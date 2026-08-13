#!/usr/bin/env python3
"""Validate the minimal immutable-stage ledger used by proof-verify."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DIGEST = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
GIT_OBJECT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$", re.IGNORECASE)
STATUSES = {"VERIFIED", "SEALED", "BLOCKED", "SUPERSEDED"}
SEALED_INVALIDATORS = {"contract_sha256", "source.commit", "inputs[].sha256"}


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(DIGEST.fullmatch(value))


def is_git_object(value: Any) -> bool:
    return isinstance(value, str) and bool(GIT_OBJECT.fullmatch(value))


def digest_entries(value: Any, label: str, errors: list[str]) -> set[str]:
    if not isinstance(value, list) or not value:
        errors.append(f"{label} must be a non-empty list")
        return set()
    result: set[str] = set()
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not is_digest(entry.get("sha256")):
            errors.append(f"{label}[{index}] needs name and sha256")
            continue
        result.add(entry["sha256"].lower())
    return result


def validate(ledger: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1:
        return ["schema_version must be 1"]
    stages = ledger.get("stages")
    if not isinstance(stages, list) or not stages:
        return ["stages must be a non-empty list"]

    by_id: dict[str, dict[str, Any]] = {}
    for index, stage in enumerate(stages):
        prefix = f"stages[{index}]"
        if not isinstance(stage, dict):
            errors.append(f"{prefix} must be an object")
            continue
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif stage_id in by_id:
            errors.append(f"duplicate stage id: {stage_id}")
        else:
            by_id[stage_id] = stage
        if stage.get("status") not in STATUSES:
            errors.append(f"{prefix}.status must be one of {sorted(STATUSES)}")
        if not isinstance(stage.get("scope"), list) or not all(isinstance(item, str) and item for item in stage["scope"]):
            errors.append(f"{prefix}.scope must be a non-empty list of strings")

    sealed_outputs: dict[str, set[str]] = {}
    for stage_id, stage in by_id.items():
        prefix = f"stage {stage_id}"
        status = stage.get("status")
        if status in {"VERIFIED", "SEALED"}:
            if not is_digest(stage.get("contract_sha256")):
                errors.append(f"{prefix}.contract_sha256 must be a SHA-256 digest")
            source = stage.get("source")
            if not isinstance(source, dict) or not is_git_object(source.get("commit")) or not is_git_object(source.get("tree")):
                errors.append(f"{prefix}.source needs immutable commit and tree IDs")
            digest_entries(stage.get("inputs"), f"{prefix}.inputs", errors)
            outputs = digest_entries(stage.get("outputs"), f"{prefix}.outputs", errors)
            verdict = stage.get("fresh_verdict")
            if not isinstance(verdict, dict) or verdict.get("status") != "PASS" or not isinstance(verdict.get("path"), str) or not is_digest(verdict.get("sha256")):
                errors.append(f"{prefix}.fresh_verdict needs PASS, path, and sha256")
            if status == "SEALED":
                invalidators = set(stage.get("invalidates_on", [])) if isinstance(stage.get("invalidates_on"), list) else set()
                missing = SEALED_INVALIDATORS - invalidators
                if missing:
                    errors.append(f"{prefix}.invalidates_on missing {sorted(missing)}")
                sealed_outputs[stage_id] = outputs
        elif status == "BLOCKED":
            blocked_on = stage.get("blocked_on")
            if not isinstance(blocked_on, list) or not blocked_on:
                errors.append(f"{prefix}.blocked_on must name the missing prerequisite")
            else:
                for index, blocker in enumerate(blocked_on):
                    if not isinstance(blocker, dict) or not isinstance(blocker.get("kind"), str) or not isinstance(blocker.get("name"), str):
                        errors.append(f"{prefix}.blocked_on[{index}] needs kind and name")
        elif status == "SUPERSEDED":
            successor = stage.get("superseded_by")
            if not isinstance(successor, str) or not successor:
                errors.append(f"{prefix}.superseded_by must name a successor stage")

    for stage_id, stage in by_id.items():
        if stage.get("status") == "SUPERSEDED" and stage.get("superseded_by") not in by_id:
            errors.append(f"stage {stage_id}.superseded_by does not exist")
        requires = stage.get("requires", [])
        if not isinstance(requires, list):
            errors.append(f"stage {stage_id}.requires must be a list")
            continue
        for index, requirement in enumerate(requires):
            label = f"stage {stage_id}.requires[{index}]"
            if not isinstance(requirement, dict) or not isinstance(requirement.get("stage"), str) or not is_digest(requirement.get("output_sha256")):
                errors.append(f"{label} needs stage and output_sha256")
                continue
            parent = requirement["stage"]
            output = requirement["output_sha256"].lower()
            if parent not in sealed_outputs:
                errors.append(f"{label} must reference a SEALED parent stage")
            elif output not in sealed_outputs[parent]:
                errors.append(f"{label}.output_sha256 is not an output of {parent}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", nargs="?", type=Path, default=Path(".proof/stage-ledger.json"))
    args = parser.parse_args()
    try:
        ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"STAGE LEDGER: FAIL - {exc}")
        return 2
    errors = validate(ledger)
    if errors:
        print("STAGE LEDGER: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"STAGE LEDGER: PASS ({len(ledger['stages'])} stages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
