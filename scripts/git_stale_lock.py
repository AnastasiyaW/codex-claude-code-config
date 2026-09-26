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
removed only if ALL hold:

1. the git dir is on a local disk (UNC / \\\\wsl$ / mapped network drive -> refuse:
   owners there are invisible to this machine's process table);
2. mtime is not in the future (clock skew makes the age meaningless);
3. age >= --min-age (default 600 s). git holds most locks for one operation;
   `git commit` holds index.lock while its editor is open, hence the owner test;
4. no possible owner is running: a process whose name suggests a git client
   (OWNER_NAME_HINTS) or whose name / start time cannot be read, started before
   the lock's mtime. A process that started after the lock existed could not
   have created it; mtime >= creation, so "started <= mtime" is conservative.

Removal is identity-checked against the classified file (mtime_ns, size, inode):
the lock is renamed to a tombstone, the tombstone is re-checked, and only then
deleted; a lock that appeared in between is put back. Afterwards the tool checks
the file is gone and `git status` exits 0. It never repairs a damaged index.

Exit codes (see rules/absence-of-signal.md):
  0  nothing stale, or every stale lock removed and verified
  1  a lock exists but removal is refused, or the post-check failed
  2  UNKNOWN: not a git repo, or processes could not be enumerated
  3  dry run found stale locks (nothing removed; re-run with --remove)

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
# magnitude of margin. Long holders (commit editor) are caught by the owner test.
DEFAULT_MIN_AGE = 600
# Filesystem mtime vs process create_time come from different clocks; allow skew.
CLOCK_SKEW = 2.0
# Name fragments of programs that may hold a git lock: the git CLI and git GUIs /
# libgit2 hosts (TortoiseGitProc, GitHub Desktop, GitKraken, SmartGit, lazygit ...
# all contain "git"), plus clients without "git" in the name.
# WSL / Docker hosts are included because a git inside them is invisible here; while
# they run, removal is refused (conservative).
OWNER_NAME_HINTS = ("git", "sourcetree", "devenv", "fork", "wsl", "vmmem", "docker")


def _git(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def git_dir(repo: Path) -> Path | None:
    out = _git(repo, "rev-parse", "--absolute-git-dir")
    return Path(out) if out else None


def git_dirs(repo: Path) -> list[Path]:
    """The repo's git dir plus, for a linked worktree, the shared common dir."""
    gdir = git_dir(repo)
    if gdir is None:
        return []
    dirs = [gdir]
    common = _git(repo, "rev-parse", "--git-common-dir")
    if common:
        cpath = Path(common) if Path(common).is_absolute() else (repo / common)
        cpath = cpath.resolve()
        if cpath != gdir.resolve():
            dirs.append(cpath)
    return dirs


def find_locks(gdir: Path) -> list[Path]:
    # index.lock, HEAD.lock, config.lock, packed-refs.lock, ... plus ref locks
    locks = [p for p in gdir.glob("*.lock") if p.is_file()]
    refs = gdir / "refs"
    if refs.is_dir():
        locks += [p for p in refs.rglob("*.lock") if p.is_file()]
    return sorted(locks)


def on_remote_fs(path: Path) -> bool:
    s = str(path)
    if s.startswith("\\\\") or s.startswith("//"):
        return True  # UNC, including \\wsl$ and \\wsl.localhost
    if os.name == "nt":
        import ctypes
        drive = os.path.splitdrive(s)[0]
        # 4 = DRIVE_REMOTE (mapped network share)
        return bool(drive) and ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4
    # simplification: POSIX network mounts are not detected; add a statfs check if
    # this ever runs on NFS/SMB-mounted repos on Linux/macOS
    return False


def live_git_processes() -> list[tuple[int, str, float]]:
    """(pid, name, create_time) of every process that could own a git lock.

    psutil puts None for a field it may not read (AccessDenied) instead of
    raising. Unreadable must not look like absent: such a process counts as a
    possible owner, with start time 0.0 = older than any lock.
    """
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "create_time"]):
        name = p.info.get("name")
        ct = p.info.get("create_time")
        if name is None or any(h in name.lower() for h in OWNER_NAME_HINTS):
            out.append((p.info["pid"], (name or "<unreadable>").lower(), float(ct) if ct else 0.0))
    return out


def _identity(st: os.stat_result) -> tuple[int, int, int]:
    return (st.st_mtime_ns, st.st_size, getattr(st, "st_ino", 0))


def classify_lock(lock: Path, procs, now: float, min_age: float) -> tuple[str, str]:
    """('STALE'|'YOUNG'|'OWNED'|'SKEWED'|'GONE', detail). Shared with the Stop hook."""
    try:
        mtime = lock.stat().st_mtime
    except FileNotFoundError:
        return "GONE", "lock no longer exists"
    age = now - mtime
    if age < -CLOCK_SKEW:
        return "SKEWED", f"mtime is {-age:.0f}s in the future (clock skew; age meaningless)"
    if age < min_age:
        return "YOUNG", f"age {age:.0f}s < {min_age:.0f}s (may be in use)"
    owners = [(pid, n) for pid, n, ct in procs if ct <= mtime + CLOCK_SKEW]
    if owners:
        return "OWNED", f"age {age:.0f}s but possible owners alive: {owners[:5]}"
    return "STALE", f"age {age:.0f}s, no possible owner older than it"


