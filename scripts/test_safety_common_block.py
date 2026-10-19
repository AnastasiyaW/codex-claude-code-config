"""block() refuses once per Stop, then lets the re-entered Stop through.

Claude Code sets ``stop_hook_active`` when a Stop is retried after a hook
blocked it. A gate that blocks again on that retry wedges the session, so
``safety_common.block`` turns into ``allow`` there. Every other event, and a
first Stop, must still block.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
PROBE = (
    "import sys; sys.path.insert(0, sys.argv[1]); import safety_common as s; "
    "s.LOG_PATH = s.Path(sys.argv[2]); s.read_event(); s.block('probe reason')"
)


def run(event: dict, tmp: Path) -> str:
    r = subprocess.run(
        [sys.executable, "-c", PROBE, str(HOOKS), str(tmp / "log.jsonl")],
        input=json.dumps(event), capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


class BlockOnStopReentry(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def test_first_stop_blocks(self):
        out = run({"hook_event_name": "Stop", "stop_hook_active": False}, self.tmp)
        self.assertIn('"decision": "block"', out)

    def test_reentered_stop_passes(self):
        for name in ("Stop", "SubagentStop"):
            out = run({"hook_event_name": name, "stop_hook_active": True}, self.tmp)
            self.assertNotIn("block", out, name)

    def test_flag_on_other_events_still_blocks(self):
        out = run({"hook_event_name": "PreToolUse", "stop_hook_active": True}, self.tmp)
        self.assertIn('"decision": "block"', out)


if __name__ == "__main__":
    unittest.main()
