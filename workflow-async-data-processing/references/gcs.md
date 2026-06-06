# GCP Cloud Storage (GCS) — Read, Write, Staging Patterns

## Client setup

```python
from google.cloud import storage

def get_client() -> storage.Client:
    # Uses Application Default Credentials (ADC) automatically in GCP environments
    return storage.Client()
```

## Writing files

```python
def upload_json(bucket_name: str, blob_path: str, data: list[dict]) -> str:
    """Write a list of dicts to GCS as newline-delimited JSON. Returns gs:// URI."""
    client = get_client()
    blob = client.bucket(bucket_name).blob(blob_path)
    content = "\n".join(json.dumps(r) for r in data)
    blob.upload_from_string(content, content_type="application/json")
    return f"gs://{bucket_name}/{blob_path}"

def upload_file(bucket_name: str, blob_path: str, local_path: str) -> None:
    client = get_client()
    blob = client.bucket(bucket_name).blob(blob_path)
    blob.upload_from_filename(local_path)
```

### Resumable / streaming upload (large files)

```python
import io

def upload_large(bucket_name: str, blob_path: str, data_iter) -> None:
    """Stream data into GCS without buffering the whole thing in memory."""
    client = get_client()
    blob = client.bucket(bucket_name).blob(blob_path)
    with blob.open("w") as f:
        for record in data_iter:
            f.write(json.dumps(record) + "\n")
```

## Reading files

```python
def download_json(bucket_name: str, blob_path: str) -> list[dict]:
    client = get_client()
    blob = client.bucket(bucket_name).blob(blob_path)
    content = blob.download_as_text()
    return [json.loads(line) for line in content.splitlines() if line.strip()]

def download_to_file(bucket_name: str, blob_path: str, local_path: str) -> None:
    client = get_client()
    client.bucket(bucket_name).blob(blob_path).download_to_filename(local_path)
```

## Listing objects

```python
def list_blobs(bucket_name: str, prefix: str) -> list[str]:
    """Return all gs:// URIs under a prefix."""
    client = get_client()
    return [
        f"gs://{bucket_name}/{b.name}"
        for b in client.list_blobs(bucket_name, prefix=prefix)
    ]

def partition_exists(bucket_name: str, date_str: str) -> bool:
    """Check whether a daily partition has any objects (used in Airflow sensors)."""
    client = get_client()
    blobs = client.list_blobs(bucket_name, prefix=f"raw/{date_str}/", max_results=1)
    return any(True for _ in blobs)
```

## Path / partitioning conventions

Good GCS paths include a meaningful partition key so pipelines can list only what they need and
retries overwrite rather than duplicate:

```
gs://my-bucket/
  raw/
    dt=2024-01-15/             # Hive-style partitioning (compatible with BigQuery/Athena)
      part-00000.jsonl
  processed/
    dt=2024-01-15/
      run_id=abc123/           # Add run_id for idempotent reruns
        part-00000.parquet
  staging/
    job_id=xyz789/             # Temp area; cleaned up after job completes
      shard-0000-of-0010.jsonl
```

```python
def make_output_path(bucket: str, ds: str, run_id: str, shard: int = None) -> str:
    base = f"gs://{bucket}/processed/dt={ds}/run_id={run_id}"
    if shard is not None:
        return f"{base}/part-{shard:05d}.parquet"
    return base + "/"
```

## Deleting / cleaning up staging files

```python
def delete_prefix(bucket_name: str, prefix: str) -> int:
    """Delete all objects under a prefix. Returns count deleted."""
    client = get_client()
    blobs = list(client.list_blobs(bucket_name, prefix=prefix))
    if blobs:
        client.bucket(bucket_name).delete_blobs(blobs)
    return len(blobs)
```

## Copying / moving (promote staging → final)

```python
def promote_staging(
    bucket_name: str, staging_prefix: str, final_prefix: str
) -> list[str]:
    """Copy all objects from staging to final path atomically, then delete staging."""
    client = get_client()
    bucket = client.bucket(bucket_name)
    final_paths = []
    for blob in client.list_blobs(bucket_name, prefix=staging_prefix):
        dest_name = blob.name.replace(staging_prefix, final_prefix, 1)
        bucket.copy_blob(blob, bucket, new_name=dest_name)
        final_paths.append(f"gs://{bucket_name}/{dest_name}")
    # Delete staging only after all copies succeed
    delete_prefix(bucket_name, staging_prefix)
    return final_paths
```

## GCS as a Beam source / sink (quick reference)

```python
# Read all files matching a glob
p | beam.io.ReadFromText("gs://bucket/raw/dt=2024-01-15/*.jsonl")

# Write with explicit sharding
pcoll | beam.io.WriteToText(
    "gs://bucket/processed/dt=2024-01-15/part",
    file_name_suffix=".jsonl",
    num_shards=10,
)

# Read/write Parquet
from apache_beam.io import parquetio
p | parquetio.ReadFromParquet("gs://bucket/data/*.parquet")
pcoll | parquetio.WriteToParquet("gs://bucket/out/data", schema=schema)
```

## Monitoring and cost tips

- Use **Object Lifecycle Management** to auto-delete staging files after 7 days as a safety net.
- Enable **Requester Pays** on shared buckets used by multiple teams.
- Use **Nearline / Coldline** storage class for archive paths not accessed within 30/90 days.
- For high-throughput writes, distribute across many object names (avoid sequential prefixes)
  to spread load across GCS shards.
- Use **Parallel composite uploads** (`storage.blob.Blob.upload_from_file` with
  `checksum="crc32c"`) for files > 150 MB.
