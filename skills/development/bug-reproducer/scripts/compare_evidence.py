#!/usr/bin/env python3
"""Classify red-to-green evidence captured by Bug Reproducer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object in {path}")
    for field in ("command", "exit_code", "timed_out", "stdout", "stderr"):
        if field not in data:
            raise ValueError(f"Missing {field} in {path}")
    return data


def classify(
    before: dict[str, Any],
    after: dict[str, Any],
    reproduction: str,
    relevant_evidence: dict[str, Any] | None,
    targeted_scope_sufficient: bool,
    scope_rationale: str | None,
) -> tuple[str, str]:
    if before.get("command") != after.get("command"):
        return "INCONCLUSIVE", "Before and after did not run the exact same targeted command."
    if before.get("timed_out"):
        return "INCONCLUSIVE", "The original run timed out without a confirmed causal signal."
    if before.get("exit_code") == 0:
        return "NOT_REPRODUCED", "The proposed reproducer passed before any production fix."
    if reproduction != "confirmed":
        return "INCONCLUSIVE", "The failing run was not confirmed to match the reported bug."
    if after.get("timed_out") or after.get("exit_code") != 0:
        return "STILL_FAILING", "The same targeted reproducer still fails after the attempted fix."
    if relevant_evidence is not None:
        if duplicates_targeted_reproducer(before, after, relevant_evidence):
            return "FIX_UNVERIFIED", "The purported relevant check duplicates the targeted reproducer; record targeted-only scope explicitly instead."
        if relevant_evidence.get("timed_out") or relevant_evidence.get("exit_code") != 0:
            return "FIX_REGRESSION", "The targeted reproducer passes, but the captured relevant check fails or times out."
        return "FIX_PROVEN", "The same reproducer changed from failing to passing and the captured proportionate relevant check passed."
    if targeted_scope_sufficient:
        return "FIX_PROVEN", "The same reproducer changed from failing to passing; the declared targeted-only scope is the proportionate check."
    return "FIX_UNVERIFIED", "The targeted reproducer passes, but no captured proportionate relevant check or targeted-only scope rationale was supplied."


def duplicates_targeted_reproducer(
    before: dict[str, Any], after: dict[str, Any], relevant_evidence: dict[str, Any]
) -> bool:
    return (
        relevant_evidence == before
        or relevant_evidence == after
        or relevant_evidence.get("command") == after.get("command")
    )


def relevant_check_status(evidence: dict[str, Any] | None) -> str:
    if evidence is None:
        return "not-run"
    if evidence.get("timed_out") or evidence.get("exit_code") != 0:
        return "failed"
    return "passed"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--reproduction",
        choices=["confirmed", "unconfirmed"],
        default="unconfirmed",
    )
    relevant_group = parser.add_mutually_exclusive_group()
    relevant_group.add_argument(
        "--relevant-evidence",
        type=Path,
        help="Evidence JSON captured from the proportionate relevant check.",
    )
    relevant_group.add_argument(
        "--targeted-scope-sufficient",
        action="store_true",
        help="Declare that the exact targeted reproducer is the only proportionate relevant check.",
    )
    parser.add_argument(
        "--scope-rationale",
        help="Why targeted-only scope is sufficient; required with --targeted-scope-sufficient.",
    )
    args = parser.parse_args()
    if args.targeted_scope_sufficient and not args.scope_rationale:
        parser.error("--targeted-scope-sufficient requires --scope-rationale")
    if args.scope_rationale and not args.targeted_scope_sufficient:
        parser.error("--scope-rationale requires --targeted-scope-sufficient")

    before = load(args.before)
    after = load(args.after)
    relevant_evidence = load(args.relevant_evidence) if args.relevant_evidence else None
    relevant_check = relevant_check_status(relevant_evidence)
    if relevant_evidence and duplicates_targeted_reproducer(before, after, relevant_evidence):
        relevant_check = "duplicate-targeted"
    if args.targeted_scope_sufficient:
        relevant_check = "targeted-only"
    status, reason = classify(
        before,
        after,
        args.reproduction,
        relevant_evidence,
        args.targeted_scope_sufficient,
        args.scope_rationale,
    )
    result = {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "reproduction": args.reproduction,
        "relevant_check": relevant_check,
        "relevant_scope": "targeted-only" if args.targeted_scope_sufficient else "additional" if relevant_evidence else "not-recorded",
        "relevant_evidence": str(args.relevant_evidence) if args.relevant_evidence else None,
        "scope_rationale": args.scope_rationale,
        "same_command": before.get("command") == after.get("command"),
        "before": before,
        "after": after,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{status}: exit {before.get('exit_code')} -> {after.get('exit_code')} "
        f"({reason})"
    )


if __name__ == "__main__":
    main()
