#!/usr/bin/env python3
"""Executable contracts for the task-cycle controller."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "task-cycle-controller.py"


def internal_finding(fid: str = "F-001") -> dict:
    return {
        "finding_id": fid,
        "classification": "INTERNAL_FIXABLE",
        "accepted_requirement": "AC1: installer must not open a browser",
        "boundary": "server/release-admission",
        "next_action": "Write the red release-admission reproducer and repair it.",
        "proof_requirements": ["focused_test", "runtime_proof", "independent_review"],
        "proof_plan": {
            "focused_test": "pytest -q tests/test_release_admission.py",
            "runtime_proof": "Run the VM process/URL trace and store it under evidence/.",
            "independent_review": "Fresh evaluator reviews the changed boundary.",
        },
    }


def external_finding(next_check: str = "2099-01-01T00:00:00Z") -> dict:
    return {
        "finding_id": "F-002",
        "classification": "EXTERNAL_REQUIRED",
        "accepted_requirement": "AC2: signing authority must exist",
        "boundary": "external signing authority",
        "next_action": "Re-read the signer receipt and update this finding.",
        "blocker": "No signer receipt exists.",
        "last_checked_at": "1999-12-31T00:00:00Z",
        "next_check_at": next_check,
        "last_check_evidence": "evidence/external-check.txt",
    }


class TaskCycleControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="task-cycle-controller-")
        self.task = Path(self.tmp.name) / "task"
        self.task.mkdir()
        (self.task / "state.json").write_text(json.dumps({"task_id": "demo"}), encoding="utf-8")
        (self.task / "evidence").mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_findings(self, findings: list[dict]) -> None:
        (self.task / "findings.json").write_text(
            json.dumps({"schema": "agent-task-findings/v1", "findings": findings}), encoding="utf-8"
        )

    def evidence(self, name: str) -> str:
        path = self.task / "evidence" / name
        path.write_text(f"real {name} output\n", encoding="utf-8")
        return path.relative_to(self.task).as_posix()

    def invoke(self, *args: str) -> tuple[int, dict | None, str]:
        result = subprocess.run(
            [sys.executable, str(CONTROLLER), *args, "--task-dir", str(self.task), "--json"],
            text=True, capture_output=True, encoding="utf-8", check=False,
        )
        return result.returncode, (json.loads(result.stdout) if result.stdout.strip() else None), result.stderr

    def reconcile(self) -> dict:
        code, payload, stderr = self.invoke("reconcile")
        self.assertEqual(code, 0, stderr)
        return payload or {}

    def test_internal_work_requires_test_runtime_and_fresh_review_in_order(self) -> None:
        self.write_findings([internal_finding()])
        self.assertEqual(self.reconcile()["created"], ["F-001"])
        code, result, stderr = self.invoke("next")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["next_proof"], "focused_test")

        for proof, evidence in (
            ("focused_test", "focused.txt"),
            ("runtime_proof", "trace.json"),
        ):
            code, result, stderr = self.invoke(
                "record-proof", "--finding", "F-001", "--proof", proof,
                "--result", "PASS", "--evidence", self.evidence(evidence),
            )
            self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["next_proof"], "independent_review")
        code, result, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "independent_review",
            "--result", "PASS", "--evidence", self.evidence("review.md"),
            "--reviewer", "fresh-evaluator", "--fresh-context",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["decision"], "ACCEPTED")

    def test_failed_proof_needs_causal_requeue_then_escalates(self) -> None:
        self.write_findings([internal_finding()])
        self.reconcile()
        receipt = self.evidence("failed.txt")
        code, _result, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test",
            "--result", "FAIL", "--evidence", receipt,
        )
        self.assertEqual(code, 2)
        self.assertIn("--next-action", stderr)
        for attempt in (1, 2, 3):
            code, result, stderr = self.invoke(
                "record-proof", "--finding", "F-001", "--proof", "focused_test",
                "--result", "FAIL", "--evidence", receipt,
                "--next-action", "Repair the parser before repeating the test.",
                "--causal-boundary", "parser rejects the signed version epoch",
            )
            self.assertEqual(code, 0, stderr)
            self.assertEqual(result and result["decision"], "ESCALATED" if attempt == 3 else "WORK")

    def test_external_finding_is_rechecked_when_due(self) -> None:
        self.evidence("external-check.txt")
        self.write_findings([external_finding(next_check="2000-01-01T00:00:00Z")])
        self.reconcile()
        code, result, stderr = self.invoke("next")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["decision"], "RECHECK_EXTERNAL")
        code, result, stderr = self.invoke(
            "record-external-check", "--finding", "F-002",
            "--evidence", self.evidence("external-recheck.txt"),
            "--next-check-at", "2099-01-01T00:00:00Z",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["decision"], "WAIT_EXTERNAL")

    def test_contract_mutation_missing_evidence_and_wrong_order_are_rejected(self) -> None:
        finding = internal_finding()
        self.write_findings([finding])
        self.reconcile()
        code, _result, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "runtime_proof",
            "--result", "PASS", "--evidence", self.evidence("wrong-order.txt"),
        )
        self.assertEqual(code, 2)
        self.assertIn("proof order violation", stderr)
        code, _result, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test",
            "--result", "PASS", "--evidence", "evidence/missing.txt",
        )
        self.assertEqual(code, 2)
        self.assertIn("evidence file does not exist", stderr)
        finding["next_action"] = "A different causal boundary must use a new id."
        self.write_findings([finding])
        code, _result, stderr = self.invoke("reconcile")
        self.assertEqual(code, 2)
        self.assertIn("new finding_id", stderr)

    def test_failed_runtime_invalidates_the_old_proof_epoch_and_changes_focus(self) -> None:
        self.write_findings([internal_finding()])
        self.reconcile()
        code, _result, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test",
            "--result", "PASS", "--evidence", self.evidence("green-focused.txt"),
        )
        self.assertEqual(code, 0, stderr)
        code, _result, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "runtime_proof",
            "--result", "FAIL", "--evidence", self.evidence("failed-trace.txt"),
            "--next-action", "Repair the process tracing boundary before re-running it.",
            "--causal-boundary", "VM trace drops child-process ancestry",
        )
        self.assertEqual(code, 0, stderr)
        cycle_path = self.task / "cycle.json"
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        self.assertEqual(
            cycle["work_orders"][0]["next_action"],
            "Write the red release-admission reproducer and repair it.",
        )
        # A failed proof owns a repair action in its receipt. Reconciling the
        # unchanged evaluator finding keeps its frozen action while `next`
        # still returns the repair action.
        code, _result, stderr = self.invoke("reconcile")
        self.assertEqual(code, 0, stderr)
        # Existing cycles from the previous implementation have the failed
        # action in next_action. Reconcile must fail loud rather than guessing
        # whether the incoming evaluator action is the original contract.
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        cycle["work_orders"][0]["next_action"] = "Repair the process tracing boundary before re-running it."
        cycle_path.write_text(json.dumps(cycle), encoding="utf-8")
        code, _result, stderr = self.invoke("reconcile")
        self.assertEqual(code, 2)
        self.assertIn("new finding_id", stderr)
        code, _result, stderr = self.invoke(
            "migrate-legacy-action", "--finding", "F-001",
            "--original-action", "Write the red release-admission reproducer and repair it.",
            "--evidence", self.evidence("legacy-action-migration.txt"),
        )
        self.assertEqual(code, 0, stderr)
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        self.assertEqual(
            cycle["work_orders"][0]["next_action"],
            "Write the red release-admission reproducer and repair it.",
        )
        code, result, stderr = self.invoke("next")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["boundary"], "VM trace drops child-process ancestry")
        self.assertEqual(result and result["next_proof"], "focused_test")
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        self.assertEqual(cycle["work_orders"][0]["proofs"], {})

    def test_hand_edited_acceptance_without_evidence_is_rejected(self) -> None:
        self.write_findings([internal_finding()])
        self.reconcile()
        cycle_path = self.task / "cycle.json"
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        cycle["work_orders"][0]["status"] = "ACCEPTED"
        cycle_path.write_text(json.dumps(cycle), encoding="utf-8")
        code, _result, stderr = self.invoke("next")
        self.assertEqual(code, 2)
        self.assertIn("ACCEPTED is missing PASS evidence", stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
