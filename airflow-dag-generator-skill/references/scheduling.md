# Time-Interval & Combined Scheduling (Airflow 3.0)

In Airflow 3.0 the parameter is `schedule=` (the 2.x `schedule_interval=` is removed). It accepts
several types — pick the narrowest one that expresses your intent.

## The `schedule=` value types

| Value | Meaning |
|---|---|
| `None` | Manual / triggered only |
| `"0 6 * * *"` | Cron string |
| `"@daily"`, `"@hourly"`, `"@weekly"` | Preset cron |
| `timedelta(hours=4)` | Fixed delta between runs |
| `Asset(...)` or `[Asset, ...]` | Data-aware (see `async_assets.md`) |
| `CronTriggerTimetable(...)` | Cron without the "data interval" semantics |
| `AssetOrTimeSchedule(...)` | Asset updates **OR** a timetable |

## Cron / preset / delta

```python
from datetime import datetime, timedelta
from airflow.sdk import dag

@dag(dag_id="hourly", start_date=datetime(2024, 1, 1), schedule="@hourly", catchup=False)
def hourly(): ...

@dag(dag_id="every4h", start_date=datetime(2024, 1, 1), schedule=timedelta(hours=4), catchup=False)
def every4h(): ...
```

## CronTriggerTimetable (fire exactly at cron time)

Use this when you want the DAG to fire *at* the cron instant and don't care about Airflow's data
interval bookkeeping (common for event-style "run at 6am" jobs).

```python
from airflow.timetables.trigger import CronTriggerTimetable

@dag(
    dag_id="daily_6am",
    start_date=datetime(2024, 1, 1),
    schedule=CronTriggerTimetable("0 6 * * *", timezone="UTC"),
    catchup=False,
)
def daily_6am(): ...
```

## AssetOrTimeSchedule — interval AND event together

Runs on the timetable *and* whenever any listed asset updates. This is the recommended way to give
an event/asset-driven DAG a guaranteed minimum cadence.

```python
from airflow.timetables.assets import AssetOrTimeSchedule
from airflow.timetables.trigger import CronTriggerTimetable
from airflow.sdk import Asset, dag

@dag(
    dag_id="orders_rollup",
    start_date=datetime(2024, 1, 1),
    schedule=AssetOrTimeSchedule(
        timetable=CronTriggerTimetable("0 * * * *", timezone="UTC"),  # at least hourly
        assets=[Asset("s3://warehouse/clean_orders")],                # and on update
    ),
    catchup=False,
)
def orders_rollup(): ...
```

## Catchup & backfill (3.0)

- `catchup=False` (default in practice) — only the latest interval runs; no historical fill.
- Set `catchup=True` only when you genuinely want one run per missed interval since `start_date`.
- In 3.0, backfills are **scheduler-managed**: trigger via the UI/API/CLI
  (`airflow backfill create ...`) rather than relying on catchup.

## Timezones

Always pass an explicit `timezone=` to timetables. Use a `pendulum`/IANA name (`"America/New_York"`)
for DST-correct scheduling; `"UTC"` for infra jobs.

## Common mistakes to avoid

- Don't use `schedule_interval=` — removed in 3.0.
- Don't leave `catchup` unset if `start_date` is far in the past — you'll trigger a flood of runs.
- Don't use a plain cron string when you need exact-instant firing — prefer `CronTriggerTimetable`.
