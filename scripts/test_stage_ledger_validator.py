"""Unit tests for the proof-verify stage-ledger validator."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from copy import deepcopy
from pathlib import Path


VALIDATOR = Path(__file__).resolve().parent.parent / "skills" / "development" / "proof-verify" / "scripts" / "validate_stage_ledger.py"
SPEC = importlib.util.spec_from_file_location("validate_stage_ledger", VALIDATOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def digest(value: str) -> str:
    return value * 64


def sealed_stage() -> dict[str, object]:
    return {
        "id": "source",
        "status": "SEALED",
        "scope": ["src/source"],
        "contract_sha256": digest("a"),
        "source": {"commit": digest("b")[:40], "tree": digest("c")[:40]},
        "inputs": [{"name": "contract", "sha256": digest("d")}],
        "outputs": [{"name": "artifact", "sha256": digest("e")}],
        "fresh_verdict": {"status": "PASS", "path": ".proof/verdicts/source.md", "sha256": digest("f")},
        "invalidates_on": ["contract_sha256", "source.commit", "inputs[].sha256"],
    }


class StageLedgerValidatorTests(unittest.TestCase):
    def test_accepts_sealed_parent_and_blocked_child(self) -> None:
        parent = sealed_stage()
        child = {
            "id": "external-signer",
            "status": "BLOCKED",
            "scope": ["release/signer"],
            "blocked_on": [{"kind": "account", "name": "signer account"}],
            "requires": [{"stage": "source", "output_sha256": digest("e")}],
        }
        self.assertEqual(MODULE.validate({"schema_version": 1, "stages": [parent, child]}), [])

    def test_rejects_downstream_of_unsealed_parent(self) -> None:
        parent = sealed_stage()
        parent["status"] = "VERIFIED"
        child = {
            "id": "child",
            "status": "BLOCKED",
            "scope": ["release/child"],
            "blocked_on": [{"kind": "host", "name": "build host"}],
            "requires": [{"stage": "source", "output_sha256": digest("e")}],
        }
        errors = MODULE.validate({"schema_version": 1, "stages": [parent, child]})
        self.assertTrue(any("SEALED parent" in error for error in errors), errors)

    def test_rejects_changed_parent_output_digest(self) -> None:
        parent = sealed_stage()
        child = {
            "id": "child",
            "status": "BLOCKED",
            "scope": ["release/child"],
            "blocked_on": [{"kind": "host", "name": "build host"}],
            "requires": [{"stage": "source", "output_sha256": digest("0")}],
        }
        errors = MODULE.validate({"schema_version": 1, "stages": [parent, child]})
        self.assertTrue(any("not an output" in error for error in errors), errors)

    def test_rejects_sealed_stage_without_invalidation_keys(self) -> None:
        stage = deepcopy(sealed_stage())
        stage["invalidates_on"] = ["source.commit"]
        errors = MODULE.validate({"schema_version": 1, "stages": [stage]})
        self.assertTrue(any("invalidates_on" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
