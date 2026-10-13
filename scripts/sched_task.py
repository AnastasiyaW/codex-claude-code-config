#!/usr/bin/env python3
"""Windows scheduled task template that is proven to run: register, run once, verify.

Owner request 2026-10-13: "при создании задач по времени нужен шаблон, который можно
переиспользовать и который реально работает".

Why a template, not hand-written `schtasks /Create` (each line is a failure seen on these machines):
  * Task Scheduler "Last Result" is ambiguous (267009 = still running, 1 = our own
    "findings" code, 0 = maybe nothing ran) -> every run goes through `run`, which writes
    start/end/rc/duration/output tail to ~/.claude/state/sched/<name>.jsonl. That log, not
    Task Scheduler, is the proof.
  * `python` through the WindowsApps alias leaked one Appinfo handle per launch (146k in
    a day, 2026-10-11) -> executables are resolved to absolute paths, aliases are refused.
  * Console windows popped up on a shared workstation -> the task runs pythonw and every
    child gets CREATE_NO_WINDOW.
  * Overlapping runs and runs that never end -> MultipleInstancesPolicy=IgnoreNew, plus
    our own time limit that kills the whole child tree (Task Scheduler's limit kills only
    the top process).
  * Laptop/battery and missed-start defaults silently skip runs -> battery checks off,
    StartWhenAvailable on.

Usage:
  python sched_task.py create --name NAME (--every-min N | --daily HH:MM | --at-logon)
                              [--limit-min M] [--ok-codes 0,1] [--workdir DIR] [--logon interactive|s4u] -- EXE [ARGS...]
  python sched_task.py verify --name NAME [--wait-s 300]   # runs it now, checks the log
  python sched_task.py status --name NAME                  # last runs from the log
  python sched_task.py run --name NAME --limit-min M [--workdir DIR] -- EXE [ARGS...]  # what the task executes

Exit codes: 0 ok, 1 failed (task ran and failed, or registration refused), 2 not verified
(no fresh log record within the wait: it did not run, or is still running).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

LOG_DIR = Path.home() / ".claude" / "state" / "sched"
NO_WINDOW = 0x08000000
TAIL = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_exe(exe: str) -> str:
    """Absolute path to EXE; refuses WindowsApps app-execution aliases."""
    path = exe if os.path.isabs(exe) else shutil.which(exe)
    if not path or not os.path.exists(path):
        raise SystemExit(f"executable not found: {exe}")
    if "\\windowsapps\\" in path.lower().replace("/", "\\"):
        raise SystemExit(f"refusing WindowsApps alias {path}: it leaks Appinfo handles; pass the real path")
    return str(Path(path).resolve())


def _pythonw() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def _log(name: str, rec: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / f"{name}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _records(name: str) -> list[dict]:
    f = LOG_DIR / f"{name}.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


def cmd_run(a: argparse.Namespace) -> int:
    """Executed by the task: run the command hidden, enforce the limit, log the outcome."""
    run_id = f"{int(time.time())}-{os.getpid()}"
    t0 = time.time()
    _log(a.name, {"event": "start", "run_id": run_id, "ts": _now(), "cmd": a.command})
    with tempfile.TemporaryFile() as out:
        try:
            p = subprocess.Popen(a.command, cwd=a.workdir or None, stdin=subprocess.DEVNULL, stdout=out,
                                 stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        except OSError as e:
            _log(a.name, {"event": "end", "run_id": run_id, "ts": _now(), "rc": None, "status": "LAUNCH_FAILED",
                          "error": str(e), "seconds": 0})
            return 2
        try:
            rc = p.wait(timeout=a.limit_min * 60)
            status = "OK" if rc in a.ok_codes else "FAILED"
        except subprocess.TimeoutExpired:
            _kill_tree(p.pid)
            rc, status = None, "TIMED_OUT"
        out.seek(0, 2)
        out.seek(max(0, out.tell() - TAIL))
        tail = out.read().decode("utf-8", "replace")
    _log(a.name, {"event": "end", "run_id": run_id, "ts": _now(), "rc": rc, "status": status,
                  "seconds": round(time.time() - t0, 1), "tail": tail})
    return 0 if status == "OK" else (2 if rc is None else 1)


def task_xml(name: str, trigger: str, limit_min: float, logon: str, action_exe: str, action_args: str,
             workdir: str | None) -> str:
    start = datetime.now().replace(microsecond=0).isoformat()
    if trigger.startswith("every:"):
        trig = (f"<TimeTrigger><StartBoundary>{start}</StartBoundary><Enabled>true</Enabled>"
                f"<Repetition><Interval>PT{int(trigger[6:])}M</Interval><StopAtDurationEnd>false</StopAtDurationEnd>"
                f"</Repetition></TimeTrigger>")
    elif trigger.startswith("daily:"):
        hh, mm = trigger[6:].split(":")
        day = datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0).isoformat()
        trig = (f"<CalendarTrigger><StartBoundary>{day}</StartBoundary><Enabled>true</Enabled>"
                f"<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>")
    else:
        trig = "<LogonTrigger><Enabled>true</Enabled></LogonTrigger>"
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
    logon_type = "S4U" if logon == "s4u" else "InteractiveToken"
    wd = f"<WorkingDirectory>{escape(workdir)}</WorkingDirectory>" if workdir else ""
    # Task Scheduler's own limit is a backstop above ours: `run` kills the child tree first.
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{escape(name)} (sched_task.py template; log ~/.claude/state/sched/{escape(name)}.jsonl)</Description></RegistrationInfo>
  <Triggers>{trig}</Triggers>
  <Principals><Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>{logon_type}</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT{int(limit_min) + 5}M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(action_exe)}</Command><Arguments>{escape(action_args)}</Arguments>{wd}</Exec></Actions>
</Task>
"""


