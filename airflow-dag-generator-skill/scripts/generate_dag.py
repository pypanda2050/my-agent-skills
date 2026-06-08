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
    if dag_type == "hybrid":
        lines[-1] = "from airflow.sdk import dag, task, Asset, AssetAny, AssetAll, AssetWatcher"
        hy = spec.get("hybrid", {})
        if hy.get("time_floor_cron"):
            lines.append(
                "from airflow.timetables.assets import AssetOrTimeSchedule"
            )
            lines.append(
                "from airflow.timetables.trigger import CronTriggerTimetable"
            )
        if any(e.get("type") == "sqs" for e in hy.get("events", [])):
            lines.append(
                "from airflow.providers.amazon.aws.triggers.sqs import SqsSensorTrigger"
            )
    # Dependency-wiring helpers
    deps = spec.get("dependencies", {})
    pattern = deps.get("pattern")
    sdk_import = next(i for i, l in enumerate(lines) if l.startswith("from airflow.sdk import"))
    if pattern in ("linear", "fan_out", "fan_in", "diamond") and "chain" not in lines[sdk_import]:
        lines[sdk_import] += ", chain"
    if pattern == "cross":
        lines[sdk_import] += ", cross_downstream"
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
    if dag_type == "hybrid":
        hy = spec.get("hybrid", {})
        combine = "AssetAll" if hy.get("combine") == "all" else "AssetAny"
        members = []
        members += [f"Asset({json.dumps(u)})" for u in hy.get("assets", [])]
        members += [f"Asset({json.dumps(w)})" for w in hy.get("webhooks", [])]
        members += [f"_event_{i}" for i in range(len(hy.get("events", [])))]
        asset_expr = f"{combine}(" + ", ".join(members) + ")"
        if hy.get("time_floor_cron"):
            expr = (
                "AssetOrTimeSchedule(\n"
                f'        timetable=CronTriggerTimetable({json.dumps(hy["time_floor_cron"])}, timezone="UTC"),\n'
                f"        assets={asset_expr},\n"
                "    )"
            )
            return expr, "# Hybrid: webhook/event/asset OR a time floor"
        return asset_expr, "# Hybrid: runs on any/all of webhook, event, asset sources"
    expr, _ = _schedule_literal(spec.get("schedule"), dag_type)
    return expr, "# Time-based schedule"


def _dependency_wiring(handles: list[str], deps: dict) -> str:
    """Emit task-wiring code for a named-handle list.

    Patterns:
      linear   : h0 -> h1 -> ... -> hn
      fan_out  : h0 -> [h1..hn] (parallel)
      fan_in   : [h0..h(n-1)] -> hn (join)
      diamond  : h0 -> [h1..h(n-1)] -> hn (split then join)
      cross    : cross_downstream(groups[0], groups[1]); requires deps["groups"]
      custom   : explicit edges deps["edges"] = [["a","b"], ...]
    Default (no pattern): assign handles then chain linearly if >1, else call once.
    """
    pattern = deps.get("pattern")

    def call(h: str) -> str:
        return f"{h}()"

    # Assign each task to a variable so handles can be referenced in multiple edges.
    assigns = [f"        {h} = {call(h)}" for h in handles]

    if not pattern:
        if len(handles) == 1:
            return "        " + call(handles[0])
        body = "\n".join(assigns)
        return body + "\n        chain(" + ", ".join(handles) + ")"

    if pattern == "linear":
        body = "\n".join(assigns)
        return body + "\n        chain(" + ", ".join(handles) + ")"

    if pattern == "fan_out":
        head, rest = handles[0], handles[1:]
        body = "\n".join(assigns)
        return body + f"\n        chain({head}, [{', '.join(rest)}])"

    if pattern == "fan_in":
        *rest, tail = handles
        body = "\n".join(assigns)
        return body + f"\n        chain([{', '.join(rest)}], {tail})"

    if pattern == "diamond":
        head, middle, tail = handles[0], handles[1:-1], handles[-1]
        body = "\n".join(assigns)
        return body + f"\n        chain({head}, [{', '.join(middle)}], {tail})"

    if pattern == "cross":
        groups = deps.get("groups")
        body = "\n".join(assigns)
        g1 = ", ".join(groups[0])
        g2 = ", ".join(groups[1])
        return body + f"\n        cross_downstream([{g1}], [{g2}])"

    if pattern == "custom":
        body = "\n".join(assigns)
        edges = "\n".join(f"        {a} >> {b}" for a, b in deps.get("edges", []))
        return body + "\n" + edges

    # Fallback
    return "\n".join(assigns)


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

    if dag_type == "hybrid":
        hy = spec.get("hybrid", {})
        watcher_blocks = []
        for i, ev in enumerate(hy.get("events", [])):
            watcher_blocks.append(
                f'''_event_trigger_{i} = SqsSensorTrigger(
    sqs_queue={json.dumps(ev["uri"])},
    aws_conn_id="aws_default",
)
_event_{i} = Asset(
    "{dag_id}_event_{i}",
    watchers=[AssetWatcher(name="{dag_id}_watcher_{i}", trigger=_event_trigger_{i})],
)'''
            )
        if watcher_blocks:
            pre_dag = "\n".join(watcher_blocks) + "\n\n\n"

    # task bodies
    task_lines = []
    if beam:
        task_lines.append(_beam_task(beam))
        task_lines.append("        beam_job")
    else:
        tasks = spec.get("tasks") or [{"id": "run"}]
        defs = []
        # Instantiate each task into a named handle so we can wire arbitrary graphs.
        handles = []
        for t in tasks:
            tid = t["id"]
            defs.append(
                f'''        @task
        def {tid}() -> None:
            ...'''
            )
            handles.append(tid)
        task_lines.append("\n\n".join(defs))

        wiring = _dependency_wiring(handles, spec.get("dependencies", {}))
        task_lines.append(wiring)

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
