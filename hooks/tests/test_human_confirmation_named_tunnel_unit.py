"""Regression: a systemd service the owner names in full is stopped even when its name contains the
word "tunnel" (owner 2026-11-18: «останови службы jobs-tunnel-a1 и jobs-tunnel@a2
на gpu-host» was refused, then «Да, поправь хук»). Access tunnels keep their own protected names
(ssh, autossh, cloudflared, frpc ...), and a process pattern "tunnel" for pkill stays protected.
Synthetic transcripts only; nothing is executed."""
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

ASK = "останови службы jobs-tunnel-a1 и jobs-tunnel@a2 на gpu-host"


class NamedTunnelUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="named-tunnel-unit-")
        self.addCleanup(self._dir.cleanup)
        guard.APPROVAL_LOG = Path(self._dir.name) / "approvals.jsonl"

    def decide(self, cmd: str, prompt: str = ASK) -> tuple[bool, str]:
        path = Path(self._dir.name) / "t.jsonl"
        entries = [
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Готово."}]}},
            {"type": "user", "origin": {"kind": "human"}, "isSidechain": False,
             "message": {"role": "user", "content": prompt}},
        ]
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
        return guard.approved_by_owner(cmd, {"tool_name": "Bash", "transcript_path": str(path),
                                             "session_id": "test", "tool_input": {"command": cmd}})

    def test_named_tunnel_units_are_stopped(self) -> None:
        for cmd in ("ssh gpu-host 'sudo -n systemctl stop jobs-tunnel-a1.service'",
                    "ssh gpu-host 'sudo -n systemctl stop jobs-tunnel@a2'"):
            with self.subTest(cmd=cmd):
                ok, why = self.decide(cmd)
                self.assertTrue(ok, why)

    def test_unit_not_named_is_refused(self) -> None:
        ok, _ = self.decide("ssh gpu-host 'sudo -n systemctl stop jobs-tunnel-b1.service'")
        self.assertFalse(ok)

    def test_access_tunnels_stay_protected_when_named(self) -> None:
        for unit in ("autossh-tunnel", "ssh-tunnel-prod", "cloudflared-tunnel", "frpc-tunnel"):
            with self.subTest(unit=unit):
                ok, _ = self.decide(f"ssh h 'sudo -n systemctl stop {unit}.service'", f"останови службу {unit}")
                self.assertFalse(ok)

    def test_bare_tunnel_unit_and_pattern_stay_protected(self) -> None:
        for cmd, prompt in (("ssh h 'sudo -n systemctl stop tunnel.service'", "останови службу tunnel"),
                            ("ssh h 'pkill -f tunnel'", "останови процессы tunnel")):
            with self.subTest(cmd=cmd):
                ok, _ = self.decide(cmd, prompt)
                self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
