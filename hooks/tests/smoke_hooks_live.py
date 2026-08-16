# -*- coding: utf-8 -*-
"""End-to-end smoke: feed the real guards real events and read their verdicts.

Unit tests exercise the matcher. This runs the hook processes exactly as the
harness does - JSON on stdin, JSON verdict on stdout - because a guard that
imports fine can still crash on an event, and a crash is a guard that is not
there (this codebase has been bitten by exactly that: a hook that failed to
import and therefore failed open for five days).
"""
import json
import os
import pathlib
import subprocess
import sys

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))

CASES = [
    ("human-confirmation-guard.py",
     {"tool_name": "Bash", "tool_input": {"command": "# Reason: the reboot history\nuptime -p"}},
     False, "a comment naming a restart"),
    ("human-confirmation-guard.py",
     {"tool_name": "Bash", "tool_input": {"command": "sudo reboot"}},
     True, "an actual restart"),
    ("destructive-command-guard.py",
     {"tool_name": "Bash", "tool_input": {"command": 'grep -n "rm -rf" /var/log/history'}},
     False, "searching a log for the phrase"),
    # Two corrections live in this one case, both found by running the guard for
    # real rather than trusting the matcher:
    #  * this guard's contract is catastrophic ROOTS, not any recursive delete -
    #    `rm -rf /srv/scratch/data` matches none of its patterns;
    #  * CLAUDE_ALLOW_DESTRUCTIVE=1 is live in the inherited environment, so it
    #    ALLOWS even `rm -rf /home` - correctly, and now visibly.
    ("destructive-command-guard.py",
     {"tool_name": "Bash", "tool_input": {"command": "rm -rf /home"}},
     bool(os.environ.get("CLAUDE_ALLOW_DESTRUCTIVE", "").strip().lower()
          not in {"1", "true", "yes", "on"}),
     "a catastrophic root: blocked, unless the environment bypass is on"),
    ("git-destructive-guard.py",
     {"tool_name": "Bash", "tool_input": {"command": 'echo "never use git reset --hard here"'}},
     False, "the phrase inside an echo"),
    ("git-destructive-guard.py",
     {"tool_name": "Bash", "tool_input": {"command": "git reset --hard origin/main"}},
     True, "an actual hard reset"),
]

failures = []
for hook, event, should_block, why in CASES:
    path = HOOKS / hook
    if not path.exists():
        print(f"  SKIP {hook} not found")
        continue
    proc = subprocess.run([sys.executable, str(path)], input=json.dumps(event),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)
    out = (proc.stdout or "").strip()
    verdict = ""
    try:
        verdict = json.loads(out).get("decision", "") if out else ""
    except json.JSONDecodeError:
        verdict = f"unparseable: {out[:40]}"
    did_block = verdict == "block"
    ok = did_block == should_block
    if not ok:
        failures.append((hook, why, should_block, verdict, proc.stderr[:120]))
    print(f"  {'ok  ' if ok else 'FAIL'} {hook:<30} expected={'block' if should_block else 'pass':<5} "
          f"got={'block' if did_block else 'pass':<5} {why}")

print()
if failures:
    for hook, why, expected, verdict, err in failures:
        print(f"  - {hook}: {why} -> verdict {verdict!r} {err}")
    sys.exit(1)
print(f"all {len(CASES)} live hook cases correct")
