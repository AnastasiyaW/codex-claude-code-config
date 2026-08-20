#!/usr/bin/env python3
"""Turn verified findings into durable, schedulable work orders.

An agent saying "what remains" is not a scheduler.  This controller owns the
small deterministic part of the loop:

    evaluator finding -> work order -> focused proof -> fresh review -> accepted

It deliberately accepts structured findings only.  Regexing an arbitrary chat
message into an infrastructure change would be a new guessing failure.  A
heartbeat calls ``reconcile`` then ``next`` on every wake; the JSON response is
the current focus, rather than a stale prose list embedded in the heartbeat.

All durable files live below one task directory:

* ``findings.json`` is the evaluator/coordinator input;
* ``cycle.json`` is the controller-owned state and work queue;
* evidence paths named by ``record-proof`` must already exist below the task.

The script has no network or shell execution capability.  It schedules and
validates evidence transitions; the heartbeat or worker executes the named
focused test/runtime proof and stores its real output first.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "agent-task-cycle/v1"
FINDINGS_SCHEMA = "agent-task-findings/v1"
INTERNAL = "INTERNAL_FIXABLE"
EXTERNAL = "EXTERNAL_REQUIRED"
VALID_CLASSIFICATIONS = {INTERNAL, EXTERNAL}
ACTIVE = {"READY", "IN_PROGRESS", "TESTING", "RUNTIME_PROOF", "REVIEWING"}
TERMINAL = {"ACCEPTED", "ESCALATED"}
MAX_FAILED_PROOFS = 3
REQUIRED_PROOF_ORDER = ["focused_test", "runtime_proof", "independent_review"]
FROZEN_KEYS = (
    "classification",
    "accepted_requirement",
    "boundary",
    "next_action",
    "proof_requirements",
    "proof_plan",
)


class CycleError(ValueError):
    """A malformed contract must be visible, never silently treated as idle."""


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise CycleError(f"{field} must be a non-empty UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CycleError(f"{field} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise CycleError(f"{field} must include a timezone: {value!r}")
    return parsed.astimezone(dt.timezone.utc)


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CycleError(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CycleError(f"cannot parse {label} {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CycleError(f"{label} must be a JSON object: {path}")
    return data


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CycleError(f"{field} must be a non-empty string")
    return value.strip()


def string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CycleError(f"{field} must be a non-empty list")
    result = [nonempty_string(item, f"{field}[]") for item in value]
    if len(set(result)) != len(result):
        raise CycleError(f"{field} must not repeat proof names")
    return result


def validate_finding(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CycleError("each finding must be an object")
    finding = dict(raw)
    finding["finding_id"] = nonempty_string(finding.get("finding_id"), "finding_id")
    classification = nonempty_string(finding.get("classification"), "classification")
    if classification not in VALID_CLASSIFICATIONS:
        raise CycleError(f"{finding['finding_id']}: classification must be one of {sorted(VALID_CLASSIFICATIONS)}")
    finding["classification"] = classification
    finding["accepted_requirement"] = nonempty_string(
        finding.get("accepted_requirement"), f"{finding['finding_id']}.accepted_requirement"
    )
    finding["boundary"] = nonempty_string(finding.get("boundary"), f"{finding['finding_id']}.boundary")
    finding["next_action"] = nonempty_string(finding.get("next_action"), f"{finding['finding_id']}.next_action")

    if classification == INTERNAL:
        requirements = string_list(finding.get("proof_requirements"), f"{finding['finding_id']}.proof_requirements")
        if requirements != REQUIRED_PROOF_ORDER:
            raise CycleError(
                f"{finding['finding_id']}: INTERNAL_FIXABLE proof_requirements must be "
                f"{REQUIRED_PROOF_ORDER!r} in this exact order"
            )
        plan = finding.get("proof_plan")
        if not isinstance(plan, dict):
            raise CycleError(f"{finding['finding_id']}.proof_plan must be an object")
        normalized_plan = {}
        for proof in requirements:
            normalized_plan[proof] = nonempty_string(plan.get(proof), f"{finding['finding_id']}.proof_plan.{proof}")
        finding["proof_requirements"] = requirements
        finding["proof_plan"] = normalized_plan
        for key in ("blocker", "last_checked_at", "next_check_at"):
            finding.pop(key, None)
    else:
        finding["blocker"] = nonempty_string(finding.get("blocker"), f"{finding['finding_id']}.blocker")
        checked = parse_utc(finding.get("last_checked_at"), f"{finding['finding_id']}.last_checked_at")
        next_check = parse_utc(finding.get("next_check_at"), f"{finding['finding_id']}.next_check_at")
        if next_check <= checked:
            raise CycleError(f"{finding['finding_id']}.next_check_at must be after last_checked_at")
        finding["last_checked_at"] = checked.isoformat().replace("+00:00", "Z")
        finding["next_check_at"] = next_check.isoformat().replace("+00:00", "Z")
        finding["last_check_evidence"] = nonempty_string(
            finding.get("last_check_evidence"), f"{finding['finding_id']}.last_check_evidence"
        )
        finding["proof_requirements"] = []
        finding["proof_plan"] = {}
    return finding


def findings_path(task_dir: Path) -> Path:
    return task_dir / "findings.json"


def cycle_path(task_dir: Path) -> Path:
    return task_dir / "cycle.json"


def task_id(task_dir: Path) -> str:
    state_path = task_dir / "state.json"
    if not state_path.exists():
        return task_dir.name
    state = load_json(state_path, "state.json")
    return nonempty_string(state.get("task_id"), "state.json.task_id")


def empty_cycle(task_dir: Path) -> dict[str, Any]:
    return {"schema": SCHEMA, "task_id": task_id(task_dir), "work_orders": [], "updated_at": now_utc()}


def load_cycle(task_dir: Path, required: bool = True) -> dict[str, Any]:
    path = cycle_path(task_dir)
    if not path.exists() and not required:
        return empty_cycle(task_dir)
    cycle = load_json(path, "cycle.json")
    if cycle.get("schema") != SCHEMA:
        raise CycleError(f"cycle.json.schema must equal {SCHEMA!r}")
    nonempty_string(cycle.get("task_id"), "cycle.json.task_id")
    if not isinstance(cycle.get("work_orders"), list):
        raise CycleError("cycle.json.work_orders must be a list")
    return cycle


def finding_contract(finding: dict[str, Any]) -> dict[str, Any]:
    return {key: finding.get(key) for key in FROZEN_KEYS}


def validate_order(order: Any) -> dict[str, Any]:
    if not isinstance(order, dict):
        raise CycleError("each work order must be an object")
    required = validate_finding(order)
    status = nonempty_string(order.get("status"), f"{required['finding_id']}.status")
    allowed = ACTIVE | TERMINAL | {"BLOCKED_EXTERNAL"}
    if status not in allowed:
        raise CycleError(f"{required['finding_id']}: unknown status {status!r}")
    if required["classification"] == EXTERNAL and status != "BLOCKED_EXTERNAL":
        raise CycleError(f"{required['finding_id']}: EXTERNAL_REQUIRED must stay BLOCKED_EXTERNAL")
    if required["classification"] == INTERNAL and status == "BLOCKED_EXTERNAL":
        raise CycleError(f"{required['finding_id']}: INTERNAL_FIXABLE cannot be BLOCKED_EXTERNAL")
    proofs = order.get("proofs", {})
    if not isinstance(proofs, dict):
        raise CycleError(f"{required['finding_id']}.proofs must be an object")
    attempts = order.get("attempts", 0)
    if not isinstance(attempts, int) or attempts < 0:
        raise CycleError(f"{required['finding_id']}.attempts must be a non-negative integer")
    if status == "ACCEPTED":
        for proof in required["proof_requirements"]:
            record = proofs.get(proof)
            if not isinstance(record, dict) or record.get("result") != "PASS":
                raise CycleError(f"{required['finding_id']}: ACCEPTED is missing PASS evidence for {proof}")
        review = proofs.get("independent_review")
        if isinstance(review, dict) and (not review.get("fresh_context") or not review.get("reviewer")):
            raise CycleError(f"{required['finding_id']}: ACCEPTED requires a named fresh independent review")
    order = dict(order)
    order.update(required)
    order["status"] = status
    order["proofs"] = proofs
    order["attempts"] = attempts
    return order


def reconcile(task_dir: Path) -> dict[str, Any]:
    input_data = load_json(findings_path(task_dir), "findings.json")
    if input_data.get("schema") != FINDINGS_SCHEMA:
        raise CycleError(f"findings.json.schema must equal {FINDINGS_SCHEMA!r}")
    incoming = input_data.get("findings")
    if not isinstance(incoming, list):
        raise CycleError("findings.json.findings must be a list")
    normalized = [validate_finding(row) for row in incoming]
    ids = [row["finding_id"] for row in normalized]
    if len(ids) != len(set(ids)):
        raise CycleError("findings.json has duplicate finding_id values")

    cycle = load_cycle(task_dir, required=False)
    existing: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(cycle["work_orders"]):
        order = validate_order(raw)
        fid = order["finding_id"]
        if fid in existing:
            raise CycleError(f"cycle.json has duplicate finding_id {fid!r}")
        existing[fid] = order
        cycle["work_orders"][index] = order

    created: list[str] = []
    for finding in normalized:
        old = existing.get(finding["finding_id"])
        if old is None:
            order = dict(finding)
            order.update({
                "status": "READY" if finding["classification"] == INTERNAL else "BLOCKED_EXTERNAL",
                "attempts": 0,
                "proofs": {},
                "created_at": now_utc(),
            })
            cycle["work_orders"].append(order)
            created.append(finding["finding_id"])
            continue
        if finding_contract(old) != finding_contract(finding):
            raise CycleError(
                f"{finding['finding_id']}: accepted contract changed; create a new finding_id for a new causal boundary"
            )
        # An evaluator finding may be reconciled repeatedly.  It must not be
        # able to make an overdue external check disappear by merely editing a
        # timestamp in the input file; ``record-external-check`` owns that
        # transition and requires a new receipt on disk.

    cycle["updated_at"] = now_utc()
    validate_evidence_files(task_dir, cycle)
    write_json_atomic(cycle_path(task_dir), cycle)
    return {"decision": "RECONCILED", "created": created, "work_orders": len(cycle["work_orders"])}


def evidence_path(task_dir: Path, supplied: str) -> str:
    relative = Path(nonempty_string(supplied, "evidence"))
    if relative.is_absolute():
        raise CycleError("evidence must be a relative path below the task directory")
    resolved_task = task_dir.resolve()
    resolved = (task_dir / relative).resolve()
    try:
        resolved.relative_to(resolved_task)
    except ValueError as exc:
        raise CycleError("evidence path escapes the task directory") from exc
    if not resolved.is_file():
        raise CycleError(f"evidence file does not exist: {relative.as_posix()}")
    return relative.as_posix()


def validate_evidence_files(task_dir: Path, cycle: dict[str, Any]) -> None:
    """Do not let a hand-edited queue point to evidence that is not on disk."""
    for raw in cycle["work_orders"]:
        order = validate_order(raw)
        if order["classification"] == EXTERNAL:
            evidence_path(task_dir, order.get("last_check_evidence"))
        for proof, record in order["proofs"].items():
            if isinstance(record, dict) and record.get("result") == "PASS":
                evidence_path(task_dir, record.get("evidence"))
        migration = order.get("legacy_action_migration")
        if migration is not None:
            if not isinstance(migration, dict):
                raise CycleError(f"{order['finding_id']}.legacy_action_migration must be an object")
            evidence_path(task_dir, migration.get("evidence"))


def find_order(cycle: dict[str, Any], finding_id: str) -> dict[str, Any]:
    for index, raw in enumerate(cycle["work_orders"]):
        order = validate_order(raw)
        if order["finding_id"] == finding_id:
            cycle["work_orders"][index] = order
            return order
    raise CycleError(f"unknown finding_id {finding_id!r}")


def migrate_legacy_action(
    task_dir: Path, finding_id: str, original_action: str, evidence: str,
) -> dict[str, Any]:
    """Receipt-bind a one-time repair of the pre-v1 overwritten-action shape.

    This is deliberately not part of ``reconcile`` or the heartbeat: without
    a stored original action, an automatic migration cannot distinguish it
    from an evaluator changing the contract.  The caller must name the action
    currently in findings.json and supply a durable migration receipt.
    """
    input_data = load_json(findings_path(task_dir), "findings.json")
    if input_data.get("schema") != FINDINGS_SCHEMA or not isinstance(input_data.get("findings"), list):
        raise CycleError("findings.json is not a valid task finding document")
    incoming = [validate_finding(row) for row in input_data["findings"]]
    finding = next((row for row in incoming if row["finding_id"] == finding_id), None)
    if finding is None:
        raise CycleError(f"{finding_id}: not present in findings.json")
    action = nonempty_string(original_action, "--original-action")
    if action != finding["next_action"]:
        raise CycleError("--original-action must equal the current findings.json next_action")

    cycle = load_cycle(task_dir)
    validate_evidence_files(task_dir, cycle)
    order = find_order(cycle, finding_id)
    failure = order.get("last_failure")
    if not isinstance(failure, dict) or order.get("next_action") != failure.get("next_action"):
        raise CycleError(f"{finding_id}: no receipt-bound legacy overwritten-action state to migrate")
    receipt = evidence_path(task_dir, evidence)
    order["next_action"] = action
    order["legacy_action_migration"] = {
        "evidence": receipt,
        "original_action": action,
        "migrated_at": now_utc(),
    }
    cycle["updated_at"] = now_utc()
    validate_evidence_files(task_dir, cycle)
    write_json_atomic(cycle_path(task_dir), cycle)
    return select_next(cycle)


def pending_proofs(order: dict[str, Any]) -> list[str]:
    pending = []
    for proof in order["proof_requirements"]:
        record = order["proofs"].get(proof)
        if not isinstance(record, dict) or record.get("result") != "PASS":
            pending.append(proof)
    return pending


def next_status(order: dict[str, Any]) -> str:
    pending = pending_proofs(order)
    if not pending:
        return "ACCEPTED"
    if "independent_review" in pending and len(pending) == 1:
        return "REVIEWING"
    if "runtime_proof" in pending:
        return "RUNTIME_PROOF"
    if "focused_test" in pending:
        return "TESTING"
    return "IN_PROGRESS"


def record_proof(
    task_dir: Path,
    finding_id: str,
    proof: str,
    result: str,
    evidence: str,
    reviewer: str | None,
    fresh_context: bool,
    next_action: str | None,
    causal_boundary: str | None,
) -> dict[str, Any]:
    if result not in {"PASS", "FAIL"}:
        raise CycleError("result must be PASS or FAIL")
    cycle = load_cycle(task_dir)
    validate_evidence_files(task_dir, cycle)
    order = find_order(cycle, finding_id)
    if order["classification"] != INTERNAL:
        raise CycleError(f"{finding_id}: external blockers do not accept proof records")
    if order["status"] in TERMINAL:
        raise CycleError(f"{finding_id}: terminal work order cannot accept new proof")
    if proof not in order["proof_requirements"]:
        raise CycleError(f"{finding_id}: {proof!r} is not a required proof")
    pending = pending_proofs(order)
    if not pending or proof != pending[0]:
        expected = pending[0] if pending else "no proof"
        raise CycleError(f"{finding_id}: proof order violation; expected {expected!r}, got {proof!r}")
    relative_evidence = evidence_path(task_dir, evidence)
    proof_record: dict[str, Any] = {"result": result, "evidence": relative_evidence, "recorded_at": now_utc()}
    if proof == "independent_review":
        proof_record["reviewer"] = nonempty_string(reviewer, "reviewer")
        if not fresh_context:
            raise CycleError("independent_review requires --fresh-context")
        proof_record["fresh_context"] = True
    if result == "FAIL":
        failure_action = nonempty_string(next_action, "--next-action after a failed proof")
        failure_boundary = nonempty_string(causal_boundary, "--causal-boundary after a failed proof")
        order["attempts"] += 1
        # Any failed proof means the implementation changed before the next
        # attempt.  Earlier green output and a prior fresh review no longer
        # bind that new implementation, so start a fresh proof epoch.
        order["proofs"] = {}
        order["last_failure"] = {
            "proof": proof,
            "evidence": relative_evidence,
            "causal_boundary": failure_boundary,
            "next_action": failure_action,
            "recorded_at": now_utc(),
        }
        order["status"] = "ESCALATED" if order["attempts"] >= MAX_FAILED_PROOFS else "READY"
    else:
        order["proofs"][proof] = proof_record
        order["status"] = next_status(order)
    cycle["updated_at"] = now_utc()
    validate_evidence_files(task_dir, cycle)
    write_json_atomic(cycle_path(task_dir), cycle)
    return select_next(cycle)


def record_external_check(
    task_dir: Path,
    finding_id: str,
    evidence: str,
    next_check_at: str,
    blocker: str | None,
) -> dict[str, Any]:
    """Atomically receipt-bind one real external recheck before re-scheduling it."""
    cycle = load_cycle(task_dir)
    validate_evidence_files(task_dir, cycle)
    order = find_order(cycle, finding_id)
    if order["classification"] != EXTERNAL:
        raise CycleError(f"{finding_id}: only EXTERNAL_REQUIRED work can record an external check")
    checked = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    next_check = parse_utc(next_check_at, "--next-check-at")
    if next_check <= checked:
        raise CycleError("--next-check-at must be after the new external check")
    receipt = evidence_path(task_dir, evidence)
    checked_text = checked.isoformat().replace("+00:00", "Z")
    order["last_checked_at"] = checked_text
    order["next_check_at"] = next_check.isoformat().replace("+00:00", "Z")
    order["last_check_evidence"] = receipt
    if blocker is not None:
        order["blocker"] = nonempty_string(blocker, "--blocker")
    checks = order.setdefault("external_checks", [])
    if not isinstance(checks, list):
        raise CycleError(f"{finding_id}.external_checks must be a list")
    checks.append({"checked_at": checked_text, "next_check_at": order["next_check_at"], "evidence": receipt})
    cycle["updated_at"] = now_utc()
    validate_evidence_files(task_dir, cycle)
    write_json_atomic(cycle_path(task_dir), cycle)
    return select_next(cycle)


def select_next(cycle: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    current = now or dt.datetime.now(dt.timezone.utc)
    orders = [validate_order(order) for order in cycle["work_orders"]]
    escalated = [order for order in orders if order["status"] == "ESCALATED"]
    if escalated:
        return {
            "decision": "ESCALATED",
            "finding_id": escalated[0]["finding_id"],
            "boundary": escalated[0].get("last_failure", {}).get("causal_boundary", escalated[0]["boundary"]),
            "next_action": escalated[0].get("last_failure", {}).get("next_action", escalated[0]["next_action"]),
        }
    active = [order for order in orders if order["status"] in ACTIVE]
    if active:
        order = active[0]
        pending = pending_proofs(order)
        proof = pending[0] if pending else None
        failure = order.get("last_failure") if isinstance(order.get("last_failure"), dict) else {}
        return {
            "decision": "WORK",
            "finding_id": order["finding_id"],
            "status": order["status"],
            "boundary": failure.get("causal_boundary", order["boundary"]),
            "next_action": failure.get("next_action", order["next_action"]),
            "next_proof": proof,
            "proof_instruction": order["proof_plan"].get(proof) if proof else None,
        }
    external = [order for order in orders if order["status"] == "BLOCKED_EXTERNAL"]
    overdue = [order for order in external if parse_utc(order["next_check_at"], "next_check_at") <= current]
    if overdue:
        order = overdue[0]
        return {
            "decision": "RECHECK_EXTERNAL",
            "finding_id": order["finding_id"],
            "boundary": order["boundary"],
            "blocker": order["blocker"],
            "last_checked_at": order["last_checked_at"],
            "next_check_at": order["next_check_at"],
            "next_action": order["next_action"],
        }
    if external:
        return {
            "decision": "WAIT_EXTERNAL",
            "blockers": [
                {"finding_id": order["finding_id"], "next_check_at": order["next_check_at"], "blocker": order["blocker"]}
                for order in external
            ],
        }
    return {"decision": "ACCEPTED", "task_id": cycle["task_id"]}


def print_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    decision = result["decision"]
    print(f"DECISION: {decision}")
    for key in ("finding_id", "status", "boundary", "next_action", "next_proof", "proof_instruction", "blocker", "next_check_at"):
        if result.get(key):
            print(f"{key}: {result[key]}")
    if decision == "WAIT_EXTERNAL":
        for blocker in result["blockers"]:
            print(f"{blocker['finding_id']}: next check {blocker['next_check_at']} — {blocker['blocker']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("reconcile", "next", "validate"):
        command = sub.add_parser(name)
        command.add_argument("--task-dir", type=Path, required=True)
        command.add_argument("--json", action="store_true")
    proof = sub.add_parser("record-proof")
    proof.add_argument("--task-dir", type=Path, required=True)
    proof.add_argument("--finding", required=True)
    proof.add_argument("--proof", required=True)
    proof.add_argument("--result", required=True, choices=("PASS", "FAIL"))
    proof.add_argument("--evidence", required=True)
    proof.add_argument("--reviewer")
    proof.add_argument("--fresh-context", action="store_true")
    proof.add_argument("--next-action")
    proof.add_argument("--causal-boundary")
    proof.add_argument("--json", action="store_true")
    external = sub.add_parser("record-external-check")
    external.add_argument("--task-dir", type=Path, required=True)
    external.add_argument("--finding", required=True)
    external.add_argument("--evidence", required=True)
    external.add_argument("--next-check-at", required=True)
    external.add_argument("--blocker")
    external.add_argument("--json", action="store_true")
    legacy = sub.add_parser("migrate-legacy-action")
    legacy.add_argument("--task-dir", type=Path, required=True)
    legacy.add_argument("--finding", required=True)
    legacy.add_argument("--original-action", required=True)
    legacy.add_argument("--evidence", required=True)
    legacy.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        task_dir = args.task_dir.resolve()
        if not task_dir.is_dir():
            raise CycleError(f"task directory does not exist: {task_dir}")
        if args.command == "reconcile":
            result = reconcile(task_dir)
        elif args.command == "next":
            cycle = load_cycle(task_dir)
            validate_evidence_files(task_dir, cycle)
            result = select_next(cycle)
        elif args.command == "validate":
            cycle = load_cycle(task_dir)
            validate_evidence_files(task_dir, cycle)
            result = {"decision": "VALID", "work_orders": len(cycle["work_orders"])}
        elif args.command == "record-proof":
            result = record_proof(
                task_dir, args.finding, args.proof, args.result, args.evidence,
                args.reviewer, args.fresh_context, args.next_action, args.causal_boundary,
            )
        elif args.command == "migrate-legacy-action":
            result = migrate_legacy_action(task_dir, args.finding, args.original_action, args.evidence)
        else:
            result = record_external_check(
                task_dir, args.finding, args.evidence, args.next_check_at, args.blocker,
            )
    except CycleError as exc:
        print(f"task-cycle: FAIL: {exc}", file=sys.stderr)
        return 2
    print_result(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
