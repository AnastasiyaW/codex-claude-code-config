#!/usr/bin/env python3
"""Remove a git lock file only when it is PROVEN to have no live owner.

Why this exists
---------------
A git command killed mid-operation (session cut, hook timeout, app closing its
background git) leaves `.git/index.lock` behind, and every later git write fails
with "Unable to create index.lock: File exists". Agents could not clear it:
`rm .git/index.lock` is correctly blocked by human-confirmation-guard, because
from the command text alone a stale lock and a lock held right now by a live git
look the same - deleting the second corrupts the index.

This tool supplies the missing proof instead of a whitelist entry. A lock is
removed only if BOTH hold:

1. age >= --min-age (default 600 s). git holds its locks for the duration of one
   operation, i.e. seconds.
2. no running git-family process started before the lock's mtime. A process that
   started after the lock existed cannot own it: it would have failed to create
   it. mtime >= creation time, so "started <= mtime" is the conservative side.

After removal it re-checks that the file is gone and that `git status` exits 0
(index readable). It never repairs a damaged index.

Exit codes (three states, see rules/absence-of-signal.md):
  0  nothing stale, or every stale lock removed and verified (dry-run: report only)
  1  a lock exists but removal is refused (too young / possible owner) or the
     post-check failed
  2  UNKNOWN: not a git repo, or processes could not be enumerated

Usage:
  python git_stale_lock.py [REPO] [--remove] [--min-age SECONDS]
  python git_stale_lock.py --self-test
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 10 min: git holds a lock for one operation (seconds); 600 s leaves two orders of
# magnitude of margin, also for libgit2-based GUIs that do not appear as git.exe.
DEFAULT_MIN_AGE = 600
# Filesystem mtime vs process create_time come from different clocks; allow skew.
CLOCK_SKEW = 2.0


def git_dir(repo: Path) -> Path | None:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def find_locks(gdir: Path) -> list[Path]:
    # index.lock, HEAD.lock, config.lock, packed-refs.lock, ... plus ref locks
    locks = [p for p in gdir.glob("*.lock") if p.is_file()]
    refs = gdir / "refs"
    if refs.is_dir():
        locks += [p for p in refs.rglob("*.lock") if p.is_file()]
    return sorted(locks)


def live_git_processes() -> list[tuple[int, str, float]]:
    """(pid, name, create_time) of every running git-family process. Raises on failure."""
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "create_time"]):
        name = (p.info.get("name") or "").lower()
        if name.startswith("git") and p.info.get("create_time"):
            out.append((p.info["pid"], name, float(p.info["create_time"])))
    return out


def run(repo: Path, remove: bool, min_age: float, procs_fn=live_git_processes) -> int:
    gdir = git_dir(repo)
    if gdir is None:
        print(f"UNKNOWN: {repo} is not a git repository")
        return 2
    locks = find_locks(gdir)
    print(f"SCANNED: git_dir={gdir} locks={len(locks)}")
    if not locks:
        print("OK: no lock files")
        return 0
    try:
        procs = procs_fn()
    except Exception as exc:  # cannot prove absence of an owner -> not green
        print(f"UNKNOWN: cannot enumerate processes: {exc!r}")
        return 2

    now = time.time()
    verdict = 0
    removed = []
    for lock in locks:
        mtime = lock.stat().st_mtime
        age = now - mtime
        owners = [(pid, n) for pid, n, ct in procs if ct <= mtime + CLOCK_SKEW]
        if age < min_age:
            print(f"REFUSE: {lock} age {age:.0f}s < {min_age:.0f}s (may be in use)")
            verdict = 1
            continue
        if owners:
            print(f"REFUSE: {lock} age {age:.0f}s but possible owners alive: {owners}")
            verdict = 1
            continue
        if not remove:
            print(f"STALE: {lock} age {age:.0f}s, no git process older than it (dry run; add --remove)")
            continue
        lock.unlink()
        if lock.exists():
            print(f"FAIL: {lock} still exists after unlink")
            verdict = 1
            continue
        removed.append(lock)
        print(f"REMOVED: {lock} (age {age:.0f}s, verified absent)")

    if removed:
        st = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True)
        if st.returncode != 0:
            print(f"FAIL: git status exit {st.returncode} after removal: {st.stderr.strip()[:300]}")
            return 1
        print("VERIFIED: git status exit 0 after removal")
    return verdict


def self_test() -> int:
    """Negative controls: every red case must come back red, the green one green."""
    failures = []
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        lock = repo / ".git" / "index.lock"
        old = time.time() - 3600
        no_procs = lambda: []  # noqa: E731

        lock.write_bytes(b"")  # fresh lock -> refuse, must survive
        if run(repo, True, 600, no_procs) != 1 or not lock.exists():
            failures.append("fresh lock was not refused")

        os.utime(lock, (old, old))  # old lock, owner started before it -> refuse
        if run(repo, True, 600, lambda: [(1, "git.exe", old - 10)]) != 1 or not lock.exists():
            failures.append("lock with live older owner was not refused")

        # old lock, only a process started AFTER it -> not an owner -> remove
        if run(repo, True, 600, lambda: [(2, "git.exe", time.time())]) != 0 or lock.exists():
            failures.append("stale lock with no possible owner was not removed")

        lock.write_bytes(b"")  # process enumeration failure -> UNKNOWN, keep file
        os.utime(lock, (old, old))

        def boom():
            raise RuntimeError("no access")
        if run(repo, True, 600, boom) != 2 or not lock.exists():
            failures.append("enumeration failure was not UNKNOWN")

        if run(repo, False, 600, no_procs) != 0 or not lock.exists():
            failures.append("dry run removed the lock or failed")

        if run(Path(td), True, 600, no_procs) != 2:
            failures.append("non-repo was not UNKNOWN")

    for f in failures:
        print(f"SELF-TEST FAIL: {f}")
    print("SELF-TEST", "PASS" if not failures else "FAIL")
    return 0 if not failures else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--min-age", type=float, default=DEFAULT_MIN_AGE)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    return run(Path(a.repo).resolve(), a.remove, a.min_age)


if __name__ == "__main__":
    sys.exit(main())
