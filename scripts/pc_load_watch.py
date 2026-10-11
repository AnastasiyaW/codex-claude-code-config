#!/usr/bin/env python3
"""PC load watch: snapshot load, find hung agent processes, track memory growth.

Owner directive 2026-10-11: watch this PC's load, kill hung processes promptly,
find where memory leaks. One run = one sample; a scheduled task runs it every
5 minutes (`--install-task`). State lives in ~/.claude/state/pc-load/:
  history.jsonl  one line per run (totals + per-process private MB)
  latest.md      human summary of the last run (what agents/owner read)
  kills.jsonl    every process this tool killed, with the reason

Auto-kill (owner 2026-10-11: "всё что висит без дела более получаса просто
выключай или что потеряло родителя") applies to agent worker processes
(KILL_NAMES: python/node/shells/uv/`codex exec`/plain ssh) that are not protected:
  * HUNG HOOK - a hook runner idle and older than HOOK_MAX_AGE_MIN (20 min);
  * IDLE      - the process together with its children spent < IDLE_CPU_S
                CPU-seconds over the last IDLE_MIN (30) minutes;
  * ORPHAN    - its parent is gone (or the parent PID now belongs to a younger
                process), older than ORPHAN_GRACE_MIN.
Never killed: GUI apps and claude.exe, the Codex app-server, MCP servers,
rclone mounts, ssh tunnels (-W/-L/-R/-D/-N: a parentless `ssh -W` carries a
mount), this tool and its ancestors/children, and any command line containing a
line of ~/.claude/state/pc-load/protect.txt. Detached long work that must
survive goes to contabo or gets a protect.txt line. Memory growth, low RAM and
Appinfo handle growth are only reported.

Hung rclone mounts are fixed too: a letter whose `dir` does not answer within
MOUNT_TIMEOUT_S twice in a row gets its rclone process restarted with the same
argv (logged in remounts.jsonl). A hung mount is what makes processes
unkillable: 2026-10-11 F: and W: hung, TerminateProcess on two hook processes
"succeeded" while they stayed alive, taskkill and every PowerShell start hung;
after the remount the hooks died on their own.

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
IDLE_MIN = 30                  # owner 2026-10-11: idle more than half an hour -> kill
IDLE_CPU_S = 1.0               # subtree CPU spent over IDLE_MIN below this = idle
ORPHAN_GRACE_MIN = 10          # let a just-detached child settle before calling it orphaned
SAMPLE_S = 20                  # CPU progress window
LOW_AVAIL_GB = 3.0             # below this the PC starts swapping hard (10.10: 1.6 GB free)
LEAK_MIN_GROWTH_MB = 500       # same process grew this much ...
LEAK_WINDOW_H = 3              # ... within this window
APPINFO_HANDLES_PER_H = 2000   # Appinfo leaked ~9k/h via the WindowsApps python alias (2026-10-11)
HISTORY_KEEP_H = 72
KILL_NAMES = {"python.exe", "pythonw.exe", "python3.exe", "node.exe", "node_repl.exe", "bash.exe",
              "sh.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "uv.exe", "uvx.exe", "codex.exe",
              "ssh.exe"}   # conhost is left out: it dies with its owner and is not work of its own
SHELLS = {"bash.exe", "sh.exe", "cmd.exe", "powershell.exe", "pwsh.exe"}
# Long-lived by design: app MCP servers, the Codex app-server, rclone and this tool. Machine-
# specific daemons (port forwards, sync loops, widgets) go in protect.txt, not here.
PROTECT_DEFAULT = ("claude extensions", "mcp", "app-server", "pc_load_watch", "--listen", "rclone")
_SSH_TUNNEL = re.compile(r"(^|\s)-[a-z]*[wlrdns]")   # -W/-L/-R/-D/-N tunnels, -s sftp (rclone transport)
_CODEX_EXEC = re.compile(r'codex(?:\.exe)?"?\s+exec\b')   # one-shot run; the app passes "-c ..." first
AUTOSTART_MIN = 10            # parentless and born this soon after boot = logon autostart daemon


def _protected(r: dict, extra: list[str], boot: float) -> bool:
    c = r["cmd"].lower()
    if r["name"] not in KILL_NAMES or any(m in c for m in PROTECT_DEFAULT) or any(m in c for m in extra):
        return True
    if r["name"] in SHELLS and len(c.split()) <= 1:
        return True                                   # bare shell = the owner's interactive terminal tab
    if not r["parent_alive"] and r["ctime"] - boot <= AUTOSTART_MIN * 60:
        return True                                   # logon autostart daemon, parentless by design
    if r["name"] == "codex.exe" and not _CODEX_EXEC.search(c):
        return True                                   # the Codex app itself, not a one-shot run
    if r["name"] == "ssh.exe" and _SSH_TUNNEL.search(c):
        return True
    return False


def _protect_list() -> list[str]:
    f = STATE / "protect.txt"
    if not f.exists():
        return []
    return [ln.strip().lower() for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


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
            "cpu_s": round(t1.user + t1.system, 2),
            "parent_alive": _parent_alive(info["ppid"], info["create_time"] or 0), "cmd": cmd,
        })
    kids: dict[int, list[int]] = {}
    for r in rows:
        kids.setdefault(r["ppid"], []).append(r["pid"])
    by = {r["pid"]: r for r in rows}

    def tree(pid: int, seen: set) -> tuple[float, float]:
        if pid in seen or pid not in by:
            return 0.0, 0.0
        seen.add(pid)
        cum, dlt = by[pid]["cpu_s"], by[pid]["cpu_delta_s"]
        for k in kids.get(pid, []):
            c, d = tree(k, seen)
            cum += c
            dlt += d
        return cum, dlt
    for r in rows:
        r["tree_cpu_s"], r["tree_delta_s"] = (round(x, 2) for x in tree(r["pid"], set()))
    vm = psutil.virtual_memory()
    return {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "epoch": round(now),
            "cpu_pct": cpu_total, "ram_avail_gb": round(vm.available / 2**30, 1),
            "ram_total_gb": round(vm.total / 2**30, 1), "appinfo_handles": _appinfo_handles(),
            "procs": rows}


def _parent_alive(ppid: int, ctime: float) -> bool:
    if ppid in (0, 4):
        return True
    try:
        return psutil.Process(ppid).create_time() <= ctime + 1   # a younger "parent" is a reused PID
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return False


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


def _idle_since(r: dict, history: list[dict], now: int, idle_min: int) -> bool:
    """Subtree spent < IDLE_CPU_S over at least idle_min minutes of recorded history."""
    if r["tree_delta_s"] >= 0.05:
        return False
    if idle_min == 0:
        return True
    key = f"{r['pid']}:{r['ctime']}"
    old = [h for h in history if h.get("epoch", 0) <= now - idle_min * 60 and key in h.get("cpu", {})]
    return bool(old) and r["tree_cpu_s"] - old[-1]["cpu"][key] < IDLE_CPU_S


MOUNT_TIMEOUT_S = 25
_MOUNT_RE = re.compile(r"\smount\s+\S+\s+([A-Za-z]):")


def _probe_letters(letters: list[str]) -> set[str]:
    """Letters whose `dir` did not answer. The probe child is abandoned, never waited on:
    a process blocked on a hung mount cannot be killed, so waiting would hang this tool."""
    procs = {L: subprocess.Popen(["cmd.exe", "/d", "/c", f"dir {L}:\\ /b >nul 2>&1"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=0x08000000)
             for L in letters}
    deadline = time.time() + MOUNT_TIMEOUT_S
    while time.time() < deadline and any(p.poll() is None for p in procs.values()):
        time.sleep(0.5)
    return {L for L, p in procs.items() if p.poll() is None}


def check_mounts(do_fix: bool) -> list[str]:
    mounts = {}
    for p in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        if (p.info["name"] or "").lower() != "rclone.exe":
            continue
        m = _MOUNT_RE.search(" ".join(p.info["cmdline"] or []))
        if m:
            mounts[m.group(1).upper()] = p.info
    hung = _probe_letters(sorted(mounts))
    if hung:
        hung = _probe_letters(sorted(hung))          # second look: a slow listing is not a hang
    findings = []
    for L in sorted(hung):
        info = mounts[L]
        note = "NOT restarted (dry run)"
        if do_fix:
            try:
                psutil.Process(info["pid"]).kill()
                psutil.wait_procs([psutil.Process(info["pid"])], timeout=15)
            except psutil.NoSuchProcess:
                pass
            new = subprocess.Popen(info["cmdline"], cwd=info["cwd"], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                                   creationflags=0x00000008 | 0x08000000 | 0x00000200)
            time.sleep(5)                            # let rclone re-create the mount point
            ok = not _probe_letters([L])
            note = f"restarted rclone {info['pid']} -> {new.pid}, answers now: {ok}"
            STATE.mkdir(parents=True, exist_ok=True)
            with (STATE / "remounts.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "letter": L, "old_pid": info["pid"], "new_pid": new.pid,
                                    "answers": ok, "argv": info["cmdline"]}) + "\n")
        findings.append(f"HUNG MOUNT {L}: (no answer in {MOUNT_TIMEOUT_S} s twice) -> {note}")
    return findings


def analyse(s: dict, history: list[dict], do_kill: bool, hook_age: int = HOOK_MAX_AGE_MIN,
            idle_min: int = IDLE_MIN) -> tuple[list[str], list[dict]]:
    findings, kills = [], []
    me = psutil.Process()
    mine = {me.pid} | {a.pid for a in me.parents()} | {c.pid for c in me.children(recursive=True)}
    extra = _protect_list()
    boot = psutil.boot_time()
    if s["ram_avail_gb"] < LOW_AVAIL_GB:
        findings.append(f"LOW MEMORY: {s['ram_avail_gb']} GB free of {s['ram_total_gb']}")
    targets: dict[int, tuple[str, dict]] = {}
    for r in s["procs"]:
        if r["pid"] in mine:
            continue
        if _is_hook(r["cmd"]) and r["age_min"] >= hook_age and r["tree_delta_s"] < 0.05:
            targets[r["pid"]] = ("HUNG HOOK", r)
        elif _protected(r, extra, boot):
            continue
        elif not r["parent_alive"] and r["age_min"] >= ORPHAN_GRACE_MIN:
            targets[r["pid"]] = ("ORPHAN", r)
        elif r["age_min"] >= idle_min and _idle_since(r, history, s["epoch"], idle_min):
            targets[r["pid"]] = (f"IDLE {idle_min}+ min", r)
    # kill only the topmost target of each tree; kill_tree takes the children with it
    for pid, (why, r) in targets.items():
        if r["ppid"] in targets:
            continue
        gone = kill_tree(pid) if do_kill else []
        if do_kill and pid not in gone:
            why += " UNKILLABLE (blocked in the kernel, usually on a hung mount)"
        kills.append({"why": why, **{k: r[k] for k in ("pid", "name", "age_min", "priv_mb", "cmd")},
                      "killed_verified": gone})
        findings.append(f"{why} {r['name']} {pid} age {r['age_min']} min, {r['priv_mb']} MB -> "
                        f"{'killed ' + str(gone) if gone else 'NOT killed'}: {r['cmd'][:110]}")
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


def write_state(s: dict, history: list[dict], findings: list[str], kills: list[dict],
                dry: bool = False) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    mem = {f"{r['pid']}:{r['ctime']}": r["priv_mb"] for r in s["procs"] if r["priv_mb"] >= 50}
    row = {k: s[k] for k in ("ts", "epoch", "cpu_pct", "ram_avail_gb", "appinfo_handles")}
    row["mem"] = mem
    row["cpu"] = {f"{r['pid']}:{r['ctime']}": r["tree_cpu_s"] for r in s["procs"] if r["name"] in KILL_NAMES}
    keep = [h for h in history if h.get("epoch", 0) >= s["epoch"] - HISTORY_KEEP_H * 3600] + [row]
    (STATE / "history.jsonl").write_text("".join(json.dumps(h) + "\n" for h in keep), encoding="utf-8")
    if kills and not dry:                      # a dry run kills nothing, so it logs nothing
        with (STATE / "kills.jsonl").open("a", encoding="utf-8") as f:
            for k in kills:
                f.write(json.dumps({"ts": s["ts"], **k}) + "\n")
    groups: dict[str, list] = {}
    for r in s["procs"]:
        g = groups.setdefault(r["name"], [0, 0, 0.0])
        g[0] += 1; g[1] += r["priv_mb"]; g[2] += r["cpu_delta_s"]
    top = sorted(groups.items(), key=lambda kv: -kv[1][1])[:12]
    lines = [f"# PC load {s['ts']}" + (" (DRY RUN: nothing killed)" if dry else ""), "",
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
    ap.add_argument("--no-kill", action="store_true", help="report what would be killed, kill nothing")
    ap.add_argument("--hook-age", type=int, default=HOOK_MAX_AGE_MIN, help="minutes before an idle hook counts as hung")
    ap.add_argument("--idle-min", type=int, default=IDLE_MIN,
                    help="minutes without CPU before a worker counts as idle")
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
    mount_findings = check_mounts(do_fix=not a.no_kill)
    findings, kills = analyse(s, history, do_kill=not a.no_kill, hook_age=a.hook_age,
                              idle_min=a.idle_min)
    findings = mount_findings + findings
    write_state(s, history, findings, kills, dry=a.no_kill)
    print((STATE / "latest.md").read_text(encoding="utf-8"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
