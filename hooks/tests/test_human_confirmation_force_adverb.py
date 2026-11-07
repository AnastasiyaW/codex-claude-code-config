"""Regression: an adverb between the stop verb and the pid list still names the pids
(owner 2026-11-03: «убей принудительно 61112 и 83296» was refused as unnamed targets,
while «убей 61112 и 83296 принудительно» passed). A number with no stop verb before it
is still no pid. Synthetic transcripts only; nothing is executed."""
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

CMD = "taskkill //PID 61112 //PID 83296 //F"


class ForceAdverbStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="force-adverb-stop-")
        self.addCleanup(self._dir.cleanup)
        guard.APPROVAL_LOG = Path(self._dir.name) / "approvals.jsonl"

    def decide(self, prompt: str, cmd: str = CMD) -> tuple[bool, str]:
        path = Path(self._dir.name) / "t.jsonl"
        entries = [
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Процессы ещё живы."}]}},
            {"type": "user", "origin": {"kind": "human"}, "isSidechain": False,
             "message": {"role": "user", "content": prompt}},
        ]
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
        return guard.approved_by_owner(cmd, {"tool_name": "Bash", "transcript_path": str(path),
                                             "session_id": "test", "tool_input": {"command": cmd}})

    def test_adverb_between_verb_and_pids_names_them(self) -> None:
        for prompt in ("убей принудительно 61112 и 83296",
                       "убей принудительно процессы 61112 и 83296",
                       "kill forcefully 61112 and 83296"):
            with self.subTest(prompt=prompt):
                self.assertEqual((True, "process stop"), self.decide(prompt))

    def test_adverb_after_pids_still_works(self) -> None:
        self.assertEqual((True, "process stop"), self.decide("убей 61112 и 83296 принудительно"))

    def test_number_without_stop_verb_is_not_a_pid(self) -> None:
        ok, why = self.decide("принудительно 61112 и 83296")
        self.assertFalse(ok, why)

    def test_other_pid_not_named(self) -> None:
        ok, why = self.decide("убей принудительно 61112", "taskkill //PID 61112 //PID 83296 //F")
        self.assertFalse(ok, why)


if __name__ == "__main__":
    unittest.main()
