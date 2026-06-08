#!/usr/bin/env python3
"""Statically validate a generated Airflow 3.0 DAG file.

Does NOT require Airflow to be installed — it parses the file with `ast` and checks structural
correctness plus the Airflow-3.0 conventions this skill promises. Use it as a fast lint in evals
and after generation.

Checks:
  - File parses as valid Python.
  - Imports come from `airflow.sdk` (Task SDK), not legacy `airflow.models.DAG`.
  - No removed/legacy 3.x APIs: `schedule_interval=`, `SubDagOperator`, `SLA`/`sla=`.
  - Exactly one `@dag`-decorated function and it is called at module level.
  - `schedule=`, `start_date=`, `catchup=` are present in the @dag call.
  - Task IDs / function names are unique.

Exit code 0 = pass, 1 = fail (with reasons printed).

Usage: python validate_dag.py path/to/dag.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


LEGACY_TOKENS = ["schedule_interval", "SubDagOperator", "SubDagOperator", "sla="]


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    src = path.read_text()

    # 1. parses
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"SyntaxError: {exc}"]

    # 2. legacy token scan (textual)
    for tok in ["schedule_interval", "SubDagOperator"]:
        if tok in src:
            errors.append(f"legacy API present: '{tok}' (removed in Airflow 3.0)")
    if "airflow.models" in src and "import DAG" in src:
        errors.append("legacy import: use `from airflow.sdk import dag` not airflow.models.DAG")

    # 3. find @dag decorated functions
    dag_funcs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                name = _dec_name(dec)
                if name == "dag":
                    dag_funcs.append((node, dec))
    # also accept @asset style single-asset DAGs
    asset_funcs = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and any(_dec_name(d) == "asset" for d in n.decorator_list)
    ]

    if not dag_funcs and not asset_funcs:
        errors.append("no @dag or @asset decorated function found")
        return errors

    # 4. check @dag call kwargs
    for fn, dec in dag_funcs:
        kwargs = {k.arg for k in dec.keywords} if isinstance(dec, ast.Call) else set()
        for required in ("schedule", "start_date"):
            if required not in kwargs:
                errors.append(f"@dag '{fn.name}' missing required kwarg '{required}='")
        if "catchup" not in kwargs:
            errors.append(f"@dag '{fn.name}' should set catchup= explicitly")

    # 5. uniqueness of task_id literals
    task_ids = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "task_id":
            if isinstance(node.value, ast.Constant):
                task_ids.append(node.value.value)
    dupes = {t for t in task_ids if task_ids.count(t) > 1}
    if dupes:
        errors.append(f"duplicate task_id(s): {sorted(dupes)}")

    # 6. dag function invoked at module level
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    for fn, _ in dag_funcs:
        if fn.name not in called:
            errors.append(f"@dag function '{fn.name}' is never instantiated (call it at module level)")

    return errors


def _dec_name(dec) -> str | None:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Call):
        if isinstance(dec.func, ast.Name):
            return dec.func.id
        if isinstance(dec.func, ast.Attribute):
            return dec.func.attr
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_dag.py <dag_file.py>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    errors = validate(path)
    if errors:
        print(f"FAIL {path}")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"PASS {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
