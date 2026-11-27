"""Regression (owner 2026-11-21): she pasted the stop command herself, alone and after «удали», and both were
refused as «does not ask to stop a process»; she asked for a ready «останови …» message she can resend instead of
«да» answers that never land. Her own pasted Windows stop line is the request. Every pid must still be in her
message; a mention mid-sentence or under a negation is not a request. Synthetic only."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "human-confirmation-guard.py"
_spec = importlib.util.spec_from_file_location("human_confirmation_guard", HOOK)
guard = importlib.util.module_from_spec(_spec)
_argv, sys.argv = sys.argv, [str(HOOK)]
_spec.loader.exec_module(guard)
sys.argv = _argv

CMD = "task" + "kill //PID 21852 //PID 10112"


class OwnerStopLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="owner-stop-line-")
        self.addCleanup(self._dir.cleanup)
        guard.APPROVAL_LOG = Path(self._dir.name) / "approvals.jsonl"

    def decide(self, prompt: str, cmd: str = CMD) -> tuple[bool, str]:
        path = Path(self._dir.name) / "t.jsonl"
        entries = [
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Копии сервера держат память."}]}},
            {"type": "user", "origin": {"kind": "human"}, "isSidechain": False,
             "message": {"role": "user", "content": prompt}},
        ]
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
        return guard.approved_by_owner(cmd, {"tool_name": "Bash", "transcript_path": str(path),
                                             "session_id": "test", "tool_input": {"command": cmd}})

    def test_bare_pasted_command_passes(self) -> None:
        self.assertEqual((True, "process stop"), self.decide(CMD))

    def test_udali_plus_pasted_command_passes(self) -> None:
        self.assertEqual((True, "process stop"), self.decide("удали " + CMD))

    def test_ready_stop_message_passes(self) -> None:
        for prompt in ("останови " + CMD, "<!-- reply 1 -->\n> Хук не принял «да».\n\nостанови " + CMD):
            with self.subTest(prompt=prompt[:30]):
                self.assertEqual((True, "process stop"), self.decide(prompt))

    def test_pid_not_in_her_message_refused(self) -> None:
        ok, _ = self.decide("task" + "kill //PID 21852", cmd=CMD)
        self.assertFalse(ok)

    def test_mid_sentence_mention_refused(self) -> None:
        ok, _ = self.decide("я видела " + CMD + " в логе")
        self.assertFalse(ok)

    def test_negated_refused(self) -> None:
        ok, _ = self.decide("не надо " + CMD)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
