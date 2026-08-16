#!/usr/bin/env python3
"""Run the complete guard regression corpus against one explicit hook tree.

The old receipt claimed thirteen suites and 190 checks while listing twelve
commands whose own totals summed to 178.  This runner owns the arithmetic and
passes ``HOOKS_DIR`` to every suite, so a worktree test cannot silently import
the installed copy instead of the source under review.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


HOOKS = Path(os.environ.get("HOOKS_DIR", Path(__file__).resolve().parents[1])).resolve()
TESTS = [
    "test_guard_evasions.py",
    "test_guard_evasions_round2.py",
    "test_guard_evasions_round3.py",
    "test_guard_evasions_round4.py",
    "test_guard_evasions_round5.py",
    "test_guard_evasions_round6.py",
    "test_guard_evasions_round7.py",
    "test_safety_common_scope.py",
    "test_transfer_guard_scope.py",
    "test_delivery_guard_scope.py",
    "test_powershell_coverage.py",
    "smoke_hooks_live.py",
]
TOTAL = re.compile(r"\ball\s+(\d+)\b.*\bcorrect\b", re.IGNORECASE)


def main() -> int:
    env = os.environ.copy()
    env["HOOKS_DIR"] = str(HOOKS)
    counts: list[int] = []
    failures: list[str] = []
    for name in TESTS:
        script = Path(__file__).with_name(name)
        result = subprocess.run(
            [sys.executable, "-B", str(script)],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env=env,
        )
        found = TOTAL.findall(result.stdout)
        if result.returncode or not found:
            failures.append(f"{name}: rc={result.returncode}\n{result.stdout}{result.stderr}")
            continue
        count = int(found[-1])
        counts.append(count)
        print(f"  ok {name}: {count} checks")
    if failures:
        print("guard regression corpus FAILED:")
        for failure in failures:
            print(failure.rstrip())
        return 1
    print(f"all {sum(counts)} checks correct across {len(TESTS)} suites (hooks: {HOOKS})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