def remove_checked(lock: Path, snap: tuple[int, int, int]) -> str | None:
    """Delete `lock` only if it is still the file that was classified. Error text or None."""
    try:
        if _identity(lock.stat()) != snap:
            return "lock changed since it was checked"
    except FileNotFoundError:
        return "lock vanished before removal"
    tomb = lock.with_name(f"{lock.name}.stale-{os.getpid()}-{time.time_ns()}")
    try:
        os.rename(lock, tomb)  # atomic; the tombstone name no longer ends in .lock
    except OSError as exc:  # e.g. WinError 32: an invisible owner holds it open
        return f"lock held open, not removed ({exc!r})"
    if _identity(tomb.stat()) != snap:
        # a new lock was created between the check and the rename: give it back.
        # link+unlink, not rename: rename on POSIX would overwrite a lock created
        # in that instant; link fails instead.
        try:
            os.link(tomb, lock)
            tomb.unlink()
        except OSError as exc:
            return f"renamed a NEW lock and could not restore it ({exc!r}); tombstone: {tomb}"
        return "a new lock appeared between check and removal; restored"
    tomb.unlink()
    if tomb.exists():
        return f"tombstone still exists after unlink: {tomb}"
    return None


def run(repo: Path, remove: bool, min_age: float, procs_fn=live_git_processes) -> int:
    dirs = git_dirs(repo)
    if not dirs:
        print(f"UNKNOWN: {repo} is not a git repository")
        return 2
    locks = sorted({p for d in dirs for p in find_locks(d)})
    print(f"SCANNED: git_dirs={[str(d) for d in dirs]} locks={len(locks)}")
    if not locks:
        print("OK: no lock files")
        return 0
    remote = [str(d) for d in dirs if on_remote_fs(d)]
    if remote:
        print(f"REFUSE: git dir on a network/WSL filesystem {remote}; owners there are not visible here")
        return 1
    try:
        procs = procs_fn()
    except Exception as exc:  # cannot prove absence of an owner -> not green
        print(f"UNKNOWN: cannot enumerate processes: {exc!r}")
        return 2

    now = time.time()
    verdict = 0
    stale_seen = 0
    removed = []
    for lock in locks:
        try:
            snap = _identity(lock.stat())
        except FileNotFoundError:
            print(f"GONE: {lock}")
            continue
        state, detail = classify_lock(lock, procs, now, min_age)
        if state == "GONE":
            print(f"GONE: {lock}")
            continue
        if state != "STALE":
            print(f"REFUSE: {lock} {detail}")
            verdict = 1
            continue
        stale_seen += 1
        if not remove:
            print(f"STALE: {lock} {detail} (dry run; add --remove)")
            continue
        err = remove_checked(lock, snap)
        if err:
            print(f"FAIL: {lock}: {err}")
            verdict = 1
            continue
        removed.append(lock)
        print(f"REMOVED: {lock} ({detail}; identity-checked, verified absent)")

    if removed:
        st = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True)
        if st.returncode != 0:
            print(f"FAIL: git status exit {st.returncode} after removal: {st.stderr.strip()[:300]}")
            return 1
        print("VERIFIED: git status exit 0 after removal")
    if verdict == 0 and stale_seen and not remove:
        return 3
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

        def stale_lock():
            lock.write_bytes(b"")
            os.utime(lock, (old, old))

        lock.write_bytes(b"")  # fresh lock -> refuse, must survive
        if run(repo, True, 600, no_procs) != 1 or not lock.exists():
            failures.append("fresh lock was not refused")

        stale_lock()  # owner started before it -> refuse
        if run(repo, True, 600, lambda: [(1, "git.exe", old - 10)]) != 1 or not lock.exists():
            failures.append("lock with live older owner was not refused")

        # unreadable process (name/start None -> recorded as start 0.0) -> refuse
        if run(repo, True, 600, lambda: [(7, "<unreadable>", 0.0)]) != 1 or not lock.exists():
            failures.append("unreadable process was not treated as a possible owner")

        future = time.time() + 3600  # mtime in the future -> refuse
        os.utime(lock, (future, future))
        if run(repo, True, 600, no_procs) != 1 or not lock.exists():
            failures.append("future mtime was not refused")

        stale_lock()  # enumeration failure -> UNKNOWN, keep file
        def boom():
            raise RuntimeError("no access")
        if run(repo, True, 600, boom) != 2 or not lock.exists():
            failures.append("enumeration failure was not UNKNOWN")

        if run(repo, False, 600, no_procs) != 3 or not lock.exists():
            failures.append("dry run did not report stale (exit 3) or removed the lock")

        snap = _identity(lock.stat())  # file replaced after classification -> refuse
        lock.unlink()
        lock.write_bytes(b"new owner")
        if remove_checked(lock, snap) is None or not lock.exists():
            failures.append("a lock replaced after the check was removed")

        stale_lock()  # only a process started AFTER it -> not an owner -> remove
        if run(repo, True, 600, lambda: [(2, "git.exe", time.time())]) != 0 or lock.exists():
            failures.append("stale lock with no possible owner was not removed")
        if list((repo / ".git").glob("index.lock.stale-*")):
            failures.append("tombstone left behind")

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
