---
name: airflow-dag-generator-skill
description: >
  Generates production-ready Apache Airflow 3.0 DAGs from a high-level spec. Supports four
  scheduling/execution paradigms: (1) synchronous tasks (classic operators run in order), (2)
  asynchronous / data-aware assets using Airflow 3.0's @asset decorator and Asset scheduling,
  (3) event-driven tasks triggered by external message queues via AssetWatcher (SQS, Kafka,
  Pub/Sub), and (4) regular time-interval / cron schedules. Also generates Apache Beam pipeline
  launch tasks that run on Flink, Spark, or Google Cloud Dataflow runners in either Java or Python.
  Use this skill whenever the user wants to author, scaffold, or generate an Airflow DAG, mentions
  Airflow 3.0 assets/datasets, deferrable/async operators, event-driven or message-queue triggered
  pipelines, cron/interval scheduling, or wants to launch a Beam/Dataflow/Flink/Spark job from
  Airflow. Also covers task-dependency wiring (linear, fan-in, fan-out, cross/complex graphs) and
  hybrid trigger DAGs combining event-driven, async-asset, time, and webhook sources in one
  schedule — even if they only describe the pipeline in plain language without naming Airflow.
---

# Airflow 3.0 DAG Generator

You generate Apache Airflow **3.0** DAGs. Airflow 3.0 changed authoring significantly — use the
new Task SDK imports (`from airflow.sdk import ...`), Assets (not legacy Datasets), and
event-driven scheduling. Never emit Airflow 2.x patterns (no `airflow.models.DAG` for new code,
no `SubDagOperator`, no `schedule_interval=`, no SLAs).

## Workflow

1. **Identify the DAG type(s)** the user needs from the table below. A single DAG can combine
   several (e.g. a time-interval schedule that also reacts to an asset update).
2. **Read the matching reference file(s)** before writing any code — they contain the exact
   Airflow 3.0 APIs, which change frequently.
3. **Generate the DAG** either by writing it directly or by using `scripts/generate_dag.py` with a
   spec dict (good for repeatable/parameterized generation).
4. **Validate** the output with `python scripts/validate_dag.py <file>` — it import-checks the DAG
   and asserts there are no cycles, the schedule is valid, and task IDs are unique.

## DAG type selection

| User intent | DAG type | Read |
|---|---|---|
| "run these steps in order", classic ETL, operators with dependencies | **Synchronous** | `references/sync_tasks.md` |
| "produce/consume a dataset", data-aware, `@asset`, async/deferrable operators | **Async asset** | `references/async_assets.md` |
| "trigger when a message arrives", SQS/Kafka/Pub-Sub, external events | **Event-driven** | `references/event_driven.md` |
| "every day at 6am", cron, `@daily`, `timedelta`, backfill | **Time interval** | `references/scheduling.md` |
| "run a Beam/Dataflow/Flink/Spark job" | (any of the above) + Beam | `references/beam_integration.md` |
| "linear/fan-in/fan-out/diamond", parallel branches, joins, cross/complex graphs, trigger rules | **Dependency wiring** | `references/dependency_patterns.md` |
| "combine webhook + event + asset", "run on either/both triggers", time floor + events | **Hybrid triggers** | `references/hybrid_triggers.md` |

## Core authoring rules (Airflow 3.0)

- Import from the Task SDK: `from airflow.sdk import dag, task, Asset, chain`. Use the `@dag` and
  `@task` decorators (TaskFlow style) by default — they're the idiomatic 3.0 form and make data
  passing explicit.
- `schedule=` accepts: `None`, a cron string (`"0 6 * * *"`), a `timedelta`, a `@preset`
  (`"@daily"`), a single `Asset` or list of Assets, an `AssetOrTimeSchedule` (combine assets +
  cron), or an `AssetWatcher`-bearing Asset for event-driven runs.
- Always set `catchup=False` unless the user explicitly wants historical backfill — 3.0 still
  defaults runs from `start_date` and accidental backfills are a common footgun.
- Give every DAG `dag_id`, `start_date`, `tags`, and a `doc_md`. Put owner/retries in
  `default_args`.
- Prefer deferrable operators (`deferrable=True`) for anything that waits on external systems
  (sensors, long jobs) — they free up worker slots and are the 3.0-recommended async path.
- Parameterize external resource names (buckets, topics, project IDs) via `Variable.get` or DAG
  `params`, never hardcode.

## Combining paradigms

The power of Airflow 3.0 is mixing these. Common combos:

- **Time interval + asset trigger**: `schedule=AssetOrTimeSchedule(timetable=CronTriggerTimetable("0 6 * * *", timezone="UTC"), assets=[Asset("s3://bucket/raw")])` — runs daily *and* whenever the raw asset updates.
- **Event-driven → Beam**: AssetWatcher on an SQS queue triggers a DAG whose single task launches a Dataflow job (see `beam_integration.md`).
- **Async asset producer → consumer chain**: an `@asset` task produces `Asset("warehouse.clean")`; a downstream DAG schedules on that asset.
- **Webhook + event + asset, with time floor**: model the webhook as `Asset("webhook://...")`, combine with a queue `AssetWatcher` and an upstream asset via `AssetAny`, and wrap in `AssetOrTimeSchedule` for a guaranteed cadence (see `hybrid_triggers.md`).
- **Fan-out → fan-in inside any of these**: e.g. an event-driven DAG that fans a payload out to parallel workers then joins with a `trigger_rule` on the reducer (see `dependency_patterns.md`).

## Output expectations

- One DAG per file, filename = `<dag_id>.py`.
- Top-of-file module docstring summarizing schedule, inputs, outputs.
- Type hints on all task functions.
- A short comment above the `schedule=` line explaining the trigger semantics.

## Evals

`evals/evals.json` defines test prompts and assertions. Run them with `python evals/run_evals.py`
(see `evals/README.md`). The eval harness generates a DAG for each prompt, then statically checks
the produced file against the assertions (correct imports, schedule type, Beam runner, no legacy
APIs). This is how you verify the generator still works after changing the skill.
