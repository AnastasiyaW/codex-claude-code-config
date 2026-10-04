"""A repeated Stop must never emit a second block through safety_common."""
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path


PATH = Path(__file__).resolve().parents[1] / "safety_common.py"


def load():
    spec = importlib.util.spec_from_file_location("safety_common_reentry", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


for event_name in ("Stop", "SubagentStop"):
    module = load()
    saved_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps({"hook_event_name": event_name, "stop_hook_active": True}))
        module.read_event()
    finally:
        sys.stdin = saved_stdin
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            module.block("would loop")
    except SystemExit as exc:
        assert exc.code == 0, (event_name, exc.code)
        assert not output.getvalue(), (event_name, output.getvalue())
    else:
        raise AssertionError(f"{event_name} block() returned")

print("PASS Stop/SubagentStop re-entry exits without decision:block")
