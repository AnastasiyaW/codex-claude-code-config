"""Regression: one owner message may remove several named units from autostart and may name the host
(owner 2026-11-18: «убери из автозапуска A и B на gpu-host» was refused). Every disabled unit must be in her
list, and a named host must be the host the command reaches. Synthetic transcripts only; nothing is executed."""
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

ASK = "убери из автозапуска jobs-a1 и jobs-a2 на gpu-host"


class DisableUnitListTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="disable-unit-list-")
        self.addCleanup(self._dir.cleanup)
        guard.APPROVAL_LOG = Path(self._dir.name) / "approvals.jsonl"

    def decide(self, cmd: str, prompt: str = ASK) -> bool:
        path = Path(self._dir.name) / "t.jsonl"
        entries = [
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Готово."}]}},
            {"type": "user", "origin": {"kind": "human"}, "isSidechain": False,
             "message": {"role": "user", "content": prompt}},
        ]
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
        ok, _ = guard.approved_by_owner(cmd, {"tool_name": "Bash", "transcript_path": str(path),
                                              "session_id": "test", "tool_input": {"command": cmd}})
        return ok

    def test_each_listed_unit_on_the_named_host_passes(self) -> None:
        for cmd in ("tailscale ssh ws@gpu-host 'sudo -n systemctl disable jobs-a1'",
                    "ssh gpu-host 'sudo -n systemctl disable jobs-a2.service'"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.decide(cmd))

    def test_unit_not_in_the_list_is_refused(self) -> None:
        self.assertFalse(self.decide("ssh gpu-host 'sudo -n systemctl disable jobs-a3'"))

    def test_other_host_than_named_is_refused(self) -> None:
        self.assertFalse(self.decide("ssh other-host 'sudo -n systemctl disable jobs-a1'"))

    def test_list_without_host_and_with_comma_passes(self) -> None:
        self.assertTrue(self.decide("ssh h 'sudo -n systemctl disable jobs-a2'",
                                    "убери из автозапуска jobs-a1, jobs-a2"))

    def test_negation_in_list_is_refused(self) -> None:
        self.assertFalse(self.decide("ssh h 'sudo -n systemctl disable jobs-a2'",
                                     "убери из автозапуска jobs-a1, но не jobs-a2"))


if __name__ == "__main__":
    unittest.main()
