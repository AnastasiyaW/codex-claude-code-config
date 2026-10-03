"""Regression: receipt mappings cannot become foreign Stop blockers."""
import importlib.util
import json
import os
import pathlib
import tempfile

HOOK = pathlib.Path(os.environ.get("TRANSFER_GUARD", pathlib.Path(__file__).resolve().parents[1] / "transfer-contract-guard.py"))
spec = importlib.util.spec_from_file_location("transfer_guard", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    name = "photo-optics-unified-layers-delivery-20261001.json"
    write_json(root / ".claude" / "transfers" / name, {
        "schema_version": 1, "transfer_id": "real", "status": "running",
        "source": "source", "destination": "destination", "purpose": "real transfer",
        "motivation": "proof", "deadline": "2026-10-03T23:59:59+02:00",
        "operation": {"kind": "copy", "tool": "cp", "settings": "bounded"},
        "verification": {"plan": ["hash"], "performed": False, "result": "PENDING", "evidence": []},
        "source_cleanup": {"planned": False, "performed": False, "verified": False},
        "session_id": "photo-optics-owner", "next_action": "verify"
    })
    write_json(root / ".agent" / "transfers" / name, {
        "record_kind": "receipt_mapping", "transfer_id": "mapping", "status": "not-a-contract"
    })
    issues, deferred = guard._stop_issues(root, "unrelated-session")
    assert not issues, issues
    assert any("owner session photo-optics-owner" in item for item in deferred), deferred

    # The exemption is not a generic escape for malformed transfer JSON.
    write_json(root / ".agent" / "transfers" / name, {"transfer_id": "unmarked"})
    issues, _ = guard._stop_issues(root, "unrelated-session")
    assert any("schema_version must be 1" in item for item in issues), issues

print("PASS explicit receipt mapping is skipped; unmarked malformed JSON blocks")
