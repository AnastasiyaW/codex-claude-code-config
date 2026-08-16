# -*- coding: utf-8 -*-
"""One session's unfinished delivery must not wedge another session.

Measured 2026-08-16: this session could neither end nor write a file in the hub,
because two OTHER sessions had open delivery intents and the working tree carried
1247 changed paths that this session never touched. Collateral of that shape is
what makes people switch a gate off, so the gate has to hold the session that
owns the delivery and let the others work.

What must NOT change: a session that owns an unresolved intent still has to
produce a delivery case. That is the whole point of the protocol.
"""
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import contextlib
import atexit
import shutil

TMP = pathlib.Path(tempfile.mkdtemp(prefix="delivery-guard-test-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
STATE = TMP / "state"
STATE.mkdir(parents=True, exist_ok=True)
os.environ["AGENT_ROOT_CAUSE_STATE_DIR"] = str(STATE)

REPO = TMP / "repo"
REPO.mkdir()
subprocess.run(["git", "init", "-q", str(REPO)], check=True, capture_output=True)
(REPO / "thing.py").write_text("print('someone else was here')\n", encoding="utf-8")

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
GUARD = HOOKS / "root-cause-delivery-guard.py"
spec = importlib.util.spec_from_file_location("delivery_guard", GUARD)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def record(session_id: str) -> None:
    g.record_intent(REPO, "incident", f"prompt from {session_id}", session_id=session_id)


def ran(fn, event) -> str:
    """Run a hook entry point and return whatever it printed (a block, or nothing)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            fn(event)
        except SystemExit:
            pass
    return buffer.getvalue().strip()


def blocked(output: str) -> bool:
    if not output:
        return False
    try:
        return json.loads(output).get("decision") == "block"
    except json.JSONDecodeError:
        return False


results = []

# 1. Another session owns an unresolved intent; mine owns none.
record("session-other")
os.chdir(REPO)
out_stop = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop, with only another session's intent open",
                False, blocked(out_stop)))

edit_event = {
    "session_id": "session-mine",
    "tool_name": "Write",
    "tool_input": {"file_path": str(REPO / "notes.py")},
}
out_edit = ran(g.pretool, edit_event)
results.append(("my source edit, with only another session's intent open",
                False, blocked(out_edit)))

# 2. The protocol itself must survive: MY intent, no case of mine.
record("session-mine")
out_mine = ran(g.pretool, edit_event)
results.append(("my source edit while I own an unresolved intent and no case",
                True, blocked(out_mine)))

failures = [r for r in results if r[1] != r[2]]
for label, expected, got in results:
    print(f"  {'ok  ' if expected == got else 'FAIL'} expected={'block' if expected else 'pass':<5} "
          f"got={'block' if got else 'pass':<5} {label}")
print()
if failures:
    print(f"{len(failures)} of {len(results)} wrong")
    sys.exit(1)
print(f"all {len(results)} cases correct")
