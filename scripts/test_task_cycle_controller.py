#!/usr/bin/env python3
"""Executable contracts for the task-cycle controller."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONTROLLER = ROOT / "scripts" / "task_cycle_controller.py"


def internal_finding(fid: str = "F-001") -> dict:
    return {
        "finding_id": fid,
        "classification": "INTERNAL_FIXABLE",
        "accepted_requirement": "AC1: current installer must not open a browser",
        "boundary": "server/release-admission",
        "next_action": "Write the red release-admission reproducer and repair it.",
        "proof_requirements": ["focused_test", "runtime_proof", "independent_review"],
        "proof_plan": {
            "focused_test": "pytest -q tests/test_release_admission.py",
            "runtime_proof": "Run the VM download-only process/URL trace and store it under evidence/.",
            "independent_review": "Fresh evaluator reviews the changed release-admission boundary.",
        },
    }


def external_finding(
    fid: str = "F-002",
    next_check: str = "2099-01-01T00:00:00Z",
    evidence: str = "evidence/external-check.txt",
) -> dict:
    last_checked = "1999-12-31T00:00:00Z" if next_check.startswith("2000-") else "2026-08-16T10:00:00Z"
    return {
        "finding_id": fid,
        "classification": "EXTERNAL_REQUIRED",
        "accepted_requirement": "AC2: a legitimate signing authority must exist",
        "boundary": "external signing authority",
        "next_action": "Re-read the signer receipt and update this finding.",
        "blocker": "No signer receipt exists.",
        "last_checked_at": last_checked,
        "next_check_at": next_check,
        "last_check_evidence": evidence,
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
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        payload = json.loads(result.stdout) if result.stdout.strip() else None
        return result.returncode, payload, result.stderr

    def reconcile(self) -> dict:
        code, payload, stderr = self.invoke("reconcile")
        self.assertEqual(code, 0, stderr)
        self.assertIsNotNone(payload)
        return payload or {}

    def test_reconcile_derives_exact_work_then_requires_test_runtime_and_fresh_review(self) -> None:
        self.evidence("external-check.txt")
        self.write_findings([internal_finding(), external_finding()])
        result = self.reconcile()
        self.assertEqual(result["created"], ["F-001", "F-002"])

        code, next_step, stderr = self.invoke("next")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(next_step and next_step["decision"], "WORK")
        self.assertEqual(next_step and next_step["finding_id"], "F-001")
        self.assertEqual(next_step and next_step["next_proof"], "focused_test")

        code, next_step, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test", "--result", "PASS",
            "--evidence", self.evidence("focused-test.txt"),
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(next_step and next_step["next_proof"], "runtime_proof")

        code, next_step, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "runtime_proof", "--result", "PASS",
            "--evidence", self.evidence("process-url-trace.json"),
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(next_step and next_step["status"], "REVIEWING")
        self.assertEqual(next_step and next_step["next_proof"], "independent_review")

        code, next_step, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "independent_review", "--result", "PASS",
            "--evidence", self.evidence("fresh-review.md"), "--reviewer", "fresh-evaluator-42", "--fresh-context",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(next_step and next_step["decision"], "WAIT_EXTERNAL")

        cycle = json.loads((self.task / "cycle.json").read_text(encoding="utf-8"))
        self.assertEqual(cycle["work_orders"][0]["status"], "ACCEPTED")
        self.assertEqual(cycle["work_orders"][0]["proofs"]["independent_review"]["fresh_context"], True)

    def test_failed_proof_requires_causal_requeue_and_escalates_after_budget(self) -> None:
        self.write_findings([internal_finding()])
        self.reconcile()
        evidence = self.evidence("failed-test.txt")

        code, _payload, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test", "--result", "FAIL", "--evidence", evidence,
        )
        self.assertEqual(code, 2)
        self.assertIn("--next-action", stderr)

        for expected_attempt in (1, 2):
            code, result, stderr = self.invoke(
                "record-proof", "--finding", "F-001", "--proof", "focused_test", "--result", "FAIL", "--evidence", evidence,
                "--next-action", "Repair the parser boundary before repeating the focused test.",
                "--causal-boundary", "parser rejects the signed version epoch",
            )
            self.assertEqual(code, 0, stderr)
            self.assertEqual(result and result["decision"], "WORK")
            cycle = json.loads((self.task / "cycle.json").read_text(encoding="utf-8"))
            self.assertEqual(cycle["work_orders"][0]["attempts"], expected_attempt)

        code, result, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test", "--result", "FAIL", "--evidence", evidence,
            "--next-action", "Escalate the parser ownership boundary.",
            "--causal-boundary", "parser rejects the signed version epoch",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["decision"], "ESCALATED")

    def test_external_blocker_is_rechecked_when_due_never_silently_waited(self) -> None:
        self.evidence("external-check.txt")
        self.write_findings([external_finding(next_check="2000-01-01T00:00:00Z")])
        self.reconcile()
        code, result, stderr = self.invoke("next")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["decision"], "RECHECK_EXTERNAL")
        self.assertEqual(result and result["finding_id"], "F-002")

        next_receipt = self.evidence("external-recheck.txt")
        code, result, stderr = self.invoke(
            "record-external-check", "--finding", "F-002", "--evidence", next_receipt,
            "--next-check-at", "2099-01-01T00:00:00Z",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(result and result["decision"], "WAIT_EXTERNAL")
        cycle = json.loads((self.task / "cycle.json").read_text(encoding="utf-8"))
        self.assertEqual(cycle["work_orders"][0]["last_check_evidence"], next_receipt)
        self.assertEqual(len(cycle["work_orders"][0]["external_checks"]), 1)

        # Editing the evaluator input afterwards cannot erase this receipt or
        # move the controller's next check by itself.
        self.write_findings([external_finding(next_check="2000-01-01T00:00:00Z")])
        self.reconcile()
        cycle_after = json.loads((self.task / "cycle.json").read_text(encoding="utf-8"))
        self.assertEqual(cycle_after["work_orders"][0]["last_check_evidence"], next_receipt)

    def test_contract_mutation_for_same_finding_is_rejected(self) -> None:
        finding = internal_finding()
        self.write_findings([finding])
        self.reconcile()
        finding["next_action"] = "A different causal boundary must use a new id."
        self.write_findings([finding])
        code, _payload, stderr = self.invoke("reconcile")
        self.assertEqual(code, 2)
        self.assertIn("new finding_id", stderr)

    def test_internal_contract_requires_runtime_and_the_defined_proof_order(self) -> None:
        without_runtime = internal_finding()
        without_runtime["proof_requirements"] = ["focused_test", "independent_review"]
        self.write_findings([without_runtime])
        code, _payload, stderr = self.invoke("reconcile")
        self.assertEqual(code, 2)
        self.assertIn("proof_requirements must be", stderr)

        reordered = internal_finding()
        reordered["proof_requirements"] = ["independent_review", "focused_test", "runtime_proof"]
        self.write_findings([reordered])
        code, _payload, stderr = self.invoke("reconcile")
        self.assertEqual(code, 2)
        self.assertIn("proof_requirements must be", stderr)

    def test_missing_evidence_cannot_be_recorded_as_a_pass(self) -> None:
        self.write_findings([internal_finding()])
        self.reconcile()
        code, _payload, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test", "--result", "PASS",
            "--evidence", "evidence/does-not-exist.txt",
        )
        self.assertEqual(code, 2)
        self.assertIn("evidence file does not exist", stderr)

    def test_hand_editing_accepted_without_all_proofs_is_rejected(self) -> None:
        self.write_findings([internal_finding()])
        self.reconcile()
        cycle_path = self.task / "cycle.json"
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        cycle["work_orders"][0]["status"] = "ACCEPTED"
        cycle_path.write_text(json.dumps(cycle), encoding="utf-8")
        code, _payload, stderr = self.invoke("next")
        self.assertEqual(code, 2)
        self.assertIn("ACCEPTED is missing PASS evidence", stderr)

    def test_proof_epoch_is_ordered_and_a_failure_invalidates_prior_review_epoch(self) -> None:
        self.write_findings([internal_finding()])
        self.reconcile()
        code, _payload, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "runtime_proof", "--result", "PASS",
            "--evidence", self.evidence("wrong-order.txt"),
        )
        self.assertEqual(code, 2)
        self.assertIn("proof order violation", stderr)

        code, _payload, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test", "--result", "PASS",
            "--evidence", self.evidence("green-focused.txt"),
        )
        self.assertEqual(code, 0, stderr)
        code, _payload, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "runtime_proof", "--result", "FAIL",
            "--evidence", self.evidence("failed-trace.txt"),
            "--next-action", "Repair the process tracing boundary before re-running it.",
            "--causal-boundary", "VM trace drops child-process ancestry",
        )
        self.assertEqual(code, 0, stderr)
        code, next_step, stderr = self.invoke("next")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(next_step and next_step["boundary"], "VM trace drops child-process ancestry")
        self.assertEqual(next_step and next_step["next_proof"], "focused_test")
        cycle = json.loads((self.task / "cycle.json").read_text(encoding="utf-8"))
        self.assertEqual(cycle["work_orders"][0]["proofs"], {})

    def test_preexisting_missing_evidence_blocks_later_transition(self) -> None:
        self.write_findings([internal_finding()])
        self.reconcile()
        first = self.evidence("first-green.txt")
        code, _payload, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "focused_test", "--result", "PASS", "--evidence", first,
        )
        self.assertEqual(code, 0, stderr)
        (self.task / first).unlink()
        code, _payload, stderr = self.invoke(
            "record-proof", "--finding", "F-001", "--proof", "runtime_proof", "--result", "PASS",
            "--evidence", self.evidence("trace-after-deleted-test.txt"),
        )
        self.assertEqual(code, 2)
        self.assertIn("evidence file does not exist", stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
