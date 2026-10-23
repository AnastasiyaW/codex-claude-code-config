#!/usr/bin/env python3
"""Stop zombie helper processes that PROVABLY have no parent left (owner 2026-10-15).

Owner: «поставь в хуке удалять зомби без моего разрешения и без родителя».

"Zombie" here is deliberately narrower than "orphan". On Windows every app started
before explorer.exe restarted is an orphan (Telegram, Firefox, Discord ...), and
killing those loses the owner's work. A process is a zombie only if ALL hold:

1. its parent is gone: the parent PID is not running, or the PID was reused by a
   process created after the child (then the real parent is gone too);
2. its image is a short-lived CLI helper from ZOMBIE_IMAGES - text filters, pagers,
   sleep, and two narrow cases: a Git-bash shell started by a Claude Code
   tool call (its command line sources .claude/shell-snapshots/) and a
   `tailscale <query>` CLI call (never tailscaled / tailscale-ipn);
3. it is older than MIN_AGE: an orphaned grep/tail that lives that long is stuck;
4. it is not this process or one of its ancestors;
5. it is not busy: no live child, and no live non-helper sibling started by the same
   parent within PIPE_WINDOW (a pipe partner such as `nohup train.py | grep`).
   A pipeline made only of helpers (`tail -f log | grep ERR >> alerts`) is reaped: its
   parent shell is gone, and such a watcher is not a job.

nohup, python, node, ssh, rclone, conhost and every daemon are never zombies: an
orphaned job or tunnel may be work in progress.

Stopping is `taskkill /PID <pid> /F` without /T (children survive), after the
identity (pid + create_time) is re-read, and is followed by a check that the
process is gone. human-confirmation-guard imports is_zombie() and lets a bare
`taskkill //PID ...` through without the owner's word only when every PID passes.

Exit codes (rules/absence-of-signal.md):
  0  no zombies, or every zombie stopped and verified gone
  1  a zombie could not be stopped, or is still running afterwards
  2  UNKNOWN: processes could not be enumerated (psutil missing / error)
  3  dry run found zombies (nothing stopped; re-run with --reap)

Usage:
  python orphan_reaper.py            # list zombies
  python orphan_reaper.py --reap     # stop them and verify
  python orphan_reaper.py --self-test
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

# 10 min: these helpers live for one pipeline (seconds); an orphan alive 600 s is stuck.
MIN_AGE = 600
# tee/xargs/timeout/find are left out: they wrap or feed a live job (review 2026-10-15).
ZOMBIE_IMAGES = frozenset({
    "grep", "egrep", "fgrep", "rg", "tail", "head", "sed", "awk", "gawk", "cat", "less", "more",
    "wc", "sort", "uniq", "cut", "tr", "sleep", "jq",
})
# A pipeline is started by one shell within milliseconds; 30 s covers a heavily loaded PC (review 2026-10-15).
PIPE_WINDOW = 30.0
SHELL_IMAGES = frozenset({"bash", "sh", "dash"})
TAILSCALE_QUERIES = frozenset({"status", "ping", "netcheck", "ip", "whois", "version"})
SNAPSHOT_MARK = re.compile(r"[\\/]\.claude[\\/]shell-snapshots[\\/]", re.IGNORECASE)


def _stem(name: str) -> str:
    n = (name or "").lower()
    return n[:-4] if n.endswith(".exe") else n


def classify(name: str, cmdline: list[str], age: float, parent_alive: bool, busy: bool = False) -> str | None:
    """Reason string if the process is a zombie, else None. Pure: unit-tested below.

    busy: it has a live child, or a live pipe partner that is not itself a helper - then the
    pipeline still carries a job (e.g. `nohup train.py | grep` from a closed shell)."""
    if parent_alive or busy or age < MIN_AGE:
        return None
    stem = _stem(name)
    if stem in ZOMBIE_IMAGES:
        return f"orphan {stem}, {int(age)} s"
    joined = " ".join(cmdline or [])
    if stem in SHELL_IMAGES and SNAPSHOT_MARK.search(joined):
        return f"orphan Claude tool shell, {int(age)} s"
    if stem == "tailscale" and len(cmdline) >= 2 and cmdline[1].lower() in TAILSCALE_QUERIES:
        return f"orphan tailscale {cmdline[1].lower()}, {int(age)} s"
    return None


def _ancestors(psutil) -> set[int]:
    out, p = set(), psutil.Process(os.getpid())
    while p is not None:
        out.add(p.pid)
        try:
            p = p.parent()
        except psutil.Error:
            break
    return out


def inspect(pid: int, psutil, now: float | None = None) -> tuple[str | None, float | None]:
    """(reason, create_time) for a live pid; reason None when it is not a zombie."""
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            name, ctime, ppid = p.name(), p.create_time(), p.ppid()
            try:
                cmd = p.cmdline()
            except psutil.Error:
                cmd = []
    except psutil.Error:
        return None, None
    if pid <= 4 or ppid <= 4:
        return None, ctime   # System / Idle parents are not "gone"
    try:
        parent_alive = psutil.Process(ppid).create_time() <= ctime
    except psutil.NoSuchProcess:
        parent_alive = False
    except psutil.Error:
        parent_alive = True   # cannot read the parent -> do not claim it is gone
    age = (now or time.time()) - ctime
    reason = classify(name, cmd, age, parent_alive)
    if reason and _busy(pid, ppid, ctime, psutil):
        reason = None
    return reason, ctime


def _busy(pid: int, ppid: int, ctime: float, psutil) -> bool:
    """Live child, or live non-helper sibling from the same (dead) parent started within PIPE_WINDOW."""
    for q in psutil.process_iter(["pid", "ppid", "name", "create_time"]):
        info = q.info
        if info["pid"] == pid:
            continue
        if info["ppid"] is None or info["create_time"] is None:
            return True   # unreadable process might be the child or pipe partner: fail closed
        if info["ppid"] == pid and info["create_time"] >= ctime:
            return True
        if (info["ppid"] == ppid and abs(info["create_time"] - ctime) <= PIPE_WINDOW
                and _stem(info["name"]) not in ZOMBIE_IMAGES):
            return True
    return False


def is_zombie(pid: int) -> str | None:
    """Reason if `pid` is a zombie right now; imported by human-confirmation-guard."""
    import psutil
    if pid in _ancestors(psutil):
        return None
    return inspect(pid, psutil)[0]


def find_zombies(psutil) -> list[tuple[int, float, str]]:
    mine, now, out = _ancestors(psutil), time.time(), []
    for pid in psutil.pids():
        if pid in mine:
            continue
        reason, ctime = inspect(pid, psutil, now)
        if reason:
            out.append((pid, ctime, reason))
    return out


def reap(zombies, psutil) -> int:
    rc = 0
    for pid, ctime, reason in zombies:
        try:
            if psutil.Process(pid).create_time() != ctime:
                print(f"skip {pid}: pid reused")
                continue
        except psutil.NoSuchProcess:
            print(f"gone {pid}: exited by itself")
            continue
        if os.name == "nt":
            # runs from a pythonw scheduled task: without CREATE_NO_WINDOW taskkill opens a console window
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        try:
            psutil.Process(pid).wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        except psutil.Error:
            pass
        try:
            still = psutil.Process(pid).create_time() == ctime
        except psutil.NoSuchProcess:
            still = False
        print(f"{'FAILED' if still else 'stopped'} {pid}: {reason}")
        rc = rc or (1 if still else 0)
    return rc


def self_test() -> int:
    old = MIN_AGE + 1
    snap = ["bash", "-c", "source /repo/.claude/shell-snapshots/snapshot-bash-1.sh && grep x"]
    must_kill = [
        ("grep.exe", ["grep", "-E", "x"], old, False),
        ("tail.exe", ["tail", "-f", "run.log"], old, False),
        ("bash.exe", snap, old, False),
        ("tailscale.exe", ["tailscale", "status"], old, False),
    ]
    must_keep = [
        ("grep.exe", ["grep"], MIN_AGE - 1, False),          # young
        ("grep.exe", ["grep"], old, True),                   # parent alive
        ("firefox.exe", ["firefox"], old, False),            # user app orphan
        ("Telegram.exe", ["Telegram"], old, False),
        ("nohup.exe", ["nohup", "python", "job.py"], old, False),
        ("python.exe", ["python", "job.py"], old, False),
        ("ssh.exe", ["ssh", "-N", "-L", "1:h:1"], old, False),
        ("rclone.exe", ["rclone", "mount"], old, False),
        ("bash.exe", ["bash", "-c", "./train.sh"], old, False),   # shell without snapshot
        ("tailscaled.exe", ["tailscaled"], old, False),
        ("tailscale.exe", ["tailscale", "up"], old, False),
        ("tailscale-ipn.exe", ["tailscale-ipn"], old, False),
        ("conhost.exe", ["conhost", "0x4"], old, False),
        ("tee.exe", ["tee", "log"], old, False),                  # feeds a live job's log
        ("timeout.exe", ["timeout", "900", "python", "x"], old, False),
        ("grep.exe", ["grep", "x"], old, False, True),            # pipe partner still alive
        ("bash.exe", snap, old, False, True),                     # background job still running
    ]
    bad = [c for c in must_kill if not classify(*c)] + [c for c in must_keep if classify(*c)]
    for c in bad:
        print("SELF-TEST FAIL:", c)
    print("self-test", "FAIL" if bad else "PASS", f"({len(must_kill)} kill, {len(must_keep)} keep)")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reap", action="store_true", help="stop the zombies and verify")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--log", help="append output to this file (scheduled background runs)")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.log:
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _run(a.reap)
        if rc != 0 or "stopped" in buf.getvalue() or "FAILED" in buf.getvalue():
            with open(a.log, "a", encoding="utf-8") as fh:
                for line in buf.getvalue().splitlines():
                    fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} rc={rc} {line}\n")
        return rc
    return _run(a.reap)


def _run(do_reap: bool) -> int:
    try:
        import psutil
        zombies = find_zombies(psutil)
    except Exception as e:  # noqa: BLE001 - any enumeration failure is UNKNOWN, not "clean"
        print(f"UNKNOWN: cannot enumerate processes: {e}")
        return 2
    for pid, _, reason in zombies:
        print(f"zombie {pid}: {reason}")
    if not zombies:
        print("no zombies")
        return 0
    return reap(zombies, psutil) if do_reap else 3


if __name__ == "__main__":
    sys.exit(main())
