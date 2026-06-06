# GCP Pub/Sub — Publish, Subscribe, Dead-Letter Queues

## Publishing messages

```python
from google.cloud import pubsub_v1
import json

def get_publisher(project: str, topic: str) -> pubsub_v1.PublisherClient:
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project, topic)
    return publisher, topic_path

def publish_messages(project: str, topic: str, records: list[dict]) -> None:
    publisher, topic_path = get_publisher(project, topic)
    futures = []
    for record in records:
        data = json.dumps(record).encode("utf-8")
        # Attributes are optional key-value metadata (strings only)
        future = publisher.publish(
            topic_path,
            data,
            source="my-service",
            event_type=record.get("type", "unknown"),
        )
        futures.append(future)

    # Block until all publishes confirm
    for f in futures:
        try:
            msg_id = f.result(timeout=30)
        except Exception as exc:
            # Implement your retry / DLQ logic here
            raise RuntimeError(f"Publish failed: {exc}") from exc
```

### Batching for throughput

```python
batch_settings = pubsub_v1.types.BatchSettings(
    max_messages=1000,      # flush after N messages
    max_bytes=1024 * 1024,  # flush after 1 MB
    max_latency=0.05,       # flush after 50 ms
)
publisher = pubsub_v1.PublisherClient(batch_settings=batch_settings)
```

## Subscribing — streaming pull (long-running consumer)

```python
from concurrent.futures import TimeoutError
from google.cloud import pubsub_v1

def subscribe_streaming(project: str, subscription: str, timeout: float = 60.0) -> None:
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = subscriber.subscription_path(project, subscription)

    def callback(message: pubsub_v1.types.PubsubMessage) -> None:
        try:
            data = json.loads(message.data.decode("utf-8"))
            process(data)
            message.ack()
        except Exception as exc:
            # nack → message redelivered up to retry limit, then goes to DLQ
            message.nack()

    flow_control = pubsub_v1.types.FlowControl(
        max_messages=200,         # max outstanding un-acked messages per thread
        max_bytes=50 * 1024 * 1024,
    )
    streaming_pull_future = subscriber.subscribe(
        sub_path, callback=callback, flow_control=flow_control
    )
    with subscriber:
        try:
            streaming_pull_future.result(timeout=timeout)
        except TimeoutError:
            streaming_pull_future.cancel()
```

## Subscribing — synchronous pull (batch / Airflow task)

```python
def pull_batch(project: str, subscription: str, max_messages: int = 100) -> list[dict]:
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = subscriber.subscription_path(project, subscription)

    response = subscriber.pull(
        request={"subscription": sub_path, "max_messages": max_messages},
        retry=pubsub_v1.gapic.transports.grpc.DEFAULT_RETRY,
    )

    records = []
    ack_ids = []
    for msg in response.received_messages:
        data = json.loads(msg.message.data.decode("utf-8"))
        records.append(data)
        ack_ids.append(msg.ack_id)

    # Ack only after successful processing
    if ack_ids:
        subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})

    return records
```

## Dead-letter queue setup (Terraform / gcloud pattern)

When a message fails `max_delivery_attempts` times, Pub/Sub forwards it to the DLQ topic.

```hcl
# Terraform
resource "google_pubsub_topic" "main" { name = "my-topic" }
resource "google_pubsub_topic" "dlq"  { name = "my-topic-dlq" }

resource "google_pubsub_subscription" "main" {
  name  = "my-sub"
  topic = google_pubsub_topic.main.id

  ack_deadline_seconds = 60   # tune to your expected processing time

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dlq.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_pubsub_subscription" "dlq_sub" {
  name  = "my-topic-dlq-sub"
  topic = google_pubsub_topic.dlq.id
  # Monitor this subscription; pages when age of oldest unacked message > threshold
}
```

## Key configuration knobs

| Setting | Guidance |
|---|---|
| `ack_deadline_seconds` | Set to 2× your p99 processing time. Max 600 s. Extend mid-processing with `modify_ack_deadline`. |
| `max_delivery_attempts` | 5–10 for transient errors; use DLQ to catch persistent failures. |
| `retain_acked_messages` | Enable during development for replay; disable in prod to save cost. |
| `message_retention_duration` | Default 7 days; increase for event replay scenarios. |
| `flow_control.max_messages` | Limit memory usage on high-volume subscriptions. |

## Extending ack deadline for long-running tasks

```python
def process_with_extension(message: pubsub_v1.types.PubsubMessage, sub_path: str) -> None:
    import threading

    subscriber = pubsub_v1.SubscriberClient()

    def keep_alive():
        # Extend by 60 s every 30 s while processing
        while not done.is_set():
            subscriber.modify_ack_deadline(
                request={"subscription": sub_path, "ack_ids": [message.ack_id], "ack_deadline_seconds": 60}
            )
            done.wait(30)

    done = threading.Event()
    t = threading.Thread(target=keep_alive, daemon=True)
    t.start()
    try:
        do_heavy_work(message)
        message.ack()
    finally:
        done.set()
```

## Monitoring alerts (Cloud Monitoring MQL)

```
# Oldest unacked message age > 5 minutes → fire alert
fetch pubsub_subscription
| metric 'pubsub.googleapis.com/subscription/oldest_unacked_message_age'
| filter resource.subscription_id = 'my-sub'
| align next_older(1m)
| every 1m
| condition val() > 300  # seconds
```
