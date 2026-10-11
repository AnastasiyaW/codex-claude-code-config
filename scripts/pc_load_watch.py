#!/usr/bin/env python3
"""PC load watch: snapshot load, find hung agent processes, track memory growth.

Owner directive 2026-10-11: watch this PC's load, kill hung processes promptly,
find where memory leaks. One run = one sample; a scheduled task runs it every
5 minutes (`--install-task`). State lives in ~/.claude/state/pc-load/:
  history.jsonl  one line per run (totals + per-process private MB)
  latest.md      human summary of the last run (what agents/owner read)
  kills.jsonl    every process this tool killed, with the reason

Auto-kill is limited to one proven-safe class: hook processes (command line
under .claude/.codex hooks) older than HOOK_MAX_AGE_MIN that made no CPU
progress during the sample window. Hooks have their own timeouts in the
harness; one alive for 20+ minutes is a dead child, not work (measured
2026-10-11: five hooks from 07:18 sat for 5.5 h at 0 CPU). Everything else is
only reported: killing a test run, tunnel or app process is the agent's call.

Exit codes: 0 nothing to report, 1 findings (hung/leak/low memory), 2 sample
could not be taken.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - reported as "could not check"
    print("psutil missing: sample NOT taken (this is not a pass)", file=sys.stderr)
    sys.exit(2)

STATE = Path.home() / ".claude" / "state" / "pc-load"
HOOK_MAX_AGE_MIN = 20          # harness hook timeouts are minutes, not tens of minutes
STALE_REPORT_AGE_H = 3         # non-hook process idle this long is reported as hung?
SAMPLE_S = 20                  # CPU progress window
LOW_AVAIL_GB = 3.0             # below this the PC starts swapping hard (10.10: 1.6 GB free)
LEAK_MIN_GROWTH_MB = 500       # same process grew this much ...
LEAK_WINDOW_H = 3              # ... within this window
APPINFO_HANDLES_PER_H = 2000   # Appinfo leaked ~9k/h via the WindowsApps python alias (2026-10-11)
HISTORY_KEEP_H = 72
WATCH_NAMES = {"python.exe", "pythonw.exe", "node.exe", "node_repl.exe", "claude.exe",
               "codex.exe", "bash.exe", "powershell.exe", "pwsh.exe", "uv.exe", "cmd.exe"}


# A hook process RUNS a script from a hooks dir: `python "<...>/.claude/.../hooks/x.py"` or the
# harness wrapper `bash -c "python \"<...>/hooks/x.py\""`. A shell whose command merely mentions
# such a path (an agent editing hooks, a test) must not match: 2026-10-11 the broad
# substring rule killed the agent's own bash during the negative control.
_HOOK_RE = re.compile(r"^(?:.*?/bash(?:\.exe)?\s+-c\s+|bash\s+-c\s+)?(?:[a-z]:/[^;&|]*?/)?pythonw?(?:\.exe)?\s+"
                      r"/?[a-z]:/users/\S+/\.(?:claude|codex)/\S*hooks/[^\s/]+\.py/?(?:\s+--?[\w-]+(?:\s+\w+)?)*$")


def _is_hook(cmd: str) -> bool:
    c = cmd.replace("\\", "/").replace('"', "").replace("'", "").lower().strip()
    return len(c) < 400 and not any(ch in c for ch in ";&|") and bool(_HOOK_RE.match(c))


def _appinfo_handles() -> int | None:
    try:
        pid = psutil.win_service_get("Appinfo").pid()
        return psutil.Process(pid).num_handles() if pid else None
    except Exception:
        return None


def _load_history() -> list[dict]:
    path = STATE / "history.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def sample() -> dict:
    now = time.time()
    procs = {}
    for p in psutil.process_iter(["pid", "ppid", "name", "create_time", "cmdline"]):
        try:
            procs[p.pid] = (p, p.cpu_times())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    cpu_total = psutil.cpu_percent(interval=SAMPLE_S)
    rows = []
    for pid, (p, t0) in procs.items():
        try:
            t1 = p.cpu_times()
            mem = p.memory_info()
            info = p.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        cmd = " ".join(info.get("cmdline") or [])
        rows.append({
            "pid": pid, "ppid": info["ppid"], "name": (info["name"] or "").lower(),
            "ctime": round(info["create_time"] or 0), "age_min": round((now - (info["create_time"] or now)) / 60),
            "cpu_delta_s": round((t1.user + t1.system) - (t0.user + t0.system), 2),
            "priv_mb": round(getattr(mem, "private", mem.vms) / 2**20),
            "parent_alive": psutil.pid_exists(info["ppid"]), "cmd": cmd[:300],
        })
    vm = psutil.virtual_memory()
    return {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "epoch": round(now),
            "cpu_pct": cpu_total, "ram_avail_gb": round(vm.available / 2**30, 1),
            "ram_total_gb": round(vm.total / 2**30, 1), "appinfo_handles": _appinfo_handles(),
            "procs": rows}


def kill_tree(pid: int) -> list[int]:
    killed = []
    try:
        root = psutil.Process(pid)
        for c in root.children(recursive=True) + [root]:
            try:
                c.kill(); killed.append(c.pid)
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs([psutil.Process(k) for k in killed if psutil.pid_exists(k)], timeout=5)
    except psutil.NoSuchProcess:
        pass
    return [k for k in killed if not psutil.pid_exists(k)]  # verified gone


def analyse(s: dict, history: list[dict], do_kill: bool, hook_age: int = HOOK_MAX_AGE_MIN) -> tuple[list[str], list[dict]]:
    findings, kills = [], []
    mine = {os.getpid()} | {a.pid for a in psutil.Process().parents()}
    if s["ram_avail_gb"] < LOW_AVAIL_GB:
        findings.append(f"LOW MEMORY: {s['ram_avail_gb']} GB free of {s['ram_total_gb']}")
    for r in s["procs"]:
        idle = r["cpu_delta_s"] < 0.05
        if r["pid"] not in mine and _is_hook(r["cmd"]) and r["age_min"] >= hook_age and idle:
            gone = kill_tree(r["pid"]) if do_kill else []
            kills.append({**{k: r[k] for k in ("pid", "name", "age_min", "cmd")}, "killed_verified": gone})
            findings.append(f"HUNG HOOK {r['pid']} age {r['age_min']} min -> "
                            f"{'killed ' + str(gone) if gone else 'NOT killed'}: {r['cmd'][:120]}")
        elif (r["name"] in WATCH_NAMES and idle and r["age_min"] >= STALE_REPORT_AGE_H * 60
              and not r["parent_alive"] and r["priv_mb"] >= 30):
            findings.append(f"ORPHAN IDLE {r['name']} {r['pid']} age {r['age_min'] // 60} h, "
                            f"{r['priv_mb']} MB, parent dead: {r['cmd'][:120]}")
    # leaks: same (pid, ctime) grew by LEAK_MIN_GROWTH_MB within LEAK_WINDOW_H
    since = s["epoch"] - LEAK_WINDOW_H * 3600
    base: dict[tuple, int] = {}
    for h in history:
        if h.get("epoch", 0) < since:
            continue
        for key, mb in h.get("mem", {}).items():
            pid, ctime = key.split(":")
            k = (int(pid), int(ctime))
            base[k] = min(base.get(k, mb), mb)
    for r in s["procs"]:
        b = base.get((r["pid"], r["ctime"]))
        if b is not None and r["priv_mb"] - b >= LEAK_MIN_GROWTH_MB:
            findings.append(f"GROWING {r['name']} {r['pid']}: {b} -> {r['priv_mb']} MB in "
                            f"<= {LEAK_WINDOW_H} h: {r['cmd'][:120]}")
    # Appinfo handle leak rate
    prev = [h for h in history if h.get("appinfo_handles")]
    if s["appinfo_handles"] and prev:
        p = prev[0] if s["epoch"] - prev[0]["epoch"] < 6 * 3600 else prev[-1]
        dt_h = max((s["epoch"] - p["epoch"]) / 3600, 1e-6)
        rate = (s["appinfo_handles"] - p["appinfo_handles"]) / dt_h
        if dt_h >= 0.25 and rate > APPINFO_HANDLES_PER_H:
            findings.append(f"APPINFO HANDLE LEAK: {s['appinfo_handles']} handles, +{rate:,.0f}/h "
                            "(something launches through a WindowsApps alias; see python-alias gotcha)")
    return findings, kills


def write_state(s: dict, history: list[dict], findings: list[str], kills: list[dict]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    mem = {f"{r['pid']}:{r['ctime']}": r["priv_mb"] for r in s["procs"] if r["priv_mb"] >= 50}
    row = {k: s[k] for k in ("ts", "epoch", "cpu_pct", "ram_avail_gb", "appinfo_handles")}
    row["mem"] = mem
    keep = [h for h in history if h.get("epoch", 0) >= s["epoch"] - HISTORY_KEEP_H * 3600] + [row]
    (STATE / "history.jsonl").write_text("".join(json.dumps(h) + "\n" for h in keep), encoding="utf-8")
    if kills:
        with (STATE / "kills.jsonl").open("a", encoding="utf-8") as f:
            for k in kills:
                f.write(json.dumps({"ts": s["ts"], **k}) + "\n")
    groups: dict[str, list] = {}
    for r in s["procs"]:
        g = groups.setdefault(r["name"], [0, 0, 0.0])
        g[0] += 1; g[1] += r["priv_mb"]; g[2] += r["cpu_delta_s"]
    top = sorted(groups.items(), key=lambda kv: -kv[1][1])[:12]
    lines = [f"# PC load {s['ts']}", "",
             f"CPU {s['cpu_pct']}% | RAM free {s['ram_avail_gb']} / {s['ram_total_gb']} GB | "
             f"Appinfo handles {s['appinfo_handles']}", "", "## Findings"]
    lines += [f"- {f}" for f in findings] or ["- none"]
    lines += ["", "## Top by private memory (name, count, MB, CPU s in window)"]
    lines += [f"- {n}: {c[0]} procs, {c[1]:,} MB, {c[2]:.1f} s" for n, c in top]
    (STATE / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def install_task() -> int:
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(sys.executable)
    tr = f'"{exe}" "{Path(__file__).resolve()}"'
    r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "5",
                        "/TN", "pc-load-watch", "/TR", tr], capture_output=True, text=True)
    print(r.stdout or r.stderr)
    return 0 if r.returncode == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-kill", action="store_true", help="report hung hooks without killing")
    ap.add_argument("--hook-age", type=int, default=HOOK_MAX_AGE_MIN, help="minutes before an idle hook counts as hung")
    ap.add_argument("--install-task", action="store_true", help="register the 5-minute scheduled task")
    a = ap.parse_args()
    if a.install_task:
        return install_task()
    try:
        s = sample()
    except Exception as e:  # sample failure is UNKNOWN, never green
        print(f"sample NOT taken: {e}", file=sys.stderr)
        return 2
    history = _load_history()
    findings, kills = analyse(s, history, do_kill=not a.no_kill, hook_age=a.hook_age)
    write_state(s, history, findings, kills)
    print((STATE / "latest.md").read_text(encoding="utf-8"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
