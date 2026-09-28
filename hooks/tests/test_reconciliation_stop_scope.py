"""Regression: foreign reconciliation records must not block another session."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path


HOOKS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("task_guard", HOOKS / "user-task-completion-guard.py")
guard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(guard)


def make_observation(root: Path, owner: str | None) -> Path:
    evidence = root / ".agent" / "tasks" / "case" / "evidence"
    evidence.mkdir(parents=True)
    observation = evidence / "reconciliation-case.json"
    observation.write_text("{}", encoding="utf-8")
    if owner is not None:
        registration = {
            "schema": guard.RECONCILIATION_REGISTRATION_SCHEMA,
            "observation_evidence": "evidence/reconciliation-case.json",
            "observation_sha256": hashlib.sha256(observation.read_bytes()).hexdigest(),
            "owner_session_id": owner,
        }
        (evidence / "reconciliation-case-registration.json").write_text(
            json.dumps(registration), encoding="utf-8"
        )
    return observation


original_assess = guard.assess_reconciliation_observation
guard.assess_reconciliation_observation = lambda *_: "broken controller receipt"
try:
    with tempfile.TemporaryDirectory(prefix="reconciliation-stop-scope-") as raw:
        root = Path(raw)
        make_observation(root, "other-session")
        issues, deferred = guard.assess_reconciliation_observations(root, "my-session")
        assert not issues and deferred, (issues, deferred)

    with tempfile.TemporaryDirectory(prefix="reconciliation-stop-scope-") as raw:
        root = Path(raw)
        make_observation(root, "my-session")
        issues, deferred = guard.assess_reconciliation_observations(root, "my-session")
        assert issues and not deferred, (issues, deferred)

    with tempfile.TemporaryDirectory(prefix="reconciliation-stop-scope-") as raw:
        root = Path(raw)
        make_observation(root, None)
        issues, deferred = guard.assess_reconciliation_observations(root, "my-session")
        assert not issues and deferred, (issues, deferred)

    with tempfile.TemporaryDirectory(prefix="reconciliation-stop-scope-") as raw:
        root = Path(raw)
        observation = make_observation(root, "my-session")
        registration_path = observation.with_name("reconciliation-case-registration.json")
        registration = json.loads(registration_path.read_text(encoding="utf-8"))
        registration["observation_sha256"] = "0" * 64
        registration_path.write_text(json.dumps(registration), encoding="utf-8")
        issues, deferred = guard.assess_reconciliation_observations(root, "my-session")
        assert not issues and deferred, (issues, deferred)
finally:
    guard.assess_reconciliation_observation = original_assess

print("reconciliation Stop scope PASS")
