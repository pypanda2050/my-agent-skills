# Event-Driven DAGs (Airflow 3.0 AssetWatcher)

Airflow 3.0 introduced **event-driven scheduling**: a DAG runs in (near) real time when an external
message arrives on a queue, instead of on a clock. This is built on **AssetWatcher** + a
**message-queue trigger**. The scheduler listens to the queue via the triggerer; each qualifying
message materializes the asset and kicks off scheduled DAGs.

Requires the `apache-airflow-providers-common-messaging` provider plus the source provider
(Amazon for SQS, etc.).

## AssetWatcher with an SQS queue

```python
"""Event-driven: runs whenever a message lands on the ingest SQS queue."""
from datetime import datetime

from airflow.sdk import Asset, AssetWatcher, dag, task
from airflow.providers.amazon.aws.triggers.sqs import SqsSensorTrigger

# The trigger the scheduler watches. When it fires, the asset updates.
trigger = SqsSensorTrigger(
    sqs_queue="https://sqs.us-east-1.amazonaws.com/123456789012/ingest-queue",
    aws_conn_id="aws_default",
    waiter_delay=30,
)

watcher = AssetWatcher(name="ingest_queue_watcher", trigger=trigger)

# Attach the watcher to an asset via the `watchers=` arg.
ingest_event = Asset("ingest_event", watchers=[watcher])


@dag(
    dag_id="event_driven_ingest",
    start_date=datetime(2024, 1, 1),
    # Event-driven: schedule on the watched asset.
    schedule=[ingest_event],
    catchup=False,
    tags=["event-driven", "sqs"],
    doc_md=__doc__,
)
def event_driven_ingest():
    @task
    def handle_event(**context) -> None:
        # The triggering message payload is available via the asset events.
        events = context["inlet_events"][ingest_event]
        for ev in events:
            payload = ev.extra  # message body / attributes
            process(payload)

    handle_event()


event_driven_ingest()
```

## Other message-queue triggers

The pattern is identical — swap the trigger:

```python
# Generic common-messaging trigger (provider: common.messaging)
from airflow.providers.common.messaging.triggers.msg_queue import MessageQueueTrigger

trigger = MessageQueueTrigger(
    queue="kafka://broker:9092/my-topic",   # scheme selects the backend
)
watcher = AssetWatcher(name="kafka_watcher", trigger=trigger)
events = Asset("kafka_events", watchers=[watcher])
```

Supported schemes depend on installed providers (Kafka, SQS, and others via the common-messaging
abstraction). For Google Pub/Sub, use a pull-based deferrable sensor (see below) if no native
watcher trigger is available in your provider version.

## Fallback: deferrable pull sensor (when no watcher trigger exists)

If your queue backend has no AssetWatcher trigger yet, approximate event-driven behavior with a
continuously-rescheduling deferrable sensor:

```python
from airflow.providers.google.cloud.sensors.pubsub import PubSubPullSensor

wait = PubSubPullSensor(
    task_id="wait_for_message",
    project_id="{{ var.value.gcp_project }}",
    subscription="ingest-sub",
    max_messages=10,
    ack_messages=False,
    deferrable=True,      # async wait
    poke_interval=15,
)
```

## Design notes

- **Idempotency is critical** — queues deliver at-least-once. Dedupe on a message ID and make
  handlers safe to re-run.
- **Combine with time** to guarantee a floor cadence even with no events:
  `schedule=AssetOrTimeSchedule(timetable=CronTriggerTimetable("0 * * * *", timezone="UTC"), assets=[ingest_event])`
  (see `scheduling.md`).
- The **triggerer** process must be running for event-driven scheduling to work.
- Tune the trigger's poll/waiter delay to balance latency vs. cost.
