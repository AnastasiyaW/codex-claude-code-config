#!/usr/bin/env python3
"""Starting a job is a promise to look at it. This holds you to it.

A launch detaches work that outlives the call: training, a scraper, a build, a poller.
Nothing afterwards forces anyone to confirm it actually started — and the failure is
silent by construction, because a job that died in its first second looks exactly like
a job that is running quietly. The usual tells all point the wrong way: no output can
mean progress, an empty log can mean the writer never opened it, and over a flaky link
even the absence of an answer means nothing at all.

Measured over 30 days of this machine's history: 2,958 launches, of which 42 (1.4%)
were never probed anywhere later in the same session, spread across 28 of 175 sessions.
So roughly one session in six ended with something running that nobody had confirmed
was running. Within 30 minutes of the launch the figure is 11.5% — the check usually
happens, just late enough that a dead job burns an hour of wall clock first.

This is the "structured heartbeat" of https://andrewcrookston.com/articles/close-the-loop.html:
a generic reminder lets the turn proceed anyway, a structured one refuses to advance
until the precondition holds. The precondition here is one probe.

Wire on BOTH events, like repeated-attempt-guard:
    PostToolUse  -- records launches, and records probes that clear them
    Stop         -- refuses to end while a launch has never been probed

It cannot loop the way anthropics/claude-code#55754 did: the shared stop-budget caps
any gate at three refusals, and a single probe clears the watch permanently.

Tunables: CLAUDE_LAUNCH_WINDOW_H (6) -- how far back an unprobed launch still counts
Bypass:   CLAUDE_SKIP_LAUNCH_WATCH=1, or `# claude-bypass: launch-watch` in the command
Self-test: python launch-watch-guard.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import log, read_event  # noqa: E402

WINDOW_H = float(os.environ.get("CLAUDE_LAUNCH_WINDOW_H", "6"))
STATE = Path(os.environ.get("CLAUDE_LAUNCH_STATE",
                            str(Path.home() / ".claude" / "state" / "launches.jsonl")))

# Specific launch verbs only. A trailing `&` and a bare Start-Process also matched folder
# openers and ordinary chained commands; over-matching a shell string is how three other
# guards this week produced hundreds of false positives before being narrowed.
LAUNCH = re.compile(
    r"(?:^|[\s;&|])nohup\s|"
    r"\bdocker\s+(?:run|compose\s+up)\b[^|;]*\s-d\b|"
    r"\bschtasks\s+/create\b|"
    r"\bsystemd-run\b|"
    r"\bsbatch\b|"
    r"\b(?:tmux|screen)\s+new-session\s+-d|"
    r"\bStart-Job\b",
    re.I | re.M,
)
NOT_A_JOB = re.compile(r"\b(explorer\.exe|xdg-open|open\s+-a|notepad|code\s+\.)\b", re.I)
PROBE = re.compile(
    r"\b(ps\s+aux|pgrep|tasklist|Get-Process|nvidia-smi|docker\s+ps|docker\s+logs|"
    r"squeue|schtasks\s+/query|tail\b|Get-Content|journalctl|systemctl\s+status|"
    r"rocm-smi|qstat|kubectl\s+get)\b",
    re.I,
)
# What the launch names that a later command can be recognised by. The stem threshold is
# 2, not 4: at 4 the commonest log name of all, `run.log`, did not match its own launch.
TOKEN = re.compile(r"[\w./\\-]{2,}\.(?:log|out|err|jsonl)\b|[\w-]{2,}\.py\b|--name[= ]([\w-]+)")
REMOTE = re.compile(r"\b(ssh|tailscale\s+ssh|scp|rsync)\b", re.I)


def tokens_of(command: str) -> list[str]:
    return sorted({m.group(0).lower() for m in TOKEN.finditer(command)})[:6]


def is_launch(command: str) -> bool:
    if not command or NOT_A_JOB.search(command):
        return False
    return bool(LAUNCH.search(command))


def _load(now: float) -> list[dict]:
    try:
        rows = [json.loads(l) for l in STATE.read_text(encoding="utf-8-sig").splitlines()
                if l.strip()]
    except (OSError, ValueError):
        return []
    return [r for r in rows if now - float(r.get("ts", 0)) <= WINDOW_H * 3600]


def _append(row: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        with STATE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def unprobed(rows: list[dict]) -> list[dict]:
    """Launches with no probe recorded after them.

    A probe clears every launch that preceded it whose tokens it names, and a generic
    liveness probe clears all of them: someone who ran `nvidia-smi` or `docker ps` has
    looked at the machine, which is the thing being asked for.
    """
    launches = [r for r in rows if r.get("kind") == "launch"]
    probes = [r for r in rows if r.get("kind") == "probe"]
    out = []
    for launch in launches:
        cleared = False
        for probe in probes:
            if float(probe["ts"]) <= float(launch["ts"]):
                continue
            if probe.get("generic"):
                cleared = True
                break
            if set(probe.get("tokens") or []) & set(launch.get("tokens") or []):
                cleared = True
                break
        if not cleared:
            out.append(launch)
    return out


def record(event: dict) -> int:
    tool_input = event.get("tool_input") or {}
    command = str(tool_input.get("command") or "")
    if not command or "claude-bypass: launch-watch" in command:
        return 0
    now = time.time()
    background = bool(tool_input.get("run_in_background"))
    if background or is_launch(command):
        _append({"ts": now, "kind": "launch", "cmd": command.replace("\n", " ")[:160],
                 "tokens": tokens_of(command), "remote": bool(REMOTE.search(command))})
        # Logged, not just recorded in the watch file: without an audit line there is no
        # way to answer "has this hook ever fired in production", which is the question
        # every one of these guards exists to make answerable about something else.
        log("INFO", "launch_watch", "armed",
            "background" if background else "launch-verb", command[:200])
        return 0
    if PROBE.search(command):
        _append({"ts": now, "kind": "probe", "generic": True, "tokens": tokens_of(command)})
    else:
        found = tokens_of(command)
        if found:
            _append({"ts": now, "kind": "probe", "generic": False, "tokens": found})
    return 0


def decide() -> int:
    pending = unprobed(_load(time.time()))
    if not pending:
        return 0
    lines = [f"  - {row['cmd']}" for row in pending[:5]]
    log("BLOCK", "launch_watch", "deny", f"{len(pending)}_unprobed",
        "; ".join(row["cmd"][:60] for row in pending[:3]))
    remote = any(row.get("remote") for row in pending)
    extra = ""
    if remote:
        # From this machine's own history, 2026-06-28: over a link that answers only in
        # rare windows, a foreground probe that returns nothing is not evidence of
        # anything. The durable check has to run on the box.
        extra = (
            "\n\nAt least one of these was launched over ssh. On a flaky link the absence "
            "of an answer is not evidence the job is alive — put the check on the box "
            "itself (a scheduled local script with a retry cap that removes itself once "
            "progress appears), rather than probing across the link."
        )
    print(json.dumps({
        "decision": "block",
        "reason": (
            f"{len(pending)} job(s) were started in the last {WINDOW_H:.0f}h and never "
            f"checked on:\n" + "\n".join(lines) +
            "\n\nA job that died in its first second looks exactly like one running "
            "quietly, so confirm it is actually computing: the process exists, the log "
            "is growing, the GPU is busy, the output is landing. One probe clears this."
            + extra +
            "\n\nDeliberate override: CLAUDE_SKIP_LAUNCH_WATCH=1."
        ),
    }))
    return 0


def main() -> int:
    if os.environ.get("CLAUDE_SKIP_LAUNCH_WATCH") == "1":
        return 0
    event = read_event()
    if not event:
        return 0
    hook = event.get("hook_event_name") or ""
    if hook == "PostToolUse":
        return record(event)
    if event.get("stop_hook_active"):
        return 0
    return decide()


def self_test() -> int:
    import tempfile

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    check("nohup is a launch", is_launch("nohup python train.py > run.log 2>&1 &"), True)
    check("detached docker is a launch", is_launch("docker run -d --name w img"), True)
    check("sbatch is a launch", is_launch("sbatch job.slurm"), True)
    check("a trailing & alone is not", is_launch("cd /x && make && echo ok &"), False)
    check("opening a folder is not a job",
          is_launch("nohup explorer.exe D:/out &"), False)
    check("an ordinary command is not", is_launch("git status"), False)
    check("the log path is picked up as a token",
          "run.log" in tokens_of("nohup python train.py > run.log 2>&1 &"), True)

    now = time.time()
    launch = {"ts": now - 60, "kind": "launch", "cmd": "nohup python train.py > run.log &",
              "tokens": ["run.log", "train.py"]}
    check("a launch with nothing after it is pending", len(unprobed([launch])), 1)
    named = launch, {"ts": now - 30, "kind": "probe", "generic": False, "tokens": ["run.log"]}
    check("naming its log clears it", len(unprobed(list(named))), 0)
    generic = launch, {"ts": now - 30, "kind": "probe", "generic": True, "tokens": []}
    check("a generic liveness probe clears it", len(unprobed(list(generic))), 0)
    earlier = {"ts": now - 90, "kind": "probe", "generic": True, "tokens": []}, launch
    check("a probe BEFORE the launch does not clear it", len(unprobed(list(earlier))), 1)

    global STATE
    with tempfile.TemporaryDirectory() as td:
        saved = STATE
        try:
            STATE = Path(td) / "launches.jsonl"
            record({"tool_input": {"command": "nohup python train.py > run.log 2>&1 &"}})
            check("launch persisted", len(unprobed(_load(time.time()))), 1)
            record({"tool_input": {"command": "nvidia-smi"}})
            check("probe clears it in the state file",
                  len(unprobed(_load(time.time()))), 0)
            STATE.unlink()
            record({"tool_input": {"command": "# claude-bypass: launch-watch\nnohup x &"}})
            check("bypass marker records nothing", len(_load(time.time())), 0)
            record({"tool_input": {"command": "python replay.py", "run_in_background": True}})
            check("run_in_background counts as a launch",
                  len(unprobed(_load(time.time()))), 1)
        finally:
            STATE = saved

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
