#!/usr/bin/env python3
"""Eval harness for airflow-dag-generator-skill.

For each eval in evals.json it:
  1. Generates a DAG from the eval's `spec` using scripts/generate_dag.py.
  2. Runs the static validator (scripts/validate_dag.py) on the output.
  3. Checks every assertion against the generated source.

Assertion types:
  - contains       : `value` substring must appear in the generated file
  - not_contains   : `value` substring must NOT appear
  - validator_pass : scripts/validate_dag.py must exit 0

Outputs a per-eval pass/fail table and an overall pass rate. Exit 0 iff all pass.

Usage:
  python evals/run_evals.py            # run all, keep outputs in a temp dir
  python evals/run_evals.py --keep DIR # write generated DAGs to DIR for inspection
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
SCRIPTS = SKILL_ROOT / "scripts"


def _load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_assertion(assertion: dict, source: str, dag_path: Path, validate_fn) -> tuple[bool, str]:
    atype = assertion["type"]
    if atype == "contains":
        ok = assertion["value"] in source
        return ok, "" if ok else f"missing: {assertion['value']!r}"
    if atype == "not_contains":
        ok = assertion["value"] not in source
        return ok, "" if ok else f"unexpectedly present: {assertion['value']!r}"
    if atype == "validator_pass":
        errs = validate_fn(dag_path)
        return (not errs), "" if not errs else "; ".join(errs)
    return False, f"unknown assertion type: {atype}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", help="Directory to write generated DAGs into (default: temp)")
    ap.add_argument("--evals", default=str(HERE / "evals.json"))
    args = ap.parse_args()

    gen = _load("generate_dag", SCRIPTS / "generate_dag.py")
    validator = _load("validate_dag", SCRIPTS / "validate_dag.py")

    evals = json.loads(Path(args.evals).read_text())["evals"]

    out_dir = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="dag_evals_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    total_assertions = 0
    passed_assertions = 0
    eval_results = []

    for ev in evals:
        name = ev["name"]
        source = gen.generate(ev["spec"])
        dag_path = out_dir / f"{ev['spec']['dag_id']}.py"
        dag_path.write_text(source)

        results = []
        for a in ev["assertions"]:
            ok, detail = check_assertion(a, source, dag_path, validator.validate)
            total_assertions += 1
            passed_assertions += int(ok)
            results.append((a["name"], ok, detail))
        eval_passed = all(r[1] for r in results)
        eval_results.append((name, eval_passed, results))

    # Report
    print("=" * 64)
    print(f"airflow-dag-generator-skill evals   (output: {out_dir})")
    print("=" * 64)
    for name, eval_passed, results in eval_results:
        flag = "PASS" if eval_passed else "FAIL"
        print(f"\n[{flag}] {name}")
        for aname, ok, detail in results:
            mark = "  ok " if ok else "  XX "
            line = f"{mark} {aname}"
            if not ok:
                line += f"  -> {detail}"
            print(line)

    rate = passed_assertions / total_assertions if total_assertions else 0.0
    n_eval_pass = sum(1 for _, p, _ in eval_results if p)
    print("\n" + "-" * 64)
    print(f"Evals passed: {n_eval_pass}/{len(eval_results)}")
    print(f"Assertions:   {passed_assertions}/{total_assertions}  ({rate:.0%})")
    print("-" * 64)

    return 0 if n_eval_pass == len(eval_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
