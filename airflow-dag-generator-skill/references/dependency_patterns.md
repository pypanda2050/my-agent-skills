# Task Dependency Patterns (Airflow 3.0)

How to wire task graphs. In TaskFlow, calling a `@task` function and passing its return value into
another creates the edge automatically; use `chain` / `cross_downstream` / `>>` for explicit control
when there's no data to pass. Prefer `chain`/`label`-based wiring for readability over long `>>`
chains.

## Linear (a → b → c)

Each task waits for the single upstream task.

```python
from airflow.sdk import chain

chain(extract, transform, load)
# equivalent: extract >> transform >> load
# TaskFlow data form: load(transform(extract()))
```

## Fan-out (one → many)

A single upstream task triggers several independent downstream tasks that can run in parallel.

```python
from airflow.sdk import chain

# start fans out to three parallel branches
chain(start, [branch_a, branch_b, branch_c])
# explicit: start >> [branch_a, branch_b, branch_c]
```

Dynamic fan-out (number of branches not known until runtime) — use task mapping:

```python
@task
def list_partitions() -> list[str]:
    return ["us", "eu", "apac"]

@task
def process(region: str) -> str:
    return region.upper()

process.expand(region=list_partitions())   # one mapped instance per partition
```

## Fan-in (many → one)

Several upstream tasks must all complete before a single downstream task runs (a join / reduce).

```python
chain([branch_a, branch_b, branch_c], merge)
# explicit: [branch_a, branch_b, branch_c] >> merge
```

Reduce a mapped task's outputs into one (fan-out then fan-in):

```python
mapped = process.expand(region=list_partitions())

@task
def summarize(results: list[str]) -> int:
    return len(results)

summarize(mapped)   # collects all mapped results -> single task
```

## Fan-out → fan-in (diamond)

The classic split/join. One source, parallel work, single sink.

```python
chain(start, [a, b, c], end)
# start -> a,b,c (parallel) -> end
```

## Cross dependencies (every upstream → every downstream)

When each task in group A must precede each task in group B (a full bipartite edge set):

```python
from airflow.sdk import cross_downstream, chain

cross_downstream([extract_x, extract_y], [load_p, load_q])
# extract_x,extract_y each -> load_p AND load_q
# then continue the graph:
chain([load_p, load_q], notify)
```

## Complex / mixed graphs

Compose the primitives. Keep it readable by naming sub-stages and wiring stage-by-stage rather than
one giant expression.

```python
from airflow.sdk import chain, cross_downstream

ingest   = ingest_task()
clean_a  = clean("a")
clean_b  = clean("b")
enrich   = enrich_task()
score    = score_task()
publish  = publish_task()
alert    = alert_task()

# ingest fans out to two cleaners
chain(ingest, [clean_a, clean_b])
# both cleaners fan in to enrich
chain([clean_a, clean_b], enrich)
# enrich fans out to two consumers that both feed publish
chain(enrich, [score, alert], publish)
```

### Branching inside a complex graph

```python
@task.branch
def pick(**ctx) -> str | list[str]:
    return ["score", "alert"] if ctx["params"]["full_run"] else "score"

# Downstream of a branch, use the proper trigger rule on the join so it doesn't
# get skipped when only some branches run:
@task(trigger_rule="none_failed_min_one_success")
def publish_task() -> None:
    ...
```

## Trigger rules (control fan-in semantics)

By default a task runs only when **all** upstreams succeed. Override on the join task when that's
too strict:

| `trigger_rule` | Join fires when |
|---|---|
| `all_success` (default) | every upstream succeeded |
| `all_done` | every upstream finished (success/fail/skip) |
| `none_failed_min_one_success` | no upstream failed and ≥1 succeeded (use after branching) |
| `one_success` | any one upstream succeeded (race / first-wins) |
| `all_failed` | every upstream failed (error-handling branch) |

```python
@task(trigger_rule="all_done")
def cleanup() -> None:
    ...   # always runs to tidy up, even if upstream failed
```

## Guidance

- Use **TaskFlow data passing** when tasks exchange data — the dependency is implied and the intent
  is obvious.
- Use **`chain` with lists** for fan-out/fan-in where there's no data to pass.
- Use **`cross_downstream`** only for true all-to-all edges; otherwise it obscures intent.
- Put a **trigger rule** on any join that sits downstream of branching or optional tasks, or it may
  be unexpectedly skipped.
- Keep wide fan-outs as **mapped tasks** (`.expand`) rather than copy-pasted task definitions.
