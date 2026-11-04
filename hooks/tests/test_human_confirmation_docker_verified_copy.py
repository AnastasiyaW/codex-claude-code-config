"""Owner 2026-11-04: a data-looking docker volume is replaceable once a verified transfer contract records
its copy elsewhere; then it goes on her bare yes to the «Удаление» block like any other named volume."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_HOOKS))
_SPEC = importlib.util.spec_from_file_location("hcg", _HOOKS / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

VOL = "stand_staging-postgres-data"
CMD = f"ssh host1 'docker volume rm {VOL}'"
BLOCK = f"**Удаление** — 1 том, ответь «да»:\n```\ndocker volume {VOL}\n```\n"


class VerifiedCopy(unittest.TestCase):
    def setUp(self) -> None:
        self.cwd = Path(tempfile.mkdtemp(prefix="hcg-docker-copy-"))
        (self.cwd / ".claude/transfers").mkdir(parents=True)
        hcg.APPROVAL_LOG = self.cwd / "audit.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self.cwd, ignore_errors=True)

    def contract(self, result: str = "PASS", performed: bool = True, host: str = "host1",
                 name: str = VOL) -> None:
        (self.cwd / ".claude/transfers/stands.json").write_text(json.dumps({
            "verification": {"performed": performed, "result": result},
            "verified_copies": [{"host": host, "kind": "volume", "name": name}]}), encoding="utf-8")

    def go(self, cmd: str = CMD, prompt: str = "да", answer: str = BLOCK) -> bool:
        return hcg._docker_rm_approval(hcg.docker_rm_targets(cmd), cmd, prompt, answer,
                                       {"cwd": str(self.cwd)})[0]

    def test_verified_copy_makes_it_replaceable(self) -> None:
        self.contract()
        self.assertTrue(self.go())
        self.assertIn("verified_copies", hcg.APPROVAL_LOG.read_text(encoding="utf-8"))

    def test_still_refused(self) -> None:
        self.assertFalse(self.go())                                   # no contract
        self.contract(result="FAIL")
        self.assertFalse(self.go())                                   # copy not verified
        self.contract(performed=False)
        self.assertFalse(self.go())
        self.contract(host="host2")
        self.assertFalse(self.go())                                   # copy of another host's volume
        self.contract(name="other-postgres")
        self.assertFalse(self.go())                                   # another volume
        self.contract()
        self.assertFalse(self.go(answer="Удалю том, подтверди"))     # still needs the block
        self.assertFalse(self.go(f"docker volume rm {VOL}"))          # local: no host to match


if __name__ == "__main__":
    unittest.main()
