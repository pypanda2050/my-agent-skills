# Apache Airflow — DAG Authoring & Orchestration

## DAG skeleton (Airflow 2.x, TaskFlow API)

```python
from __future__ import annotations
from datetime import datetime, timedelta
from airflow.decorators import dag, task
from airflow.models import Variable

DEFAULT_ARGS = {
    "owner": "data-eng",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=60),
    "email_on_failure": True,
    "email": ["alerts@example.com"],
    "on_failure_callback": lambda ctx: ...,  # custom alerting
}

@dag(
    dag_id="gcs_beam_pipeline",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["beam", "gcs"],
    doc_md="Daily batch pipeline: GCS → Beam → GCS",
)
def gcs_beam_pipeline():
    @task
    def validate_input(ds: str) -> dict:
        """Check that the expected GCS partition exists before launching Beam."""
        from google.cloud import storage
        bucket = Variable.get("input_bucket")
        prefix = f"raw/{ds}/"
        client = storage.Client()
        blobs = list(client.list_blobs(bucket, prefix=prefix, max_results=1))
        if not blobs:
            raise ValueError(f"No input data found for {ds} at gs://{bucket}/{prefix}")
        return {"bucket": bucket, "prefix": prefix, "ds": ds}

    @task
    def launch_beam_job(input_meta: dict) -> str:
        """Submit Dataflow job and return the job ID."""
        # See beam.md for the full Dataflow submission pattern
        from apache_beam.options.pipeline_options import PipelineOptions
        job_id = _submit_dataflow(input_meta)  # your submit helper
        return job_id

    @task.sensor(poke_interval=60, timeout=3600, mode="reschedule")
    def wait_for_job(job_id: str) -> bool:
        """Poll Dataflow until the job is DONE or raise on failure."""
        from googleapiclient import discovery
        df = discovery.build("dataflow", "v1b3")
        project = Variable.get("gcp_project")
        region = Variable.get("gcp_region", default_var="us-central1")
        job = df.projects().locations().jobs().get(
            projectId=project, location=region, jobId=job_id
        ).execute()
        state = job["currentState"]
        if state == "JOB_STATE_DONE":
            return True
        if state in ("JOB_STATE_FAILED", "JOB_STATE_CANCELLED"):
            raise RuntimeError(f"Dataflow job {job_id} ended with state {state}")
        return False  # still running → poke again

    meta = validate_input()
    job_id = launch_beam_job(meta)
    wait_for_job(job_id)

gcs_beam_pipeline()
```

## Triggering Dataflow from Airflow (alternative: built-in operator)

```python
from airflow.providers.google.cloud.operators.dataflow import (
    DataflowCreatePythonJobOperator,
)

run_beam = DataflowCreatePythonJobOperator(
    task_id="run_beam_batch",
    py_file="gs://{{ var.value.deploy_bucket }}/pipelines/my_pipeline.py",
    job_name="my-pipeline-{{ ds_nodash }}",
    options={
        "project": "{{ var.value.gcp_project }}",
        "region": "{{ var.value.gcp_region }}",
        "temp_location": "gs://{{ var.value.temp_bucket }}/tmp/",
        "staging_location": "gs://{{ var.value.temp_bucket }}/staging/",
        "input": "gs://{{ var.value.input_bucket }}/raw/{{ ds }}/",
        "output": "gs://{{ var.value.output_bucket }}/processed/{{ ds }}/",
    },
    wait_until_finished=True,  # blocks task until Dataflow finishes
    gcp_conn_id="google_cloud_default",
)
```

## Pub/Sub sensor pattern

```python
from airflow.providers.google.cloud.sensors.pubsub import PubSubPullSensor
from airflow.providers.google.cloud.operators.pubsub import PubSubPullOperator

# Pull up to 50 messages; ack them only after downstream task succeeds
pull = PubSubPullSensor(
    task_id="wait_for_messages",
    project_id="{{ var.value.gcp_project }}",
    subscription="{{ var.value.pubsub_subscription }}",
    max_messages=50,
    ack_messages=False,   # ack manually after processing
    poke_interval=30,
    timeout=600,
    mode="reschedule",
    gcp_conn_id="google_cloud_default",
)
```

## Key Airflow variables to manage

Always store secrets/config in `Variables` or `Connections`, never in DAG code:

```python
# Read in tasks
from airflow.models import Variable
project = Variable.get("gcp_project")
bucket  = Variable.get("input_bucket")
# With a default
region  = Variable.get("gcp_region", default_var="us-central1")
```

## SLA and alerting

```python
from datetime import timedelta
from airflow.models import SlaMiss

def sla_miss_callback(dag, task_list, blocking_task_list, slas: list[SlaMiss], blocking_tis):
    # Send a PagerDuty / Slack alert
    pass

@dag(sla_miss_callback=sla_miss_callback, ...)
def my_dag():
    @task(sla=timedelta(hours=2))
    def critical_task(): ...
```

## Retry best practices

- Use `retry_exponential_backoff=True` with a `max_retry_delay` to avoid thundering herd.
- For transient GCP errors (quota exceeded, 503), `retries=3` + 5 min base delay is a good default.
- Make every task idempotent: use the Airflow `{{ run_id }}` or `{{ ds }}` macro to namespace
  GCS output paths so a retry writes to a fresh location (or overwrites deterministically).

## XCom guidelines

- Pass small metadata (job IDs, counts, GCS paths) via XCom.
- Never push large data through XCom — store it in GCS and pass the path.
- Use `@task(multiple_outputs=True)` to return a dict and push each key as a separate XCom.
