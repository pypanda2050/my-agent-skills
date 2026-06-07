# Async / Data-Aware Asset DAGs (Airflow 3.0)

Airflow 3.0 renamed **Datasets → Assets** and added the `@asset` decorator for asset-first
authoring. Assets enable data-aware scheduling: a DAG runs when the assets it depends on are
updated, instead of (or in addition to) a clock schedule. Pair with **deferrable operators** for
true async waiting that doesn't hold a worker slot.

## Asset-oriented authoring with `@asset`

The `@asset` decorator defines a single-task DAG that *produces* an asset. The function body is the
materialization logic; the asset updates when it completes.

```python
"""Produces the `clean_orders` asset from raw order files."""
from airflow.sdk import asset


@asset(schedule="@daily", uri="s3://warehouse/clean_orders", tags=["assets"])
def clean_orders() -> dict:
    # ... read raw, clean, write to s3://warehouse/clean_orders ...
    return {"rows": 4200}   # returned metadata is attached to the asset event
```

## Consuming assets (data-aware scheduling)

A downstream DAG schedules on one or more assets. It runs as soon as the upstream asset emits an
update event — no polling, no cron.

```python
from datetime import datetime
from airflow.sdk import dag, task, Asset

CLEAN_ORDERS = Asset("s3://warehouse/clean_orders")


@dag(
    dag_id="aggregate_orders",
    start_date=datetime(2024, 1, 1),
    # Runs whenever clean_orders is updated. List = AND (all must update).
    schedule=[CLEAN_ORDERS],
    catchup=False,
    tags=["async", "assets"],
)
def aggregate_orders():
    @task
    def aggregate() -> None:
        ...

    aggregate()


aggregate_orders()
```

### Asset logical operators (3.0)

```python
from airflow.sdk import Asset, AssetAny, AssetAll

a, b, c = Asset("s3://a"), Asset("s3://b"), Asset("s3://c")

schedule = AssetAny(a, b)          # run when ANY of a, b updates (OR)
schedule = AssetAll(a, b, c)       # run when ALL have updated (AND)
schedule = (a & b) | c             # operator form: (a AND b) OR c
```

## Producing assets from a normal task (`outlets`)

```python
@task(outlets=[Asset("s3://warehouse/clean_orders")])
def write_clean() -> None:
    ...   # completing this task emits an update event for the asset
```

## Asset with metadata extra / aliases

```python
from airflow.sdk import Asset, Metadata

@task(outlets=[Asset("s3://warehouse/clean_orders")])
def write_clean():
    yield Metadata(Asset("s3://warehouse/clean_orders"), extra={"row_count": 4200})
```

## Deferrable / async operators (free the worker while waiting)

Use `deferrable=True` for anything that waits on an external system. The task suspends to the
triggerer process instead of blocking a worker slot — this is the recommended async pattern in 3.0.

```python
from airflow.providers.standard.sensors.time_delta import TimeDeltaSensorAsync
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor

wait = S3KeySensor(
    task_id="wait_for_input",
    bucket_key="s3://bucket/raw/{{ ds }}/_SUCCESS",
    deferrable=True,          # defers to triggerer; no worker slot held
    poke_interval=60,
    timeout=60 * 60,
)
```

## Custom async sensor

```python
@task.sensor(poke_interval=30, timeout=3600, mode="reschedule")
def wait_for_condition() -> bool:
    return external_system_ready()   # return False to reschedule, True to proceed
```

## When to use which

- **Asset scheduling** when the trigger is "some data was produced" and you control the producer.
- **Deferrable sensor** when you must wait on an external resource you don't control.
- **AssetOrTimeSchedule** (see `scheduling.md`) when you want both "on update" and "at least daily".
