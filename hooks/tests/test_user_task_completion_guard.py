#!/usr/bin/env python3
"""Executable contract for durable, evidence-bound user tasks."""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path


HOOK = Path(__file__).resolve().parents[1] / "user-task-completion-guard.py"
SPEC = importlib.util.spec_from_file_location("user_task_completion_guard", HOOK)
guard = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(guard)


class UserTaskCompletionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="user-task-completion-guard-")
        self.root = Path(self.tmp.name) / "repo"
        (self.root / ".git").mkdir(parents=True)
        self.event = {"prompt": "проверь и исправь обвязку", "session_id": "session-a"}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def invoke_prompt(self, event: dict | None = None) -> dict | None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.user_prompt(event or self.event, self.root), 0)
        return json.loads(output.getvalue()) if output.getvalue().strip() else None

    def invoke_stop(self, session: str = "session-a") -> dict | None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.stop({"session_id": session}, self.root), 0)
        return json.loads(output.getvalue()) if output.getvalue().strip() else None

    def request(self) -> dict:
        requests = list((self.root / ".agent" / "user-tasks").glob("*/request.json"))
        self.assertEqual(len(requests), 1)
        return json.loads(requests[0].read_text(encoding="utf-8"))

    def state_path(self) -> Path:
        request = self.request()
        return self.root / ".agent" / "user-tasks" / request["task_id"] / "state.json"

    def write_state(self, **changes: object) -> Path:
        path = self.state_path()
        state = json.loads(path.read_text(encoding="utf-8"))
        state.update(changes)
        path.write_text(json.dumps(state), encoding="utf-8")
        return path

    def receipt(self, name: str = "evidence/proof.txt") -> str:
        path = self.state_path().parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("real receipt\n", encoding="utf-8")
        return name

    def reconciliation_observation(self, classification: str = "INTERNAL_FIXABLE") -> tuple[Path, Path, dict]:
        task = self.root / ".agent" / "tasks" / "release-rollout"
        evidence = task / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "bootstrap-published.json").write_text("published\n", encoding="utf-8")
        unresolved = {
            "item_id": "signature",
            "state": classification,
            "boundary": "signature missing",
            "next_action": "sign it",
        }
        if classification == "EXTERNAL_REQUIRED":
            next_check = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(
                microsecond=0
            ).isoformat().replace("+00:00", "Z")
            unresolved.update({
                "blocker": "signer is unavailable",
                "next_check_at": next_check,
            })
        observation = {
            "schema": guard.RECONCILIATION_OBSERVATION_SCHEMA,
            "scope_id": "release-rollout",
            "desired_state": "every required artifact is verified and published",
            "observed_at": "2026-09-01T10:00:00Z",
            "items": [
                {"item_id": "bootstrap", "state": "SATISFIED", "satisfaction_receipt": "evidence/bootstrap-published.json"},
                unresolved,
            ],
        }
        path = evidence / "reconciliation-observation.json"
        path.write_text(json.dumps(observation), encoding="utf-8")
        return task, path, observation

    def register_observation(self, task: Path, observation_path: Path, observation: dict) -> dict:
        item = next(raw for raw in observation["items"] if raw["state"] != "SATISFIED")
        finding_id = f"RECONCILE-release-rollout-20260901-{item['item_id']}"
        finding = {
            "finding_id": finding_id,
            "classification": item["state"],
            "accepted_requirement": "the release rollout must reach its desired state",
            "boundary": item["boundary"],
            "next_action": item["next_action"],
        }
        if item["state"] == "INTERNAL_FIXABLE":
            finding.update({
                "proof_requirements": list(guard.REQUIRED_PROOF_ORDER),
                "proof_plan": {
                    "focused_test": "run the focused signing test",
                    "runtime_proof": "verify the signed artifact",
                    "independent_review": "fresh reviewer checks the receipt",
                },
            })
        else:
            finding.update({
                "blocker": item["blocker"],
                "last_checked_at": observation["observed_at"],
                "next_check_at": item["next_check_at"],
                "last_check_evidence": "evidence/external-check.txt",
                "proof_requirements": [],
                "proof_plan": {},
            })
        (task / "findings.json").write_text(json.dumps({
            "schema": "agent-task-findings/v1",
            "findings": [finding],
        }), encoding="utf-8")
        registration = {
            "schema": guard.RECONCILIATION_REGISTRATION_SCHEMA,
            "batch_id": "release-rollout-20260901",
            "observation_evidence": observation_path.relative_to(task).as_posix(),
            "observation_sha256": hashlib.sha256(observation_path.read_bytes()).hexdigest(),
            "registered_findings": [finding_id],
        }
        registration_path = task / "evidence" / "reconciliation-release-rollout-20260901-registration.json"
        registration_path.write_text(json.dumps(registration), encoding="utf-8")
        return finding

    def complete_active_request(self) -> None:
        evidence = self.receipt()
        self.write_state(status="COMPLETE", result="gap repaired", evidence=[evidence])

    def test_action_request_creates_a_durable_project_task(self) -> None:
        self.assertEqual(guard.classify_prompt("разверни webhook"), ("request", True))
        self.assertEqual(guard.classify_prompt("deploy the webhook"), ("request", True))
        payload = self.invoke_prompt()
        self.assertIn("[user-task]", payload["hookSpecificOutput"]["additionalContext"])
        request = self.request()
        self.assertEqual(request["schema"], guard.REQUEST_SCHEMA)
        self.assertEqual(request["kind"], "request")
        self.assertFalse(request["requires_inventory"])
        self.assertEqual(self.invoke_stop()["decision"], "block")

    def test_question_does_not_create_or_block_a_task(self) -> None:
        self.assertEqual(guard.classify_prompt("почему завис компьютер?"), ("note", False))
        self.assertIsNone(self.invoke_prompt({"prompt": "почему завис компьютер?", "session_id": "session-a"}))
        self.assertFalse((self.root / ".agent" / "user-tasks").exists())
        self.assertIsNone(self.invoke_stop())

    def test_explicit_machine_opt_out_does_not_record_its_instruction_prompt(self) -> None:
        with mock.patch.dict(guard.os.environ, {guard.TASK_CAPTURE_ENV: "0"}):
            self.assertIsNone(self.invoke_prompt())
        self.assertFalse((self.root / ".agent" / "user-tasks").exists())

    def test_complete_requires_existing_evidence_and_result(self) -> None:
        self.invoke_prompt()
        self.write_state(status="COMPLETE", result="обвязка проверена", evidence=["evidence/missing.txt"])
        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("does not exist", blocked["reason"])
        evidence = self.receipt()
        self.write_state(status="COMPLETE", result="обвязка проверена", evidence=[evidence])
        self.assertIsNone(self.invoke_stop())
        receipt = json.loads((self.state_path().parent / "terminal-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema"], guard.TERMINAL_RECEIPT_SCHEMA)
        self.assertEqual(receipt["outcome"], "COMPLETE")

    def test_external_blocker_requires_receipt_and_named_recheck(self) -> None:
        self.invoke_prompt()
        evidence = self.receipt()
        self.write_state(status="BLOCKED_EXTERNAL", evidence=[evidence], blocker="VM is unavailable", recheck="after VM access returns")
        self.assertIsNone(self.invoke_stop())

    def test_collection_cannot_close_after_one_item(self) -> None:
        event = {"prompt": "обсчитай все чекпоинты", "session_id": "session-a"}
        self.invoke_prompt(event)
        request = self.request()
        self.assertTrue(request["requires_inventory"])
        first = self.receipt("evidence/250.txt")
        self.write_state(status="COMPLETE", items=[
            {"item_id": "250", "status": "PASS", "evidence": [first]},
            {"item_id": "500", "status": "PENDING"},
        ])
        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("1/2 collection items terminal", blocked["reason"])

    def test_collection_closes_with_every_receipt_or_measured_blocker(self) -> None:
        event = {"prompt": "check all checkpoints", "session_id": "session-a"}
        self.invoke_prompt(event)
        first = self.receipt("evidence/250.txt")
        second = self.receipt("evidence/500.txt")
        self.write_state(status="BLOCKED_EXTERNAL", items=[
            {"item_id": "250", "status": "PASS", "evidence": [first]},
            {"item_id": "500", "status": "BLOCKED_EXTERNAL", "evidence": [second], "blocker": "artifact unavailable", "recheck": "after artifact receipt"},
        ])
        self.assertIsNone(self.invoke_stop())

    def test_collection_cannot_close_complete_without_a_result(self) -> None:
        """Every item receipted still says nothing about the outcome.

        The collection branch returned before state.result was read, so this shape
        closed green while answering none of the request.
        """
        event = {"prompt": "check all checkpoints", "session_id": "session-a"}
        self.invoke_prompt(event)
        first = self.receipt("evidence/250.txt")
        self.write_state(status="COMPLETE", result="   ", items=[
            {"item_id": "250", "status": "PASS", "evidence": [first]},
        ])
        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("state.result", blocked["reason"])

        self.write_state(status="COMPLETE", result="every checkpoint measured; two passed",
                         items=[{"item_id": "250", "status": "PASS", "evidence": [first]}])
        self.assertIsNone(self.invoke_stop())

    def test_registration_without_terminal_cycle_still_blocks(self) -> None:
        self.invoke_prompt()
        self.complete_active_request()
        task, observation_path, observation = self.reconciliation_observation()

        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("has no controller registration receipt", blocked["reason"])

        finding = self.register_observation(task, observation_path, observation)
        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("missing cycle.json", blocked["reason"])

        cycle_path = task / "cycle.json"
        cycle = {
            "schema": guard.CYCLE_SCHEMA,
            "task_id": "release-rollout",
            "work_orders": [{
                **finding,
                "status": "READY",
                "attempts": 0,
                "proofs": {},
            }],
        }
        cycle_path.write_text(json.dumps(cycle), encoding="utf-8")
        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("not ACCEPTED", blocked["reason"])

        cycle["work_orders"][0]["next_action"] = "stale replacement action"
        cycle_path.write_text(json.dumps(cycle), encoding="utf-8")
        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("work order is stale", blocked["reason"])

    def test_accepted_internal_reconciliation_allows_stop(self) -> None:
        self.invoke_prompt()
        self.complete_active_request()
        task, observation_path, observation = self.reconciliation_observation()
        finding = self.register_observation(task, observation_path, observation)
        proof_records = {}
        for proof in guard.REQUIRED_PROOF_ORDER:
            proof_path = task / "evidence" / f"{proof}.txt"
            proof_path.write_text(f"{proof} passed\n", encoding="utf-8")
            proof_records[proof] = {
                "result": "PASS",
                "evidence": proof_path.relative_to(task).as_posix(),
            }
        proof_records["independent_review"].update({
            "reviewer": "fresh-reviewer",
            "fresh_context": True,
        })
        (task / "cycle.json").write_text(json.dumps({
            "schema": guard.CYCLE_SCHEMA,
            "task_id": "release-rollout",
            "work_orders": [{
                **finding,
                "status": "ACCEPTED",
                "attempts": 0,
                "proofs": proof_records,
            }],
        }), encoding="utf-8")

        self.assertIsNone(self.invoke_stop())

    def test_hand_written_nonlegacy_cycle_without_typed_receipts_blocks(self) -> None:
        self.invoke_prompt()
        self.complete_active_request()
        task, observation_path, observation = self.reconciliation_observation()
        finding = self.register_observation(task, observation_path, observation)
        proofs = {}
        for proof in guard.REQUIRED_PROOF_ORDER:
            proof_path = task / "evidence" / f"forged-{proof}.txt"
            proof_path.write_text("model-authored PASS claim\n", encoding="utf-8")
            proofs[proof] = {
                "result": "PASS",
                "evidence": proof_path.relative_to(task).as_posix(),
            }
        proofs["independent_review"].update({
            "reviewer": "invented-reviewer",
            "fresh_context": True,
        })
        (task / "cycle.json").write_text(json.dumps({
            "schema": guard.CYCLE_SCHEMA,
            "task_id": "release-rollout",
            "work_orders": [{
                **finding,
                "status": "ACCEPTED",
                "attempts": 0,
                "proofs": proofs,
                "created_at": "2026-09-01T10:00:00Z",
                "budget": {
                    "max_attempts": 3,
                    "max_tool_calls": 12,
                    "max_wall_time_seconds": 21600,
                    "started_at": "2026-09-01T10:00:00Z",
                    "tool_calls": 0,
                    "exhausted_reason": None,
                },
                "attempt_history": [],
            }],
        }), encoding="utf-8")

        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("canonical controller validation", blocked["reason"])
        self.assertIn("receipt", blocked["reason"])

    def test_current_external_reconciliation_allows_stop(self) -> None:
        self.invoke_prompt()
        self.complete_active_request()
        task, observation_path, observation = self.reconciliation_observation("EXTERNAL_REQUIRED")
        finding = self.register_observation(task, observation_path, observation)
        external_receipt = task / "evidence" / "external-check.txt"
        external_receipt.write_text("signer unavailable at the checked endpoint\n", encoding="utf-8")
        (task / "cycle.json").write_text(json.dumps({
            "schema": guard.CYCLE_SCHEMA,
            "task_id": "release-rollout",
            "work_orders": [{
                **finding,
                "status": "BLOCKED_EXTERNAL",
                "attempts": 0,
                "proofs": {},
            }],
        }), encoding="utf-8")

        self.assertIsNone(self.invoke_stop())

        cycle = json.loads((task / "cycle.json").read_text(encoding="utf-8"))
        cycle["work_orders"][0]["last_checked_at"] = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        cycle["work_orders"][0]["next_check_at"] = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        (task / "cycle.json").write_text(json.dumps(cycle), encoding="utf-8")
        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("run the named recheck", blocked["reason"])

    def test_other_session_is_not_wedged_and_session_start_surfaces_open_work(self) -> None:
        self.invoke_prompt()
        self.assertIsNone(self.invoke_stop("session-b"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.session_start({}, self.root), 0)
        self.assertIn("Open durable user tasks", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
