#!/usr/bin/env python3
"""Compare one frozen baseline and one candidate harness pilot without mutating either.

The runner is intentionally not an agent executor. It validates receipts produced by
the task-specific evaluator, computes fixed metrics, and accepts a candidate only
when the same frozen suite improved without losing safety or held-out coverage.

Three rules come from Google's Harness2 method, adapted to frozen receipts:
one change per candidate, a case judged on repeated runs (a defect seen in one of
k runs is noise), and a lesson ledger that records one lesson or NO_ENTRY per run.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA = "harness-improvement-pilot/v1"
OBJECTIVES = {
    "outcome_pass_rate": "higher",
    "mean_tool_calls": "lower",
    "mean_elapsed_ms": "lower",
}
PARTITIONS = {"development", "held_out"}
COMPONENTS = frozenset({
    "prompt", "rule", "skill", "hook", "script", "memory", "tool-guidance", "subagent", "plugin",
})
MIN_RUNS = 3
DEFAULT_LESSONS = Path("evidence/harness-lessons.jsonl")
DIGEST_PATTERN = re.compile(r"(sha256:)?[0-9a-f]{64}")
LESSON_TEXT_KEYS = ("cue", "lesson", "evidence")


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def case_runs(case: dict[str, Any]) -> list[bool]:
    """Return the boolean runs of a case; a legacy single boolean is one run."""
    case_id = case.get("id")
    if "runs" in case and "outcome_passed" in case:
        raise ValueError(f"case {case_id} must use runs or outcome_passed, not both")
    if "runs" in case:
        runs = case["runs"]
        if not isinstance(runs, list) or not runs or any(type(run) is not bool for run in runs):
            raise ValueError(f"case {case_id} needs a non-empty list of boolean runs")
        return runs
    if type(case.get("outcome_passed")) is not bool:
        raise ValueError(f"case {case_id} needs boolean outcome_passed or runs")
    return [case["outcome_passed"]]


def case_outcome(case: dict[str, Any]) -> bool:
    """A case passes when a strict majority of its runs pass."""
    runs = case_runs(case)
    return sum(runs) * 2 > len(runs)


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
        case_runs(case)
        if type(case.get("safety_passed")) is not bool:
            raise ValueError(f"case {case_id} needs boolean safety_passed")
        for metric in ("tool_calls", "elapsed_ms"):
            if not _is_nonnegative_int(case.get(metric)):
                raise ValueError(f"case {case_id} needs non-negative integer {metric}")
    if partitions != PARTITIONS:
        raise ValueError("receipt must contain both development and held_out cases")
    return receipt


def validate_lesson(lesson: object) -> None:
    if not isinstance(lesson, dict):
        raise ValueError("candidate.lesson must be an object")
    for key in LESSON_TEXT_KEYS:
        value = lesson.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"candidate.lesson.{key} must be non-empty text")
    confidence = lesson.get("confidence")
    if type(confidence) not in (str, int, float) or (isinstance(confidence, str) and not confidence.strip()):
        raise ValueError("candidate.lesson.confidence must be text or a number")


def validate_change(candidate: dict[str, Any]) -> dict[str, Any]:
    """Require the one-component and diff facts of a candidate; missing facts are not checked."""
    change = candidate.get("candidate")
    if not isinstance(change, dict):
        raise ValueError("candidate.component not checked: candidate block missing")
    component = change.get("component")
    if component is None:
        raise ValueError("candidate.component not checked: component missing")
    names = component if isinstance(component, list) else [component]
    if not names or not all(isinstance(name, str) and name in COMPONENTS for name in names):
        raise ValueError(f"candidate.component must be one of {sorted(COMPONENTS)} or a list of them")
    digest = change.get("diff_sha256")
    if digest is None:
        raise ValueError("candidate.diff_sha256 not checked: missing")
    if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
        raise ValueError("candidate.diff_sha256 must be a sha256 hex digest")
    lesson = change.get("lesson")
    if lesson is not None:
        validate_lesson(lesson)
    return {"component": component, "diff_sha256": digest}


def metrics(receipt: dict[str, Any]) -> dict[str, float]:
    cases = receipt["cases"]
    count = len(cases)
    return {
        "outcome_pass_rate": sum(case_outcome(case) for case in cases) / count,
        "mean_tool_calls": sum(case["tool_calls"] for case in cases) / count,
        "mean_elapsed_ms": sum(case["elapsed_ms"] for case in cases) / count,
    }


def compare(baseline: object, candidate: object) -> dict[str, Any]:
    baseline = validate_receipt(baseline)
    candidate = validate_receipt(candidate)
    change = validate_change(candidate)
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
    names = change["component"] if isinstance(change["component"], list) else [change["component"]]
    distinct = sorted(set(names))
    if len(distinct) > 1:
        reasons.append("candidate changes more than one component: " + ", ".join(distinct))
    if not improved:
        reasons.append(f"objective {objective} did not strictly improve")
    if candidate_metrics["outcome_pass_rate"] < baseline_metrics["outcome_pass_rate"]:
        reasons.append("candidate reduced outcome pass rate")
    unsafe = [case_id for case_id, case in candidate_cases.items() if not case["safety_passed"]]
    if unsafe:
        reasons.append("candidate failed safety assertions: " + ", ".join(sorted(unsafe)))
    held_out_failures = [
        case_id for case_id, case in candidate_cases.items()
        if case["partition"] == "held_out" and not case_outcome(case)
    ]
    if held_out_failures:
        reasons.append("candidate failed held-out cases: " + ", ".join(sorted(held_out_failures)))

    if objective == "outcome_pass_rate":
        rests_on = [
            case_id for case_id in baseline_cases
            if case_outcome(baseline_cases[case_id]) != case_outcome(candidate_cases[case_id])
        ]
    else:
        rests_on = list(candidate_cases)
    thin = sorted(
        case_id for case_id in rests_on
        if min(len(case_runs(baseline_cases[case_id])), len(case_runs(candidate_cases[case_id])))
        < MIN_RUNS
    )
    confounded = improved and bool(thin)
    if confounded:
        reasons.append("improvement rests on cases with fewer than 3 runs: " + ", ".join(thin))

    decision = "ACCEPT" if not reasons else "REJECT"
    return {
        "schema": "harness-improvement-pilot-report/v1",
        "suite": baseline["suite"],
        "objective": candidate["objective"],
        "change": change,
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "decision": decision,
        "verdict": "CONFOUNDED" if confounded else decision,
        "reasons": reasons,
    }


def ledger_entry(report: dict[str, Any], candidate: dict[str, Any], *, today: str) -> dict[str, Any]:
    verdict = report["verdict"]
    lesson = candidate["candidate"].get("lesson")
    if verdict == "CONFOUNDED" or lesson is None:
        return {"date": today, "verdict": verdict, "entry": "NO_ENTRY"}
    return {
        "date": today,
        "verdict": verdict,
        "component": report["change"]["component"],
        "cue": lesson["cue"],
        "lesson": lesson["lesson"],
        "evidence": lesson["evidence"],
        "confidence": lesson["confidence"],
    }


def append_ledger(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
    parser.add_argument("--lessons", type=Path, default=DEFAULT_LESSONS,
                        help="append-only lesson ledger (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        candidate = load_json(args.candidate)
        report = compare(load_json(args.baseline), candidate)
        entry = ledger_entry(report, candidate, today=date.today().isoformat())
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        append_ledger(args.lessons, entry)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["decision"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
