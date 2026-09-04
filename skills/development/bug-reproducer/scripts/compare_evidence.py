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
    full_suite: str,
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
    if full_suite == "failed":
        return "FIX_REGRESSION", "The targeted reproducer passes, but broader relevant checks fail."
    if full_suite == "not-run":
        return "FIX_UNVERIFIED", "The targeted reproducer passes, but broader checks were not run."
    return "FIX_PROVEN", "The same reproducer changed from failing to passing and broader checks passed."


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
    parser.add_argument(
        "--full-suite",
        choices=["passed", "failed", "not-run"],
        default="not-run",
    )
    args = parser.parse_args()

    before = load(args.before)
    after = load(args.after)
    status, reason = classify(before, after, args.reproduction, args.full_suite)
    result = {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "reproduction": args.reproduction,
        "full_suite": args.full_suite,
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
