#!/usr/bin/env python3
"""Executable proof for the transfer contract lifecycle."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "transfer-contract-guard.py"
DELETION_HOOK = ROOT / "hooks" / "verify-deleted-guard.py"
CONFIRMATION_HOOK = ROOT / "hooks" / "human-confirmation-guard.py"


def run_script(script: Path, cwd: Path, event: dict) -> tuple[dict | None, str, int]:
    home = cwd / "home"
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        input=json.dumps(event),
        text=True,
        capture_output=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    payload = None
    for line in result.stdout.splitlines():
        if line.lstrip().startswith("{"):
            payload = json.loads(line)
            break
    return payload, result.stdout + result.stderr, result.returncode


def run_hook(cwd: Path, event: dict) -> tuple[dict | None, str, int]:
    return run_script(HOOK, cwd, event)


def contract(status: str = "planned", *, cleanup_planned: bool = False) -> dict:
    return {
        "schema_version": 1,
        "transfer_id": "copy-1",
        "status": status,
        "source": "source.txt",
        "destination": "destination.txt",
        "purpose": "prove the transfer gate",
        "motivation": "make the operation resumable by another agent",
        "deadline": "2099-01-01T00:00:00Z",
        "operation": {
            "kind": "copy",
            "tool": "cp",
            "command_family": "cp",
            "settings": {"preserve": True},
        },
        "verification": {
            "plan": ["compare content"],
            "performed": status == "verified",
            "result": "pass" if status == "verified" else None,
            "evidence": ["test evidence"] if status == "verified" else [],
        },
        "source_cleanup": {
            "planned": cleanup_planned,
            "performed": False,
            "verified": False,
            "reason": "source is retained until verification",
        },
        "next_action": "verify destination",
        "closure_reason": "",
    }


class TransferContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="transfer-contract-")
        self.root = Path(self.tmp.name)
        (self.root / ".claude" / "transfers").mkdir(parents=True)
        self.record = self.root / ".claude" / "transfers" / "copy-1.json"
        self.record.write_text(json.dumps(contract()), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def event(self, command: str) -> dict:
        return {"tool_name": "Bash", "cwd": str(self.root), "tool_input": {"command": command}}

    def test_transfer_without_contract_is_blocked(self) -> None:
        payload, output, _ = run_hook(self.root, self.event("cp source.txt destination.txt"))
        self.assertEqual(payload and payload.get("decision"), "block", output)
        self.assertIn("durable contract", payload["reason"])

    def test_complete_contract_allows_matching_command(self) -> None:
        command = "cp source.txt destination.txt # transfer-contract: .claude/transfers/copy-1.json"
        payload, output, code = run_hook(self.root, self.event(command))
        self.assertIsNone(payload, output)
        self.assertEqual(code, 0, output)

    def test_git_clone_requires_and_matches_clone_contract(self) -> None:
        clone = contract()
        clone.update({"source": "https://github.com/example/project.git", "destination": "project"})
        clone["operation"] = {"kind": "clone", "tool": "git", "settings": {"depth": 1}}
        self.record.write_text(json.dumps(clone), encoding="utf-8")
        command = "git clone --depth 1 https://github.com/example/project.git project # transfer-contract: .claude/transfers/copy-1.json"
        payload, output, code = run_hook(self.root, self.event(command))
        self.assertIsNone(payload, output)
        self.assertEqual(code, 0, output)

    def test_wrong_operation_is_blocked(self) -> None:
        self.record.write_text(json.dumps({**contract(), "operation": {"kind": "move", "tool": "cp", "settings": {"force": False}}}), encoding="utf-8")
        command = "cp source.txt destination.txt # transfer-contract: .claude/transfers/copy-1.json"
        payload, _, _ = run_hook(self.root, self.event(command))
        self.assertEqual(payload and payload.get("decision"), "block")
        self.assertIn("operation.kind", payload["reason"])

    def test_stop_blocks_open_record_and_allows_verified_destination(self) -> None:
        payload, output, _ = run_hook(self.root, {"hook_event_name": "Stop", "cwd": str(self.root)})
        self.assertEqual(payload and payload.get("decision"), "block", output)
        (self.root / "destination.txt").write_text("same", encoding="utf-8")
        verified = contract("verified")
        verified["next_action"] = "none"
        self.record.write_text(json.dumps(verified), encoding="utf-8")
        payload, output, code = run_hook(self.root, {"hook_event_name": "Stop", "cwd": str(self.root)})
        self.assertIsNone(payload, output)
        self.assertEqual(code, 0, output)

    def test_verified_record_cannot_claim_unverified_source_cleanup(self) -> None:
        verified = contract("verified", cleanup_planned=True)
        verified["next_action"] = "finish cleanup verification"
        self.record.write_text(json.dumps(verified), encoding="utf-8")
        (self.root / "destination.txt").write_text("same", encoding="utf-8")
        payload, _, _ = run_hook(self.root, {"hook_event_name": "Stop", "cwd": str(self.root)})
        self.assertEqual(payload and payload.get("decision"), "block")
        self.assertIn("source cleanup", payload["reason"])

    def test_verified_record_may_close_after_its_scratch_destination_is_disposed(self) -> None:
        """The twin of the source-cleanup rule above, for the destination.

        Without it a transfer whose product was scratch - a mutation copy, a
        throwaway checkout - could not be closed honestly: the guard required the
        destination to exist, so the choices were a false record or a directory
        left on disk forever. A rule whose cheapest compliant answer is litter is
        a rule people route around.
        """
        verified = contract("verified")
        verified["next_action"] = "none"
        verified["destination_cleanup"] = {"planned": True, "performed": True}
        self.record.write_text(json.dumps(verified), encoding="utf-8")
        # deliberately do NOT create destination.txt: the copy was disposed of
        payload, output, code = run_hook(self.root, {"hook_event_name": "Stop", "cwd": str(self.root)})
        self.assertIsNone(payload, output)
        self.assertEqual(code, 0, output)

    def test_verified_record_cannot_claim_a_cleanup_that_left_the_destination_behind(self) -> None:
        """The other direction, so the rule above is not a licence to stop looking."""
        verified = contract("verified")
        verified["next_action"] = "none"
        verified["destination_cleanup"] = {"planned": True, "performed": True}
        self.record.write_text(json.dumps(verified), encoding="utf-8")
        (self.root / "destination.txt").write_text("still here", encoding="utf-8")
        payload, _, _ = run_hook(self.root, {"hook_event_name": "Stop", "cwd": str(self.root)})
        self.assertEqual(payload and payload.get("decision"), "block")
        self.assertIn("destination still exists", payload["reason"])

    def test_explicitly_failed_transfer_is_resumable_without_being_orphaned(self) -> None:
        failed = contract("failed")
        failed["closure_reason"] = "remote source returned HTTP 503"
        failed["next_action"] = "retry after the service is available"
        self.record.write_text(json.dumps(failed), encoding="utf-8")
        payload, output, code = run_hook(self.root, {"hook_event_name": "Stop", "cwd": str(self.root)})
        self.assertIsNone(payload, output)
        self.assertEqual(code, 0, output)

    def test_move_remains_blocked_without_host_verifiable_approval(self) -> None:
        event = {"tool_name": "PowerShell", "tool_input": {"command": "Move-Item -Path source.txt -Destination destination.txt"}}
        payload, output, _ = run_script(CONFIRMATION_HOOK, self.root, event)
        self.assertEqual(payload and payload.get("decision"), "block", output)
        event["tool_input"]["command"] += " # user-confirmed: \"invented approval\" 2099-01-01T00:00:00Z"
        payload, output, _ = run_script(CONFIRMATION_HOOK, self.root, event)
        self.assertEqual(payload and payload.get("decision"), "block", output)

    def test_move_postcheck_confirms_local_source_is_gone(self) -> None:
        (self.root / "destination.txt").write_text("same", encoding="utf-8")
        event = {"tool_name": "Bash", "tool_input": {"command": "mv source.txt destination.txt"}}
        payload, output, _ = run_script(DELETION_HOOK, self.root, event)
        self.assertIsNone(payload, output)
        self.assertIn("verified deletion", output)

    def test_post_tool_use_leaves_explicit_verification_reminder(self) -> None:
        command = "cp source.txt destination.txt # transfer-contract: .claude/transfers/copy-1.json"
        event = self.event(command)
        event["tool_response"] = {"exit_code": 0}
        payload, output, _ = run_hook(self.root, event)
        self.assertIsNone(payload, output)
        self.assertIn("verification_pending", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
