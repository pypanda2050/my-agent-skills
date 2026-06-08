# Synchronous Task DAGs (Airflow 3.0)

Classic ordered execution: tasks run in a dependency graph, each waiting for upstream completion.
Use TaskFlow (`@task`) for new code — data passes via return values/XCom automatically.

## TaskFlow skeleton

```python
"""Daily sync ETL: extract -> transform -> load, run in strict order."""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.sdk import dag, task, chain

DEFAULT_ARGS = {
    "owner": "data-eng",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
}


@dag(
    dag_id="sync_etl",
    start_date=datetime(2024, 1, 1),
    schedule="0 6 * * *",        # daily 06:00 UTC
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["sync", "etl"],
    doc_md=__doc__,
)
def sync_etl():
    @task
    def extract() -> list[dict]:
        return [{"id": 1}, {"id": 2}]

    @task
    def transform(rows: list[dict]) -> list[dict]:
        return [{**r, "doubled": r["id"] * 2} for r in rows]

    @task
    def load(rows: list[dict]) -> int:
        # write to warehouse...
        return len(rows)

    load(transform(extract()))


sync_etl()
```

## Mixing classic operators with TaskFlow

```python
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task, chain


@dag(dag_id="mixed", start_date=datetime(2024, 1, 1), schedule="@daily", catchup=False)
def mixed():
    prep = BashOperator(task_id="prep", bash_command="echo preparing")

    @task
    def process() -> None:
        ...

    finish = BashOperator(task_id="finish", bash_command="echo done")

    # Explicit ordering with chain()
    chain(prep, process(), finish)


mixed()
```

## Dependency patterns

```python
# Linear
chain(a, b, c)

# Fan-out / fan-in
chain(start, [b1, b2, b3], end)   # start -> all branches -> end

# Cross dependencies
from airflow.sdk import cross_downstream
cross_downstream([a1, a2], [b1, b2])  # every a -> every b
```

## Dynamic task mapping (parallel over a list)

```python
@task
def get_files() -> list[str]:
    return ["a.csv", "b.csv", "c.csv"]


@task
def process_file(name: str) -> str:
    return name.upper()


# .expand() creates one mapped task instance per element
process_file.expand(name=get_files())
```

## Branching

```python
from airflow.sdk import task

@task.branch
def choose(**context) -> str:
    return "path_a" if context["logical_date"].day % 2 == 0 else "path_b"
```

## Retry & failure handling

- Put `retries`, `retry_delay`, `retry_exponential_backoff` in `default_args`.
- Use `on_failure_callback` for alerting (SLAs are removed in 3.0 — use Airflow's
  `Deadline`/alerting or external monitoring instead).
- Make tasks idempotent: namespace any external writes with `{{ run_id }}` or `{{ ds }}`.
