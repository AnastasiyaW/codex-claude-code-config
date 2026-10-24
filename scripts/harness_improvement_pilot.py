#!/usr/bin/env python3
"""Compare one frozen baseline and one candidate harness pilot without mutating either.

The runner is intentionally not an agent executor. It validates receipts produced by
the task-specific evaluator, computes fixed metrics, and accepts a candidate only
when the same frozen suite improved without losing safety or held-out coverage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA = "harness-improvement-pilot/v1"
OBJECTIVES = {
    "outcome_pass_rate": "higher",
    "mean_tool_calls": "lower",
    "mean_elapsed_ms": "lower",
}
PARTITIONS = {"development", "held_out"}


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_receipt(receipt: object) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ValueError("receipt must be a JSON object")
    if receipt.get("schema") != SCHEMA:
        raise ValueError(f"receipt.schema must be {SCHEMA!r}")
    suite = receipt.get("suite")
    if not isinstance(suite, dict) or not all(
        isinstance(suite.get(key), str) and suite[key].strip()
        for key in ("id", "input_digest")
    ):
        raise ValueError("receipt.suite needs non-empty id and input_digest")
    objective = receipt.get("objective")
    if not isinstance(objective, dict):
        raise ValueError("receipt.objective must be an object")
    name = objective.get("name")
    if name not in OBJECTIVES or objective.get("direction") != OBJECTIVES[name]:
        raise ValueError("receipt.objective must name a supported metric with its fixed direction")
    cases = receipt.get("cases")
    if not isinstance(cases, list) or len(cases) < 3:
        raise ValueError("receipt.cases must contain at least three cases")
    seen: set[str] = set()
    partitions: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("every case must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError("case ids must be non-empty and unique")
        seen.add(case_id)
        partition = case.get("partition")
        if partition not in PARTITIONS:
            raise ValueError("case.partition must be development or held_out")
        partitions.add(partition)
        if type(case.get("outcome_passed")) is not bool:
            raise ValueError(f"case {case_id} needs boolean outcome_passed")
        if type(case.get("safety_passed")) is not bool:
            raise ValueError(f"case {case_id} needs boolean safety_passed")
        for metric in ("tool_calls", "elapsed_ms"):
            if not _is_nonnegative_int(case.get(metric)):
                raise ValueError(f"case {case_id} needs non-negative integer {metric}")
    if partitions != PARTITIONS:
        raise ValueError("receipt must contain both development and held_out cases")
    return receipt


def metrics(receipt: dict[str, Any]) -> dict[str, float]:
    cases = receipt["cases"]
    count = len(cases)
    return {
        "outcome_pass_rate": sum(case["outcome_passed"] for case in cases) / count,
        "mean_tool_calls": sum(case["tool_calls"] for case in cases) / count,
        "mean_elapsed_ms": sum(case["elapsed_ms"] for case in cases) / count,
    }


def compare(baseline: object, candidate: object) -> dict[str, Any]:
    baseline = validate_receipt(baseline)
    candidate = validate_receipt(candidate)
    if baseline["suite"] != candidate["suite"]:
        raise ValueError("baseline and candidate must use the same suite id and input_digest")
    if baseline["objective"] != candidate["objective"]:
        raise ValueError("baseline and candidate must use the same objective")

    baseline_cases = {case["id"]: case for case in baseline["cases"]}
    candidate_cases = {case["id"]: case for case in candidate["cases"]}
    if set(baseline_cases) != set(candidate_cases):
        raise ValueError("baseline and candidate must contain the same case ids")
    if any(
        baseline_cases[case_id]["partition"] != candidate_cases[case_id]["partition"]
        for case_id in baseline_cases
    ):
        raise ValueError("baseline and candidate must keep each case in the same partition")

    baseline_metrics = metrics(baseline)
    candidate_metrics = metrics(candidate)
    objective = candidate["objective"]["name"]
    direction = candidate["objective"]["direction"]
    improved = (
        candidate_metrics[objective] > baseline_metrics[objective]
        if direction == "higher"
        else candidate_metrics[objective] < baseline_metrics[objective]
    )
    reasons: list[str] = []
    if not improved:
        reasons.append(f"objective {objective} did not strictly improve")
    if candidate_metrics["outcome_pass_rate"] < baseline_metrics["outcome_pass_rate"]:
        reasons.append("candidate reduced outcome pass rate")
    unsafe = [case_id for case_id, case in candidate_cases.items() if not case["safety_passed"]]
    if unsafe:
        reasons.append("candidate failed safety assertions: " + ", ".join(sorted(unsafe)))
    held_out_failures = [
        case_id for case_id, case in candidate_cases.items()
        if case["partition"] == "held_out" and not case["outcome_passed"]
    ]
    if held_out_failures:
        reasons.append("candidate failed held-out cases: " + ", ".join(sorted(held_out_failures)))
    return {
        "schema": "harness-improvement-pilot-report/v1",
        "suite": baseline["suite"],
        "objective": candidate["objective"],
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "decision": "ACCEPT" if not reasons else "REJECT",
        "reasons": reasons,
    }


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read JSON from {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = compare(load_json(args.baseline), load_json(args.candidate))
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["decision"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
