#!/usr/bin/env python3
"""End-to-end contracts for the scheduled task-cycle dispatcher."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT = ROOT / "scripts" / "task_cycle_heartbeat.py"
CONTROLLER = ROOT / "hooks" / "task-cycle-controller.py"


def internal_finding() -> dict:
    return {
        "finding_id": "F-001",
        "classification": "INTERNAL_FIXABLE",
        "accepted_requirement": "AC1: a diagnosed boundary gets three ordered proofs",
        "boundary": "release/admission",
        "next_action": "Run the focused release-admission test.",
        "proof_requirements": ["focused_test", "runtime_proof", "independent_review"],
        "proof_plan": {
            "focused_test": "pytest -q tests/test_release_admission.py",
            "runtime_proof": "capture the real process trace",
            "independent_review": "fresh evaluator reviews the causal diff",
        },
    }


def external_finding() -> dict:
    return {
        "finding_id": "F-002",
        "classification": "EXTERNAL_REQUIRED",
        "accepted_requirement": "AC2: an external receipt is rechecked when due",
        "boundary": "external signer",
        "next_action": "Re-read the signer receipt.",
        "blocker": "Signer has not published a receipt.",
        "last_checked_at": "2026-08-20T00:00:00Z",
        "next_check_at": "2099-01-01T00:00:00Z",
        "last_check_evidence": "evidence/last-check.txt",
    }


class TaskCycleHeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="task-cycle-heartbeat-")
        self.root = Path(self.tmp.name) / "tasks"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add_task(self, name: str, findings: list[dict]) -> Path:
        task = self.root / name
        (task / "evidence").mkdir(parents=True)
        (task / "findings.json").write_text(
            json.dumps({"schema": "agent-task-findings/v1", "findings": findings}), encoding="utf-8"
        )
        return task

    def invoke(self) -> tuple[int, dict | None, str]:
        result = subprocess.run(
            [sys.executable, str(HEARTBEAT), "--tasks-root", str(self.root),
             "--controller", str(CONTROLLER), "--json"],
            text=True, capture_output=True, encoding="utf-8", check=False,
        )
        return result.returncode, (json.loads(result.stdout) if result.stdout.strip() else None), result.stderr

    def test_internal_finding_becomes_exact_first_proof_and_persists_report(self) -> None:
        task = self.add_task("release", [internal_finding()])
        code, report, stderr = self.invoke()
        self.assertEqual(code, 0, stderr)
        self.assertEqual(report and report["next"]["task_dir"], "release")
        self.assertEqual(report and report["next"]["decision"]["decision"], "WORK")
        self.assertEqual(report and report["next"]["decision"]["next_proof"], "focused_test")
        self.assertTrue((task / "cycle.json").is_file())
        persisted = json.loads((self.root / "task-cycle-heartbeat.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["schema"], "task-cycle-heartbeat/v1")

    def test_future_external_finding_waits_and_unmanaged_directories_are_ignored(self) -> None:
        task = self.add_task("external", [external_finding()])
        (task / "evidence" / "last-check.txt").write_text("real prior receipt\n", encoding="utf-8")
        (self.root / "notes-only").mkdir()
        code, report, stderr = self.invoke()
        self.assertEqual(code, 0, stderr)
        self.assertIsNone(report and report["next"])
        self.assertEqual(report and report["tasks"][0]["task_dir"], "external")
        self.assertEqual(report and report["tasks"][0]["decision"]["decision"], "WAIT_EXTERNAL")
        self.assertTrue((task / "cycle.json").is_file())

    def test_missing_tasks_root_fails_closed(self) -> None:
        missing = self.root / "missing"
        result = subprocess.run(
            [sys.executable, str(HEARTBEAT), "--tasks-root", str(missing), "--json"],
            text=True, capture_output=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("tasks root does not exist", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
