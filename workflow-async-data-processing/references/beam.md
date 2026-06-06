# Apache Beam — Pipeline Design (Python SDK)

## Minimal pipeline skeleton

```python
import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions

def run(argv=None):
    options = PipelineOptions(argv)
    # Always set save_main_session so pickling works for lambdas/functions
    options.view_as(beam.options.pipeline_options.SetupOptions).save_main_session = True

    with beam.Pipeline(options=options) as p:
        (
            p
            | "Read" >> beam.io.ReadFromText("gs://my-bucket/input/*.json")
            | "Parse" >> beam.Map(parse_record)
            | "Filter" >> beam.Filter(is_valid)
            | "Transform" >> beam.ParDo(MyTransformFn())
            | "Write" >> beam.io.WriteToText("gs://my-bucket/output/result")
        )
```

## PipelineOptions for Dataflow

```python
from apache_beam.options.pipeline_options import (
    PipelineOptions, GoogleCloudOptions, WorkerOptions, StandardOptions,
)

def build_options(project: str, region: str, temp: str, staging: str) -> PipelineOptions:
    opts = PipelineOptions()

    google_opts = opts.view_as(GoogleCloudOptions)
    google_opts.project = project
    google_opts.region = region
    google_opts.temp_location = temp        # gs://bucket/tmp/
    google_opts.staging_location = staging  # gs://bucket/staging/

    worker_opts = opts.view_as(WorkerOptions)
    worker_opts.machine_type = "n1-standard-4"
    worker_opts.max_num_workers = 20
    worker_opts.autoscaling_algorithm = "THROUGHPUT_BASED"

    std_opts = opts.view_as(StandardOptions)
    std_opts.runner = "DataflowRunner"  # "DirectRunner" for local dev
    std_opts.streaming = False           # True for streaming pipelines

    return opts
```

## Custom DoFn with setup/teardown

```python
class EnrichRecordFn(beam.DoFn):
    def setup(self):
        # Called once per worker. Good for expensive client initialization.
        from google.cloud import bigquery
        self._bq = bigquery.Client()

    def teardown(self):
        # Optional cleanup
        pass

    def process(self, element: dict, *args, **kwargs):
        # Yield transformed records; raise to send to error output
        try:
            enriched = self._enrich(element)
            yield enriched
        except Exception as exc:
            yield beam.pvalue.TaggedOutput("errors", {"record": element, "error": str(exc)})

    def _enrich(self, record: dict) -> dict:
        ...
```

### Using tagged outputs (main + error sidecar)

```python
results = (
    records
    | "Enrich" >> beam.ParDo(EnrichRecordFn()).with_outputs("errors", main="good")
)
results.good   | "WriteGood"   >> beam.io.WriteToText("gs://bucket/out/good")
results.errors | "WriteErrors" >> beam.io.WriteToText("gs://bucket/out/errors")
```

## Reading from Pub/Sub (streaming)

```python
from apache_beam.io.gcp.pubsub import ReadFromPubSub

messages = (
    p
    | "ReadPubSub" >> ReadFromPubSub(
        subscription="projects/my-project/subscriptions/my-sub",
        with_attributes=True,   # gives PubsubMessage objects; False gives raw bytes
        id_label="message_id",  # for deduplication
        timestamp_attribute="event_time",  # use message attribute as event time
    )
    | "Decode" >> beam.Map(lambda msg: json.loads(msg.data.decode("utf-8")))
)
```

## Writing to GCS (batch)

```python
# Text/JSON
records | "WriteJSON" >> beam.io.WriteToText(
    "gs://bucket/out/data",
    file_name_suffix=".jsonl",
    num_shards=10,  # controls parallelism; 0 = Beam decides
)

# Avro
import apache_beam.io.avroio as avroio
records | "WriteAvro" >> avroio.WriteToAvro(
    "gs://bucket/out/data",
    schema=AVRO_SCHEMA,
    file_name_suffix=".avro",
    num_shards=0,
)

# Parquet
import apache_beam.io.parquetio as parquetio
records | "WriteParquet" >> parquetio.WriteToParquet(
    "gs://bucket/out/data",
    schema=PYARROW_SCHEMA,
    file_name_suffix=".parquet",
    num_shards=0,
)
```

## Windowing for streaming pipelines

```python
from apache_beam import window

# Fixed windows: group events into non-overlapping 5-minute buckets
windowed = (
    messages
    | "Window" >> beam.WindowInto(window.FixedWindows(5 * 60))
    | "GroupByKey" >> beam.GroupByKey()
    | "WriteWindow" >> beam.io.WriteToText("gs://bucket/out/window")
)

# Sliding windows: 10-min window, sliding every 2 min
sliding = messages | beam.WindowInto(window.SlidingWindows(10 * 60, 2 * 60))

# Session windows: gap-based grouping
session = messages | beam.WindowInto(window.Sessions(gap_size=60))
```

## Side inputs

```python
# Load a small lookup table into a side input
lookup = (
    p
    | "ReadLookup" >> beam.io.ReadFromText("gs://bucket/config/lookup.json")
    | "ParseLookup" >> beam.Map(json.loads)
    | "ToDict" >> beam.combiners.ToDict()
)

enriched = records | beam.Map(
    lambda record, lkp: {**record, "label": lkp.get(record["key"])},
    lkp=beam.pvalue.AsSingleton(lookup),
)
```

## Composite transforms (reusable building blocks)

```python
class ParseAndValidate(beam.PTransform):
    def expand(self, pcoll):
        return (
            pcoll
            | "Parse"    >> beam.Map(json.loads)
            | "Validate" >> beam.Filter(lambda r: r.get("id") is not None)
        )

# Usage
records | "Ingest" >> ParseAndValidate()
```

## requirements.txt for Dataflow workers

```
apache-beam[gcp]==2.56.0
google-cloud-pubsub==2.21.1
google-cloud-storage==2.16.0
pyarrow==15.0.2
```

Pass to Dataflow via `--requirements_file=requirements.txt` or set
`setup_file=./setup.py` in options for packages with native extensions.

## Testing with DirectRunner

```python
import unittest
import apache_beam as beam
from apache_beam.testing.test_pipeline import TestPipeline
from apache_beam.testing.util import assert_that, equal_to

class MyPipelineTest(unittest.TestCase):
    def test_transform(self):
        with TestPipeline() as p:
            result = (
                p
                | beam.Create([{"id": 1, "val": "a"}])
                | beam.Map(lambda r: (r["id"], r["val"].upper()))
            )
            assert_that(result, equal_to([(1, "A")]))
```
