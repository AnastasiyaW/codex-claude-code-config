#!/usr/bin/env python3
"""Stop hook: clean up old auto-backup branches and stashes.

Runs on session end (Stop event). Looks at the current working directory
(and optionally git worktrees) for claude-backup-{ts} branches and
claude-pre-clean-{ts} stashes older than N days. Default retention: 14 days.

This hook creates no output unless something is cleaned. Silent in
non-git dirs.

Safe to run repeatedly - idempotent.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import log  # noqa: E402

RETENTION_DAYS = 14
RETENTION_SECONDS = RETENTION_DAYS * 86400

BACKUP_BRANCH_RE = re.compile(r"^\s*(?:\*\s+)?(claude-backup-(\d+))\s*$", re.MULTILINE)
BACKUP_STASH_RE = re.compile(r"^(stash@\{\d+\}):.*claude-pre-clean-(\d+)", re.MULTILINE)


def in_git_repo(cwd: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return False


def list_local_branches(cwd: str) -> list[tuple[str, int]]:
    """Return [(name, unix_ts), ...] for claude-backup-* branches."""
    try:
        r = subprocess.run(
            ["git", "branch", "--list", "claude-backup-*"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if r.returncode != 0:
            return []
        out: list[tuple[str, int]] = []
        for m in BACKUP_BRANCH_RE.finditer(r.stdout):
            name, ts_str = m.group(1), m.group(2)
            try:
                out.append((name, int(ts_str)))
            except ValueError:
                continue
        return out
    except (subprocess.SubprocessError, OSError):
        return []


def stash_index(ref: str) -> int:
    """stash@{12} -> 12. Refs must be dropped highest index first, and as strings
    stash@{9} sorts above stash@{12}: dropping {9} first shifts {12} to {11}, so the
    next drop hits a different (possibly user) stash."""
    return int(ref[ref.index("{") + 1:ref.index("}")])


def list_stashes(cwd: str) -> list[tuple[str, int]]:
    """Return [(ref, unix_ts), ...] for claude-pre-clean-* stashes."""
    try:
        r = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if r.returncode != 0:
            return []
        out: list[tuple[str, int]] = []
        for m in BACKUP_STASH_RE.finditer(r.stdout):
            ref, ts_str = m.group(1), m.group(2)
            try:
                out.append((ref, int(ts_str)))
            except ValueError:
                continue
        return out
    except (subprocess.SubprocessError, OSError):
        return []


def delete_branch(cwd: str, name: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "branch", "-D", name],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def drop_stash(cwd: str, ref: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "stash", "drop", ref],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def main() -> None:
    # Stop event payload - read but we only need cwd
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        event = {}

    cwd = event.get("cwd") or os.getcwd()
    if not in_git_repo(cwd):
        sys.exit(0)

    now = int(time.time())
    deleted_branches: list[str] = []
    dropped_stashes: list[str] = []

    for name, ts in list_local_branches(cwd):
        if now - ts > RETENTION_SECONDS:
            if delete_branch(cwd, name):
                deleted_branches.append(name)
                log("INFO", "cleanup_backup", "branch_deleted", name, cwd)

    # Stashes need descending ref order: dropping stash@{0} shifts stash@{1} to {0}.
    for ref, ts in sorted(list_stashes(cwd), key=lambda x: stash_index(x[0]), reverse=True):
        if now - ts > RETENTION_SECONDS:
            if drop_stash(cwd, ref):
                dropped_stashes.append(ref)
                log("INFO", "cleanup_backup", "stash_dropped", ref, cwd)

    if deleted_branches or dropped_stashes:
        msg = []
        if deleted_branches:
            msg.append(f"{len(deleted_branches)} old claude-backup branch(es)")
        if dropped_stashes:
            msg.append(f"{len(dropped_stashes)} old claude-pre-clean stash(es)")
        sys.stderr.write(
            "[cleanup-backup] Retention: removed " + ", ".join(msg)
            + f" (older than {RETENTION_DAYS} days)\n"
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
