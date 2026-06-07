# Evals — airflow-dag-generator-skill

These evals verify the DAG generator produces correct Airflow 3.0 code for all four DAG types and
both Beam languages/runners.

## Run

```bash
python evals/run_evals.py                 # run all evals (outputs to a temp dir)
python evals/run_evals.py --keep ./out    # also keep generated DAGs in ./out for inspection
```

Exit code is `0` only if every eval passes. The harness prints a per-assertion table and an overall
pass rate.

## What's covered

| Eval | DAG type | Checks |
|---|---|---|
| `sync-etl-cron` | Synchronous | Task SDK imports, cron schedule, `catchup=False`, no `schedule_interval` |
| `async-asset-consumer` | Async asset | `Asset` import, data-aware `schedule=[Asset(...)]`, no legacy `airflow.datasets` |
| `event-driven-sqs` | Event-driven | `AssetWatcher`, `SqsSensorTrigger`, schedule on watched asset |
| `beam-python-dataflow` | Time interval + Beam | `BeamRunPythonPipelineOperator`, `DataflowRunner`, `deferrable=True` |
| `beam-java-flink` | Time interval + Beam | `BeamRunJavaPipelineOperator`, `FlinkRunner`, `timedelta` schedule, job class |

Every eval also runs the static validator (`scripts/validate_dag.py`), which asserts the file
parses, uses the Task SDK, has no removed 3.x APIs, sets required `@dag` kwargs, has unique task
IDs, and instantiates the DAG at module level.

## Assertion types

- `contains` — substring must appear in generated source
- `not_contains` — substring must be absent
- `validator_pass` — `validate_dag.py` must exit clean

## Extending

Add a new object to the `evals` array in `evals.json` with a `spec` (passed to
`generate_dag.generate`) and a list of `assertions`. No code changes needed.
