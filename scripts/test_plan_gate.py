"""Focused behavioral tests for the non-blocking planning and stage-contract nudge."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).resolve().parent.parent / "hooks" / "plan-gate.py"
SPEC = importlib.util.spec_from_file_location("plan_gate", HOOK)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PlanGateTests(unittest.TestCase):
    def run_hook(self, root: Path, prompt: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["TEMP"] = str(root / "temp")
        return subprocess.run(
            [sys.executable, str(HOOK)],
            cwd=root,
            input=json.dumps({"user_prompt": prompt}),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_generic_docs_and_claude_directory_are_not_a_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs").mkdir()
            (root / ".claude").mkdir()
            self.assertFalse(MODULE.has_plan_artifact(root))
            result = self.run_hook(root, "Build a new service")
            self.assertIn("no PLAN.md", result.stdout)

    def test_plan_file_suppresses_generic_reminder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "PLAN.md").write_text("# plan", encoding="utf-8")
            self.assertTrue(MODULE.has_plan_artifact(root))
            result = self.run_hook(root, "Build a new service")
            self.assertEqual(result.stdout, "")

    def test_multistage_work_requests_stage_ledger_even_with_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "PLAN.md").write_text("# plan", encoding="utf-8")
            result = self.run_hook(root, "Implement a release pipeline with an external signer")
            self.assertIn("stage-ledger.json", result.stdout)
            self.assertIn("BLOCKED", result.stdout)

    def test_existing_stage_ledger_suppresses_stage_reminder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "PLAN.md").write_text("# plan", encoding="utf-8")
            ledger = root / ".proof" / "stage-ledger.json"
            ledger.parent.mkdir()
            ledger.write_text("{}", encoding="utf-8")
            result = self.run_hook(root, "Implement a release pipeline with an external signer")
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
