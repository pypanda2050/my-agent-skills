# Apache Beam Integration (Flink / Spark / Dataflow, Java & Python)

Airflow launches Beam pipelines via the **`apache-airflow-providers-apache-beam`** provider, which
exposes `BeamRunPythonPipelineOperator` and `BeamRunJavaPipelineOperator`. The **runner** is chosen
by the `runner` option (or Beam pipeline `--runner` arg):

| Runner option | Engine |
|---|---|
| `DirectRunner` | Local (dev/test only) |
| `FlinkRunner` | Apache Flink cluster |
| `SparkRunner` | Apache Spark cluster |
| `DataflowRunner` | Google Cloud Dataflow (managed) |

Install: `pip install apache-airflow-providers-apache-beam`. For Dataflow also install
`apache-airflow-providers-google`.

## Decision guide

- **Dataflow** — fully managed on GCP, autoscaling, best for serverless GCP shops. Pair the
  operator with Airflow's Dataflow links/hooks for job monitoring.
- **Flink** — low-latency streaming, you operate the cluster (often on K8s/YARN).
- **Spark** — batch-heavy, existing Spark infra, unified with other Spark jobs.
- **Java vs Python** — choose by where the pipeline code lives. Java runs a built jar
  (`jar=`); Python runs a `.py` file (`py_file=`) with its own interpreter/venv.

## Python pipeline on Dataflow

```python
from airflow.providers.apache.beam.operators.beam import BeamRunPythonPipelineOperator
from airflow.providers.apache.beam.hooks.beam import BeamRunnerType

run_df = BeamRunPythonPipelineOperator(
    task_id="beam_python_dataflow",
    runner=BeamRunnerType.DataflowRunner,
    py_file="gs://my-bucket/pipelines/wordcount.py",
    py_options=[],
    pipeline_options={
        "project": "{{ var.value.gcp_project }}",
        "region": "us-central1",
        "tempLocation": "gs://my-bucket/tmp/",
        "stagingLocation": "gs://my-bucket/staging/",
        "output": "gs://my-bucket/out/wordcount",
    },
    py_interpreter="python3",
    py_requirements=["apache-beam[gcp]==2.56.0"],
    py_system_site_packages=False,
    deferrable=True,   # async: don't hold a worker while Dataflow runs
)
```

## Python pipeline on Flink

```python
run_flink = BeamRunPythonPipelineOperator(
    task_id="beam_python_flink",
    runner=BeamRunnerType.FlinkRunner,
    py_file="/opt/airflow/dags/pipelines/stream.py",
    pipeline_options={
        "flink_master": "flink-jobmanager:8081",
        "environment_type": "LOOPBACK",   # or DOCKER / PROCESS for portability
        "streaming": True,
    },
    py_requirements=["apache-beam==2.56.0"],
)
```

## Java pipeline on Spark

```python
from airflow.providers.apache.beam.operators.beam import BeamRunJavaPipelineOperator
from airflow.providers.apache.beam.hooks.beam import BeamRunnerType

run_spark = BeamRunJavaPipelineOperator(
    task_id="beam_java_spark",
    runner=BeamRunnerType.SparkRunner,
    jar="/opt/jars/pipeline-bundled.jar",          # fat/shaded jar with Beam + SparkRunner
    job_class="com.example.MyPipeline",
    pipeline_options={
        "sparkMaster": "spark://spark-master:7077",
        "output": "hdfs:///out/result",
    },
)
```

## Java pipeline on Dataflow

```python
run_java_df = BeamRunJavaPipelineOperator(
    task_id="beam_java_dataflow",
    runner=BeamRunnerType.DataflowRunner,
    jar="gs://my-bucket/jars/pipeline-bundled.jar",
    job_class="com.example.MyPipeline",
    pipeline_options={
        "project": "{{ var.value.gcp_project }}",
        "region": "us-central1",
        "tempLocation": "gs://my-bucket/tmp/",
        "runner": "DataflowRunner",
    },
)
```

## Native Dataflow operators (alternative to the Beam operator)

For Python-on-Dataflow you can also use the Google provider directly, which gives richer job
tracking and a built-in async completion sensor:

```python
from airflow.providers.google.cloud.operators.dataflow import (
    DataflowCreatePythonJobOperator,
)

run = DataflowCreatePythonJobOperator(
    task_id="dataflow_native",
    py_file="gs://my-bucket/pipelines/wordcount.py",
    job_name="wordcount-{{ ds_nodash }}",
    options={
        "project": "{{ var.value.gcp_project }}",
        "region": "us-central1",
        "tempLocation": "gs://my-bucket/tmp/",
    },
    wait_until_finished=True,
)
```

## Tips

- Always set `tempLocation`/`stagingLocation` for Dataflow; jobs fail without them.
- Use `deferrable=True` (Beam operator) or the Dataflow job sensor so long Beam jobs don't pin a
  worker slot.
- Pin the Beam version in `py_requirements` (Python) or bundle it in the jar (Java) so runner and
  SDK versions match.
- For Flink/Spark portability runners, set `environment_type` (DOCKER/PROCESS/LOOPBACK) to control
  how the SDK harness is launched on workers.
