#!/usr/bin/env python3
"""Executable contract for explicit whole-set user requests."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).resolve().parents[1] / "batch-completion-guard.py"
SPEC = importlib.util.spec_from_file_location("batch_completion_guard", HOOK)
guard = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(guard)


class BatchCompletionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="batch-completion-guard-")
        self.root = Path(self.tmp.name) / "repo"
        (self.root / ".git").mkdir(parents=True)
        self.event = {"prompt": "обсчитай все чекпоинты", "session_id": "session-a"}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def invoke_prompt(self) -> dict:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.user_prompt(self.event, self.root), 0)
        return json.loads(output.getvalue())

    def invoke_stop(self, session: str = "session-a") -> dict | None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.stop({"session_id": session}, self.root), 0)
        return json.loads(output.getvalue()) if output.getvalue().strip() else None

    def request(self) -> dict:
        requests = list((self.root / ".agent" / "batches").glob("*/request.json"))
        self.assertEqual(len(requests), 1)
        return json.loads(requests[0].read_text(encoding="utf-8"))

    def manifest(self, items: list[dict]) -> Path:
        request = self.request()
        directory = self.root / ".agent" / "batches" / request["intent_id"]
        path = directory / "manifest.json"
        path.write_text(json.dumps({
            "schema": guard.MANIFEST_SCHEMA,
            "intent_id": request["intent_id"],
            "items": items,
        }), encoding="utf-8")
        return directory

    def receipt(self, directory: Path, name: str) -> str:
        (directory / name).write_text("real receipt\n", encoding="utf-8")
        return name

    def test_exact_whole_checkpoint_request_creates_durable_intent(self) -> None:
        payload = self.invoke_prompt()
        self.assertIn("batch-completion", payload["hookSpecificOutput"]["additionalContext"])
        request = self.request()
        self.assertEqual(request["schema"], guard.REQUEST_SCHEMA)
        self.assertEqual(request["status"], "ACTIVE")
        self.assertEqual(self.invoke_stop()["decision"], "block")

    def test_status_question_and_singular_action_do_not_create_batch(self) -> None:
        self.assertFalse(guard.is_batch_request("все чекпоинты уже готовы?"))
        self.assertFalse(guard.is_batch_request("проверь этот чекпоинт"))
        self.assertTrue(guard.is_batch_request("render all checkpoints"))

    def test_one_completed_item_cannot_close_inventory(self) -> None:
        self.invoke_prompt()
        directory = self.manifest([
            {"item_id": "250", "status": "PASS", "evidence": "250.txt"},
            {"item_id": "500", "status": "PENDING"},
        ])
        self.receipt(directory, "250.txt")
        blocked = self.invoke_stop()
        self.assertEqual(blocked and blocked.get("decision"), "block")
        self.assertIn("1/2 items terminal", blocked["reason"])

    def test_all_receipted_items_close_request(self) -> None:
        self.invoke_prompt()
        directory = self.manifest([
            {"item_id": "250", "status": "PASS", "evidence": "250.txt"},
            {"item_id": "500", "status": "PASS", "evidence": "500.txt"},
        ])
        self.receipt(directory, "250.txt")
        self.receipt(directory, "500.txt")
        self.assertIsNone(self.invoke_stop())
        self.assertEqual(self.request()["status"], "COMPLETE")

    def test_external_blocker_is_allowed_only_after_other_items_finish(self) -> None:
        self.invoke_prompt()
        directory = self.manifest([
            {"item_id": "250", "status": "PASS", "evidence": "250.txt"},
            {
                "item_id": "500", "status": "BLOCKED_EXTERNAL", "evidence": "500.txt",
                "blocker": "checkpoint artifact is unavailable", "recheck": "after artifact receipt",
            },
        ])
        self.receipt(directory, "250.txt")
        self.receipt(directory, "500.txt")
        self.assertIsNone(self.invoke_stop())
        self.assertEqual(self.request()["status"], "BLOCKED_EXTERNAL")

    def test_other_session_is_not_wedged_by_my_batch(self) -> None:
        self.invoke_prompt()
        self.assertIsNone(self.invoke_stop("session-b"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
