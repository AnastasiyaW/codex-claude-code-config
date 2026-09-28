"""A new reconciliation registration binds its owner session to the evidence."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path


HOOKS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("controller", HOOKS / "task-cycle-controller.py")
controller = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(controller)

with tempfile.TemporaryDirectory(prefix="reconciliation-owner-") as raw:
    task = Path(raw)
    evidence = task / "evidence"
    evidence.mkdir()
    (task / "state.json").write_text(json.dumps({"task_id": "case"}), encoding="utf-8")
    (evidence / "satisfied.txt").write_text("proof", encoding="utf-8")
    (evidence / "boundary.txt").write_text("boundary", encoding="utf-8")
    observation = {
        "schema": "agent-reconciliation-observation/v1",
        "scope_id": "scope",
        "desired_state": "verified state",
        "observed_at": "2026-09-28T00:00:00Z",
        "items": [{
            "item_id": "item",
            "state": "SATISFIED",
            "satisfaction_receipt": "evidence/satisfied.txt",
        }],
    }
    (evidence / "reconciliation-case.json").write_text(json.dumps(observation), encoding="utf-8")
    previous = os.environ.get("CLAUDE_SESSION_ID")
    os.environ["CLAUDE_SESSION_ID"] = "owner-session"
    try:
        controller.register_reconciliation_gap(
            task, "case", "evidence/reconciliation-case.json", "evidence/boundary.txt"
        )
    finally:
        if previous is None:
            os.environ.pop("CLAUDE_SESSION_ID", None)
        else:
            os.environ["CLAUDE_SESSION_ID"] = previous
    receipt = json.loads((evidence / "reconciliation-case-registration.json").read_text(encoding="utf-8"))
    assert receipt["owner_session_id"] == "owner-session", receipt

print("reconciliation owner stamp PASS")
