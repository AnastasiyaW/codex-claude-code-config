#!/usr/bin/env python3
"""Executable contract for durable, evidence-bound user tasks."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
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

    def test_action_request_creates_a_durable_project_task(self) -> None:
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

    def test_other_session_is_not_wedged_and_session_start_surfaces_open_work(self) -> None:
        self.invoke_prompt()
        self.assertIsNone(self.invoke_stop("session-b"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.session_start({}, self.root), 0)
        self.assertIn("Open durable user tasks", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
