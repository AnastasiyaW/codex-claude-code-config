#!/usr/bin/env python3
"""Stop hook: require Git source-of-truth setup for adopted long-run projects.

The gate deliberately checks only durable repository setup, not a clean working
tree or a pushed branch. A global hook cannot safely infer which dirty files
belong to the current task, so it must never pressure an agent to commit
unrelated work. The project-level workflow still requires explicit review,
commit, push, and verification before a release or handoff.

Scope: a project opts in by creating ``feature_list.json`` in its root or
``.claude/feature_list.json``. Scratch folders remain silent.

Bypass: ``CLAUDE_SKIP_GIT_SOURCE_GATE=1`` or ``.claude/.skip-git-source-gate``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from safety_common import stop_budget_consume, stop_budget_exhausted  # noqa: E402
except ImportError:  # fail-open: keep the original one-shot behaviour
    stop_budget_consume = stop_budget_exhausted = None  # type: ignore[assignment]

# Gate name for the shared Stop-hook rejection budget (safety_common).
BUDGET_NAME = "git-source"

TIMEOUT_SEC = 5


def is_long_run(cwd: Path) -> bool:
    return (cwd / "feature_list.json").is_file() or (cwd / ".claude" / "feature_list.json").is_file()


def git(cwd: Path, *args: str) -> tuple[int | None, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return result.returncode, result.stdout.strip()


def evaluate(cwd: Path) -> str | None:
    """Return a block reason for a missing source-of-truth prerequisite."""
    if not is_long_run(cwd):
        return None

    inside_code, inside = git(cwd, "rev-parse", "--is-inside-work-tree")
    if inside_code != 0 or inside.lower() != "true":
        return (
            "This is a long-run project (feature_list.json) but it is not inside a Git repository. "
            "Create the repository and its .gitignore before ending: `git init -b main`, then commit the "
            "durable code and documentation."
        )

    origin_code, origin = git(cwd, "remote", "get-url", "origin")
    if origin_code != 0 or not origin:
        return (
            "This long-run Git project has no `origin` remote. Create a private remote by default, push the "
            "initial commit, and verify its visibility before ending."
        )
    return None


def main() -> int:
    try:
        raw = sys.stdin.read().lstrip("\ufeff").strip()
        event = json.loads(raw) if raw else {}
    except (OSError, json.JSONDecodeError):
        return 0
    # Anti-loop with a budget, not a one-shot surrender (safety_common).
    if event.get("stop_hook_active"):
        if stop_budget_exhausted is None or stop_budget_exhausted(BUDGET_NAME):
            return 0
    if os.environ.get("CLAUDE_SKIP_GIT_SOURCE_GATE"):
        return 0

    cwd = Path.cwd()
    if (cwd / ".claude" / ".skip-git-source-gate").exists():
        return 0

    reason = evaluate(cwd)
    if reason:
        if stop_budget_consume is not None:
            stop_budget_consume(BUDGET_NAME, cwd)
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