def cmd_create(a: argparse.Namespace) -> int:
    if not a.command:
        raise SystemExit("give the command after --")
    command = [resolve_exe(a.command[0])] + a.command[1:]
    trigger = (f"every:{a.every_min}" if a.every_min else f"daily:{a.daily}" if a.daily else "logon")
    args = subprocess.list2cmdline([str(Path(__file__).resolve()), "run", "--name", a.name,
                                    "--limit-min", str(a.limit_min),
                                    "--ok-codes", ",".join(map(str, sorted(a.ok_codes)))]
                                   + (["--workdir", a.workdir] if a.workdir else []) + ["--"] + command)
    xml = task_xml(a.name, trigger, a.limit_min, a.logon, _pythonw(), args, a.workdir)
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(xml)
        path = f.name
    try:
        r = subprocess.run(["schtasks", "/Create", "/F", "/TN", a.name, "/XML", path],
                           capture_output=True, text=True)
    finally:
        os.unlink(path)
    print((r.stdout or r.stderr).strip())
    if r.returncode != 0:
        return 1
    print(f"registered {a.name}: {trigger}, limit {a.limit_min} min, log {LOG_DIR / (a.name + '.jsonl')}")
    print("next: python sched_task.py verify --name", a.name)
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    before = {r.get("run_id") for r in _records(a.name) if r.get("event") == "end"}
    r = subprocess.run(["schtasks", "/Run", "/TN", a.name], capture_output=True, text=True)
    if r.returncode != 0:
        print("could not start task:", (r.stdout or r.stderr).strip())
        return 1
    deadline = time.time() + a.wait_s
    while time.time() < deadline:
        fresh = [x for x in _records(a.name) if x.get("event") == "end" and x.get("run_id") not in before]
        if fresh:
            last = fresh[-1]
            print(f"{a.name}: {last['status']} rc={last['rc']} in {last['seconds']} s")
            if last.get("tail"):
                print("--- output tail ---\n" + last["tail"][-800:])
            return 0 if last["status"] == "OK" else 1
        time.sleep(3)
    print(f"{a.name}: NOT VERIFIED - no finished run logged within {a.wait_s} s "
          "(it did not start, or is still running; check `status`)")
    return 2


def cmd_status(a: argparse.Namespace) -> int:
    recs = _records(a.name)
    for x in recs[-10:]:
        print(x.get("ts"), x.get("event"), x.get("status", ""), "rc=" + str(x.get("rc", "")), x.get("seconds", ""))
    return 0 if recs else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="op", required=True)
    c = sub.add_parser("create")
    c.add_argument("--name", required=True)
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--every-min", type=int)
    g.add_argument("--daily", help="HH:MM local time")
    g.add_argument("--at-logon", action="store_true")
    c.add_argument("--limit-min", type=float, default=30, help="kill the run (whole tree) after this")
    c.add_argument("--ok-codes", default="0", help="exit codes that count as success, e.g. 0,1")
    c.add_argument("--workdir")
    c.add_argument("--logon", choices=["interactive", "s4u"], default="interactive",
                   help="s4u: runs without a desktop session (no windows on a shared workstation; needs admin to register)")
    c.add_argument("command", nargs=argparse.REMAINDER)
    v = sub.add_parser("verify")
    v.add_argument("--name", required=True)
    v.add_argument("--wait-s", type=int, default=300)
    s = sub.add_parser("status")
    s.add_argument("--name", required=True)
    r = sub.add_parser("run")
    r.add_argument("--name", required=True)
    r.add_argument("--limit-min", type=float, default=30)
    r.add_argument("--ok-codes", default="0")
    r.add_argument("--workdir")
    r.add_argument("command", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if hasattr(a, "ok_codes"):
        a.ok_codes = {int(x) for x in str(a.ok_codes).split(",") if x.strip()}
    if getattr(a, "command", None) and a.command[:1] == ["--"]:
        a.command = a.command[1:]
    return {"create": cmd_create, "verify": cmd_verify, "status": cmd_status, "run": cmd_run}[a.op](a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # pythonw has no stderr: an unlogged crash looks like "Last Result 1" and nothing else
        import traceback
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "_wrapper-errors.log").open("a", encoding="utf-8") as f:
            f.write(f"{_now()} argv={sys.argv!r}\n{traceback.format_exc()}\n")
        sys.exit(2)
