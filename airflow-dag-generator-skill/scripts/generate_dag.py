#!/usr/bin/env python3
"""Generate an Airflow 3.0 DAG file from a spec dict.

This is a deterministic scaffolder for the four supported DAG types. It emits idiomatic
Airflow 3.0 (Task SDK) code so callers don't reinvent the boilerplate each time.

Spec schema (dict or JSON):
{
  "dag_id": "my_dag",                      # required
  "dag_type": "sync" | "async_asset" | "event_driven" | "time_interval",
  "schedule": "0 6 * * *",                 # cron | "@daily" | "timedelta:hours=4" | None
  "start_date": "2024-01-01",
  "tags": ["etl"],
  "catchup": false,
  "tasks": [{"id": "extract", "kind": "python"}, ...],   # for sync
  "assets_in": ["s3://warehouse/clean"],   # for async_asset (schedule on these)
  "asset_out": "s3://warehouse/agg",       # optional produced asset
  "queue": {"type": "sqs", "uri": "https://sqs.../q"},   # for event_driven
  "beam": {                                # optional Beam launch task
    "language": "python" | "java",
    "runner": "DataflowRunner" | "FlinkRunner" | "SparkRunner" | "DirectRunner",
    "py_file": "gs://.../p.py",            # python
    "jar": "/opt/jars/p.jar",             # java
    "job_class": "com.example.Pipeline",  # java
    "options": {"project": "...", "region": "us-central1"}
  }
}

Usage:
  python generate_dag.py spec.json [-o out_dir]
  python generate_dag.py - <<<'{"dag_id": "...", ...}'    # spec on stdin
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _schedule_literal(schedule, dag_type: str) -> tuple[str, str]:
    """Return (python_expr_for_schedule, extra_imports). Comment added by caller."""
    if schedule is None or schedule == "None":
        return "None", ""
    if isinstance(schedule, str) and schedule.startswith("timedelta:"):
        kw = schedule.split(":", 1)[1]
        return f"timedelta({kw})", ""
    # plain cron / preset string
    return json.dumps(schedule), ""


def _imports(spec: dict) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        "from datetime import datetime, timedelta",
        "",
        "from airflow.sdk import dag, task",
    ]
    dag_type = spec["dag_type"]
    if dag_type == "async_asset":
        lines[-1] = "from airflow.sdk import dag, task, Asset"
    if dag_type == "event_driven":
        lines[-1] = "from airflow.sdk import dag, task, Asset, AssetWatcher"
    beam = spec.get("beam")
    if beam:
        if beam["language"] == "python":
            lines.append(
                "from airflow.providers.apache.beam.operators.beam import "
                "BeamRunPythonPipelineOperator"
            )
        else:
            lines.append(
                "from airflow.providers.apache.beam.operators.beam import "
                "BeamRunJavaPipelineOperator"
            )
        lines.append(
            "from airflow.providers.apache.beam.hooks.beam import BeamRunnerType"
        )
    if dag_type == "event_driven" and spec.get("queue", {}).get("type") == "sqs":
        lines.append(
            "from airflow.providers.amazon.aws.triggers.sqs import SqsSensorTrigger"
        )
    return "\n".join(lines)


def _beam_task(beam: dict) -> str:
    runner = beam["runner"]
    opts = json.dumps(beam.get("options", {}), indent=8).replace("\n}", "\n    }")
    if beam["language"] == "python":
        return f'''        beam_job = BeamRunPythonPipelineOperator(
            task_id="beam_python",
            runner=BeamRunnerType.{runner},
            py_file={json.dumps(beam.get("py_file", ""))},
            pipeline_options={opts},
            deferrable=True,
        )'''
    return f'''        beam_job = BeamRunJavaPipelineOperator(
            task_id="beam_java",
            runner=BeamRunnerType.{runner},
            jar={json.dumps(beam.get("jar", ""))},
            job_class={json.dumps(beam.get("job_class", ""))},
            pipeline_options={opts},
        )'''


def _schedule_block(spec: dict) -> tuple[str, str]:
    """Return (schedule_expr, comment)."""
    dag_type = spec["dag_type"]
    if dag_type == "async_asset":
        assets = spec.get("assets_in", [])
        expr = "[" + ", ".join(f"Asset({json.dumps(a)})" for a in assets) + "]"
        return expr, "# Data-aware: runs when these assets update"
    if dag_type == "event_driven":
        return "[event_asset]", "# Event-driven: runs on each watched-queue message"
    expr, _ = _schedule_literal(spec.get("schedule"), dag_type)
    return expr, "# Time-based schedule"


def generate(spec: dict) -> str:
    dag_id = spec["dag_id"]
    dag_type = spec["dag_type"]
    start = spec.get("start_date", "2024-01-01")
    year, month, day = start.split("-")
    tags = spec.get("tags", [dag_type])
    catchup = spec.get("catchup", False)
    beam = spec.get("beam")

    sched_expr, sched_comment = _schedule_block(spec)
    pre_dag = ""

    if dag_type == "event_driven":
        q = spec["queue"]
        pre_dag = f'''_trigger = SqsSensorTrigger(
    sqs_queue={json.dumps(q["uri"])},
    aws_conn_id="aws_default",
)
_watcher = AssetWatcher(name="{dag_id}_watcher", trigger=_trigger)
event_asset = Asset("{dag_id}_event", watchers=[_watcher])


'''

    # task bodies
    task_lines = []
    if beam:
        task_lines.append(_beam_task(beam))
        task_lines.append("        beam_job")
    else:
        tasks = spec.get("tasks") or [{"id": "run"}]
        prev = None
        defs = []
        calls = []
        for t in tasks:
            tid = t["id"]
            defs.append(
                f'''        @task
        def {tid}() -> None:
            ...'''
            )
            calls.append(f"{tid}()")
        task_lines.append("\n\n".join(defs))
        if len(calls) > 1:
            # chain them
            task_lines.append("\n        from airflow.sdk import chain")
            task_lines.append("        chain(" + ", ".join(calls) + ")")
        else:
            task_lines.append("        " + calls[0])

    outlet = ""
    if spec.get("asset_out") and not beam:
        outlet = ""  # kept simple; outlets documented in references

    body = "\n\n".join(task_lines)

    docstring = f'"""Auto-generated {dag_type} DAG: {dag_id}."""'

    return f'''{docstring}
{_imports(spec)}

DEFAULT_ARGS = {{
    "owner": "data-eng",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
}}


{pre_dag}@dag(
    dag_id={json.dumps(dag_id)},
    start_date=datetime({int(year)}, {int(month)}, {int(day)}),
    {sched_comment}
    schedule={sched_expr},
    catchup={catchup},
    default_args=DEFAULT_ARGS,
    tags={json.dumps(tags)},
    doc_md=__doc__,
)
def {dag_id}():
{body}


{dag_id}()
'''


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate an Airflow 3.0 DAG from a spec")
    ap.add_argument("spec", help="Path to spec JSON, or '-' for stdin")
    ap.add_argument("-o", "--out-dir", default=".", help="Output directory")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text()
    spec = json.loads(raw)

    code = generate(spec)
    out = Path(args.out_dir) / f"{spec['dag_id']}.py"
    out.write_text(code)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
