"""Regression (owner 2026-11-02, «поправь хук»): `ssh winhost taskkill //PID 15692 //PID 29148` after
«да, убей 15692 и 29148» was refused with a message that never said the remote command must be quoted.
The quoted form passes; the unquoted form stays refused (OpenSSH also reads options after the host) but
the refusal names the quoting. Synthetic transcripts only; nothing is executed."""
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

PROMPT = "да, убей 15692 и 29148"


class SshTaskkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="ssh-taskkill-")
        self.addCleanup(self._dir.cleanup)
        guard.APPROVAL_LOG = Path(self._dir.name) / "approvals.jsonl"

    def decide(self, cmd: str, prompt: str = PROMPT) -> tuple[bool, str]:
        path = Path(self._dir.name) / "t.jsonl"
        entries = [
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Лишняя копия цикла висит."}]}},
            {"type": "user", "origin": {"kind": "human"}, "isSidechain": False,
             "message": {"role": "user", "content": prompt}},
        ]
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
        return guard.approved_by_owner(cmd, {"tool_name": "Bash", "transcript_path": str(path),
                                             "session_id": "test", "tool_input": {"command": cmd}})

    def test_quoted_remote_taskkill_passes(self) -> None:
        for cmd in ("ssh winhost 'taskkill /PID 15692 /PID 29148'",
                    "ssh winhost 'taskkill //PID 15692 //PID 29148'"):
            with self.subTest(cmd=cmd):
                self.assertEqual((True, "process stop"), self.decide(cmd))

    def test_unquoted_remote_is_refused_and_says_quote(self) -> None:
        ok, why = self.decide("ssh winhost taskkill //PID 15692 //PID 29148")
        self.assertFalse(ok)
        self.assertIn("quoted as one argument", why)

    def test_unnamed_pid_still_refused(self) -> None:
        ok, _ = self.decide("ssh winhost 'taskkill /PID 15692 /PID 4242'")
        self.assertFalse(ok)

    def test_not_a_stop_request_refused(self) -> None:
        ok, _ = self.decide("ssh winhost 'taskkill /PID 15692'", prompt="поправь хук")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
