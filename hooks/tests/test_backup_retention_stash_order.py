# -*- coding: utf-8 -*-
"""backup-retention-cleanup drops only its own old stashes, whatever their indexes.

Refs must be dropped highest index first. Sorted as strings, stash@{9} comes before
stash@{12}: dropping {9} shifts {12} to {11}, and the next `git stash drop stash@{12}`
removes the stash that was at {13} — a user's stash. Runs the hook as the harness does
(Stop event on stdin) against a throwaway repo, with HOME pointed at a temp dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOOKS = Path(os.environ.get("HOOKS_DIR", Path(__file__).resolve().parents[1])).resolve()
HOOK = HOOKS / "backup-retention-cleanup.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def push_stash(repo: Path, message: str, n: int) -> None:
    (repo / "f.txt").write_text(f"change {n}\n", encoding="utf-8")
    git(repo, "stash", "push", "-m", message)


def main() -> int:
    old = int(time.time()) - 30 * 86400
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "t")
        (repo / "f.txt").write_text("base\n", encoding="utf-8")
        git(repo, "add", "f.txt")
        git(repo, "commit", "-qm", "base")
        # oldest first; after all pushes: user-oldest {13}, backup {12}, backup {9}
        layout = ["user-oldest", f"claude-pre-clean-{old}", "user-a", "user-b", f"claude-pre-clean-{old + 1}"]
        layout += [f"user-{i}" for i in range(9)]
        for n, message in enumerate(layout):
            push_stash(repo, message, n)
        listing = git(repo, "stash", "list")
        assert "stash@{12}:" in listing and "stash@{9}:" in listing, listing

        env = {**os.environ, "HOME": str(Path(td) / "home")}
        subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"cwd": str(repo)}),
                       capture_output=True, text=True, env=env, timeout=60)

        after = git(repo, "stash", "list")
        user = [m for m in layout if m.startswith("user-")]
        missing = [m for m in user if f": {m}" not in after and f"On master: {m}" not in after and m not in after]
        assert not missing, f"user stashes dropped: {missing}\n{after}"
        assert "claude-pre-clean-" not in after, f"old backup stashes kept:\n{after}"
    print("test_backup_retention_stash_order: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
