# Hybrid Triggers: Event-Driven + Async Asset + Webhook (Airflow 3.0)

Real pipelines rarely fire on a single trigger type. Airflow 3.0 lets you combine **asset updates**,
**queue events (AssetWatcher)**, **time**, and external **webhooks** into one DAG's start condition.
This file shows how to mix them coherently.

## The building blocks

| Trigger source | Mechanism |
|---|---|
| Data produced upstream | `Asset(...)` in `schedule=` (data-aware) |
| Message on a queue | `Asset(..., watchers=[AssetWatcher(trigger=...)])` (event-driven) |
| Clock / floor cadence | `CronTriggerTimetable` / cron string |
| External webhook / API | REST API `POST /dags/{id}/dagRuns` **or** the Asset REST endpoint to emit an asset event |

The unifying idea in 3.0: **everything can be expressed as an asset event**, so you combine sources
with asset boolean logic (`AssetAny`, `AssetAll`, `&`, `|`) and `AssetOrTimeSchedule` for the time
axis.

## Pattern A: Asset OR event (run on either)

Run when upstream data is ready **or** a queue message arrives — whichever happens first.

```python
from datetime import datetime
from airflow.sdk import Asset, AssetAny, AssetWatcher, dag, task
from airflow.providers.amazon.aws.triggers.sqs import SqsSensorTrigger

# Event-driven asset (queue)
_trigger = SqsSensorTrigger(sqs_queue="https://sqs.../ingest", aws_conn_id="aws_default")
queue_event = Asset("ingest_queue_event", watchers=[AssetWatcher(name="ingest_w", trigger=_trigger)])

# Data-aware asset (upstream producer)
upstream_data = Asset("s3://warehouse/clean_orders")


@dag(
    dag_id="hybrid_asset_or_event",
    start_date=datetime(2024, 1, 1),
    # Run when EITHER the queue fires OR upstream data updates.
    schedule=AssetAny(queue_event, upstream_data),
    catchup=False,
    tags=["hybrid", "event-driven", "asset"],
)
def hybrid_asset_or_event():
    @task
    def handle(**context) -> None:
        ...
    handle()


hybrid_asset_or_event()
```

Use `AssetAll(...)` (or `&`) instead when you need **both** — e.g. data is staged *and* a "go"
message has arrived.

## Pattern B: (Asset OR event) AND a time floor

Event/asset-driven, but guaranteed to also run at least on a schedule so it never stalls silently.

```python
from airflow.timetables.assets import AssetOrTimeSchedule
from airflow.timetables.trigger import CronTriggerTimetable

@dag(
    dag_id="hybrid_with_time_floor",
    start_date=datetime(2024, 1, 1),
    schedule=AssetOrTimeSchedule(
        timetable=CronTriggerTimetable("0 * * * *", timezone="UTC"),  # hourly floor
        assets=AssetAny(queue_event, upstream_data),                  # plus event/asset
    ),
    catchup=False,
)
def hybrid_with_time_floor(): ...
```

## Pattern C: Webhook trigger

Webhooks don't have a native `schedule=` type — they come in over the **REST API**. Two idiomatic
approaches:

### C1. Webhook → trigger a DAG run directly

Point your webhook receiver (API gateway, Cloud Function, small FastAPI app) at the Airflow REST
API. The DAG itself uses `schedule=None` (externally triggered).

```python
@dag(dag_id="webhook_triggered", start_date=datetime(2024, 1, 1), schedule=None, catchup=False,
     tags=["hybrid", "webhook"])
def webhook_triggered():
    @task
    def handle(**context) -> None:
        payload = context["params"]   # webhook posts payload via conf -> params
        ...
    handle()

webhook_triggered()
```

The webhook backend calls:

```
POST /api/v2/dags/webhook_triggered/dagRuns
{ "logical_date": "2024-06-07T12:00:00Z", "conf": {"order_id": 123} }
```

### C2. Webhook → emit an asset event (so it composes with assets)

Better when you want the webhook to participate in hybrid asset logic. The webhook backend POSTs to
the **asset events** endpoint; any DAG scheduled on that asset then runs. This makes a webhook just
another asset source you can `AssetAny`/`AssetAll` with queues and upstream data.

```
POST /api/v2/assets/events
{ "uri": "webhook://orders/created", "extra": {"order_id": 123} }
```

```python
webhook_asset = Asset("webhook://orders/created")

@dag(
    dag_id="hybrid_full",
    start_date=datetime(2024, 1, 1),
    # Webhook OR queue OR upstream-data, with an hourly floor.
    schedule=AssetOrTimeSchedule(
        timetable=CronTriggerTimetable("0 * * * *", timezone="UTC"),
        assets=AssetAny(webhook_asset, queue_event, upstream_data),
    ),
    catchup=False,
    tags=["hybrid", "webhook", "event-driven", "asset"],
)
def hybrid_full():
    @task
    def route(**context) -> None:
        # Inspect which source fired via inlet asset events.
        for asset, events in context["inlet_events"].items():
            ...
    route()

hybrid_full()
```

## Reading "which trigger fired" inside the DAG

A hybrid DAG usually needs to branch on the source. Inlet asset events carry the payload/metadata:

```python
@task.branch
def route(**context) -> str:
    events = context["inlet_events"]
    if events[webhook_asset]:
        return "handle_webhook"
    if events[queue_event]:
        return "handle_queue"
    return "handle_scheduled"
```

## Design guidance

- **Model every external source as an asset** (`webhook://`, queue event, `s3://...`) so you can
  combine them with `AssetAny`/`AssetAll`. This keeps the `schedule=` expression declarative.
- **Always add a time floor** (`AssetOrTimeSchedule`) to event/webhook DAGs so a dropped event or
  silent webhook doesn't leave data unprocessed.
- **Idempotency is mandatory** — webhooks retry, queues deliver at-least-once, and the time floor
  may overlap with an event run. Dedupe on a business key.
- **Secure the webhook backend**, not Airflow — validate signatures/HMAC at your receiver before it
  calls the Airflow API or emits the asset event.
- The **triggerer** must be running for AssetWatcher-based event sources.
