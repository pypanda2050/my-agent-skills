---
name: workflow-async-data-processing
description: >
  Expert guide for building async data processing pipelines using Apache Airflow (DAG authoring,
  scheduling, task dependencies), Apache Beam (batch and streaming pipelines with the Python SDK),
  GCP Pub/Sub (publish/subscribe, message ingestion, dead-letter queues), and GCS (read/write,
  partitioning, staging patterns). Covers end-to-end orchestration — wiring Airflow DAGs to trigger
  Beam jobs that source from Pub/Sub and sink to GCS — plus error handling, retries, idempotency,
  and monitoring. Use this skill whenever the user mentions Airflow DAGs, Beam pipelines, Dataflow,
  Pub/Sub subscriptions, GCS buckets, async data pipelines, event-driven processing, or any
  combination of these GCP data-engineering tools, even if they only ask about one piece.
---

# Async Data Processing: Airflow + Beam + Pub/Sub + GCS

You are an expert data engineer. When this skill activates, help the user design, write, debug, or
optimize async data pipelines using the four pillars below. Read the relevant reference file for
the component(s) in scope before generating any code.

## Component map

| User asks about | Read |
|---|---|
| Airflow DAGs, tasks, scheduling, sensors | `references/airflow.md` |
| Beam pipelines, PCollections, transforms, runners | `references/beam.md` |
| Pub/Sub publish, subscribe, pull, push, DLQ | `references/pubsub.md` |
| GCS read/write, staging, partitioning | `references/gcs.md` |
| End-to-end orchestration or "how do I connect these" | Read all four |

## Guiding principles

**Idempotency first.** Every pipeline stage should be safe to retry. Design tasks so re-running
them produces the same result (use GCS object names that include a run ID or partition key;
acknowledge Pub/Sub messages only after successful write; use Airflow's `task_id` + `run_id` for
uniqueness).

**Decouple and buffer.** Pub/Sub is the right seam between producers and consumers. Don't let
Airflow tasks write directly to final destinations when the volume is unpredictable — use GCS as a
staging layer.

**Fail fast and surface errors.** Set explicit timeouts, retries, and alerting at every layer.
Silent failures in async pipelines are the hardest to debug.

**Choose the right runner.** Beam's `DirectRunner` is for local dev/test only. Use `DataflowRunner`
for production; size workers based on throughput, not just data volume.

## Common integration patterns

### Pattern 1: Pub/Sub → Beam Streaming → GCS
Real-time ingestion: Beam streaming job reads from a Pub/Sub subscription, windows and aggregates
messages, writes output files to GCS. Airflow is optional here (Dataflow job is long-running).
Use Airflow only to *launch* the Dataflow job and monitor its health.

### Pattern 2: GCS → Beam Batch → GCS (scheduled via Airflow)
Airflow DAG triggers daily; a `DataflowCreatePythonJobOperator` runs a Beam batch job that reads
staged files from GCS, transforms them, and writes results to a separate GCS path.

### Pattern 3: Airflow sensor → Pub/Sub pull → process → GCS
`PubSubPullSensor` waits for N messages, then an Airflow task pulls them in bulk, a downstream task
writes to GCS, and a final task acknowledges the messages.

## Code quality expectations

- Always use type hints in Python pipeline code.
- Parameterize all GCS paths and Pub/Sub topic/subscription names via Airflow `Variable` or Beam
  `PipelineOptions` — never hardcode them.
- Log at INFO level at the start/end of each transform and at WARNING/ERROR on retries or failures.
- Include a `requirements.txt` or `setup.py` snippet whenever Beam worker dependencies are needed.
- For Airflow, set `on_failure_callback` and `sla` on production DAGs.

## Checklist before declaring a pipeline production-ready

- [ ] Idempotent task logic (re-running produces same output, no duplicates)
- [ ] Dead-letter queue or error sink for unprocessable messages
- [ ] GCS paths include partition key (date, run ID) to avoid overwrites
- [ ] Beam pipeline has explicit `--temp_location` and `--staging_location`
- [ ] Airflow DAG has `retries`, `retry_delay`, `email_on_failure`, and `sla`
- [ ] Pub/Sub subscription has `ack_deadline_seconds` tuned to processing time
- [ ] Monitoring: Dataflow job metrics, Pub/Sub oldest unacked message age, GCS object count
- [ ] Local test with `DirectRunner` passes before deploying to Dataflow
