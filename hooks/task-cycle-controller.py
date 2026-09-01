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
import hashlib
import json
import os
import re
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
TERMINAL = {"ACCEPTED", "ESCALATED", "BUDGET_EXHAUSTED"}
MAX_FAILED_PROOFS = 3
DEFAULT_MAX_TOOL_CALLS = 9
DEFAULT_MAX_WALL_TIME_SECONDS = 30 * 24 * 60 * 60
REQUIRED_PROOF_ORDER = ["focused_test", "runtime_proof", "independent_review"]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
PROOF_RECEIPT_SCHEMA = "agent-task-proof-receipt/v1"
RECONCILIATION_OBSERVATION_SCHEMA = "agent-reconciliation-observation/v1"
RECONCILIATION_COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
RECONCILIATION_SATISFIED = "SATISFIED"
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def string_sequence(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CycleError(f"{field} must be a non-empty list")
    return [nonempty_string(item, f"{field}[]") for item in value]


def default_budget(started_at: str) -> dict[str, Any]:
    return {
        "max_attempts": MAX_FAILED_PROOFS,
        "max_tool_calls": DEFAULT_MAX_TOOL_CALLS,
        "max_wall_time_seconds": DEFAULT_MAX_WALL_TIME_SECONDS,
        "started_at": started_at,
        "tool_calls": 0,
    }


def validate_budget(value: Any, started_at: str, finding_id: str) -> dict[str, Any]:
    budget = default_budget(started_at) if value is None else dict(value) if isinstance(value, dict) else None
    if budget is None:
        raise CycleError(f"{finding_id}.budget must be an object")
    for field in ("max_attempts", "max_tool_calls", "max_wall_time_seconds"):
        number = budget.get(field)
        if not isinstance(number, int) or number <= 0:
            raise CycleError(f"{finding_id}.budget.{field} must be a positive integer")
    tool_calls = budget.get("tool_calls", 0)
    if not isinstance(tool_calls, int) or tool_calls < 0:
        raise CycleError(f"{finding_id}.budget.tool_calls must be a non-negative integer")
    budget["tool_calls"] = tool_calls
    budget["started_at"] = parse_utc(
        budget.get("started_at", started_at), f"{finding_id}.budget.started_at"
    ).isoformat().replace("+00:00", "Z")
    exhausted_reason = budget.get("exhausted_reason")
    if exhausted_reason is not None:
        budget["exhausted_reason"] = nonempty_string(exhausted_reason, f"{finding_id}.budget.exhausted_reason")
    return budget


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
    legacy_terminal_proofs = order.get("legacy_terminal_proofs", False)
    if not isinstance(legacy_terminal_proofs, bool):
        raise CycleError(f"{required['finding_id']}.legacy_terminal_proofs must be boolean")
    legacy_untyped_shape = "budget" not in order and "attempt_history" not in order
    if legacy_untyped_shape and status == "ACCEPTED":
        # Compatibility is deliberately terminal-only. Orders accepted by the
        # pre-receipt controller remain readable, but this flag never permits a
        # new proof submission or an active order to advance without v1 receipts.
        legacy_terminal_proofs = True
    if legacy_terminal_proofs and status != "ACCEPTED":
        raise CycleError(f"{required['finding_id']}: legacy proof compatibility is ACCEPTED-only")
    proofs = order.get("proofs", {})
    if not isinstance(proofs, dict):
        raise CycleError(f"{required['finding_id']}.proofs must be an object")
    attempts = order.get("attempts", 0)
    if not isinstance(attempts, int) or attempts < 0:
        raise CycleError(f"{required['finding_id']}.attempts must be a non-negative integer")
    created_at = parse_utc(
        order.get("created_at", now_utc()), f"{required['finding_id']}.created_at"
    ).isoformat().replace("+00:00", "Z")
    budget = validate_budget(order.get("budget"), created_at, required["finding_id"])
    attempt_history = order.get("attempt_history", [])
    if not isinstance(attempt_history, list):
        raise CycleError(f"{required['finding_id']}.attempt_history must be a list")
    seen_attempts: set[str] = set()
    seen_receipts: set[str] = set()
    failed_attempts = 0
    for item in attempt_history:
        if not isinstance(item, dict):
            raise CycleError(f"{required['finding_id']}.attempt_history entries must be objects")
        attempt_id = nonempty_string(item.get("attempt_id"), f"{required['finding_id']}.attempt_history.attempt_id")
        if not ATTEMPT_ID_RE.fullmatch(attempt_id):
            raise CycleError(f"{required['finding_id']}: invalid attempt_id {attempt_id!r}")
        receipt_sha256 = nonempty_string(
            item.get("receipt_sha256"), f"{required['finding_id']}.attempt_history.receipt_sha256"
        )
        if not SHA256_RE.fullmatch(receipt_sha256):
            raise CycleError(f"{required['finding_id']}: invalid proof receipt SHA-256")
        if attempt_id in seen_attempts:
            raise CycleError(f"{required['finding_id']}: repeated attempt_id {attempt_id!r}")
        if receipt_sha256 in seen_receipts:
            raise CycleError(f"{required['finding_id']}: repeated proof receipt digest {receipt_sha256}")
        seen_attempts.add(attempt_id)
        seen_receipts.add(receipt_sha256)
        result = item.get("result")
        if result not in {"PASS", "FAIL"}:
            raise CycleError(f"{required['finding_id']}.attempt_history.result must be PASS or FAIL")
        if result == "FAIL":
            failed_attempts += 1
    if legacy_terminal_proofs:
        if attempt_history or budget["tool_calls"]:
            raise CycleError(f"{required['finding_id']}: legacy terminal proofs cannot mix with typed receipts")
    else:
        if attempts != failed_attempts:
            raise CycleError(f"{required['finding_id']}.attempts does not match typed FAIL receipts")
        if budget["tool_calls"] != len(attempt_history):
            raise CycleError(f"{required['finding_id']}.budget.tool_calls does not match typed proof receipts")
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
    order["created_at"] = created_at
    order["budget"] = budget
    order["attempt_history"] = attempt_history
    if legacy_terminal_proofs:
        order["legacy_terminal_proofs"] = True
    else:
        order.pop("legacy_terminal_proofs", None)
    if status == "BUDGET_EXHAUSTED" and not budget.get("exhausted_reason"):
        raise CycleError(f"{required['finding_id']}: BUDGET_EXHAUSTED needs budget.exhausted_reason")
    return order


def budget_exhaustion_reason(order: dict[str, Any], now: dt.datetime | None = None) -> str | None:
    if order["classification"] != INTERNAL or order["status"] not in ACTIVE:
        return None
    budget = order["budget"]
    if order["attempts"] >= budget["max_attempts"]:
        return "max_attempts"
    if budget["tool_calls"] >= budget["max_tool_calls"]:
        return "max_tool_calls"
    current = now or dt.datetime.now(dt.timezone.utc)
    started = parse_utc(budget["started_at"], f"{order['finding_id']}.budget.started_at")
    if (current - started).total_seconds() >= budget["max_wall_time_seconds"]:
        return "max_wall_time_seconds"
    return None


def refresh_budget_statuses(cycle: dict[str, Any], now: dt.datetime | None = None) -> list[str]:
    exhausted: list[str] = []
    for index, raw in enumerate(cycle["work_orders"]):
        order = validate_order(raw)
        reason = budget_exhaustion_reason(order, now)
        if reason is not None:
            order["status"] = "BUDGET_EXHAUSTED"
            order["budget"]["exhausted_reason"] = reason
            exhausted.append(order["finding_id"])
        cycle["work_orders"][index] = order
    return exhausted


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
            created_at = now_utc()
            order.update({
                "status": "READY" if finding["classification"] == INTERNAL else "BLOCKED_EXTERNAL",
                "attempts": 0,
                "attempt_history": [],
                "proofs": {},
                "created_at": created_at,
                "budget": default_budget(created_at),
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

    refresh_budget_statuses(cycle)
    cycle["updated_at"] = now_utc()
    validate_evidence_files(task_dir, cycle)
    write_json_atomic(cycle_path(task_dir), cycle)
    return {"decision": "RECONCILED", "created": created, "work_orders": len(cycle["work_orders"])}


def register_plan_drift(
    task_dir: Path,
    finding_id: str,
    plan_path: Path,
    source_path: Path,
    expected_sha256: str,
    output_root: Path,
    quiescence_evidence: str,
) -> dict[str, Any]:
    """Turn a measured, pre-launch plan/source mismatch into internal work.

    The automatic route is deliberately narrow: the plan must visibly pin the
    supplied digest, the source must now differ, a real no-process receipt must
    already be under ``evidence/``, and the declared output root must not exist.
    Once outputs exist, a successor plan can require migration or invalidation;
    this helper refuses to guess which one is safe.
    """
    finding_id = nonempty_string(finding_id, "--finding")
    expected = nonempty_string(expected_sha256, "--expected-sha256").lower()
    if not SHA256_RE.fullmatch(expected):
        raise CycleError("--expected-sha256 must be a lowercase SHA-256 digest")
    if not plan_path.is_file():
        raise CycleError(f"plan file does not exist: {plan_path}")
    if not source_path.is_file():
        raise CycleError(f"source file does not exist: {source_path}")
    plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
    if expected not in plan_text.lower():
        raise CycleError("plan does not contain the expected SHA-256 digest")
    actual = sha256_file(source_path)
    if actual == expected:
        raise CycleError("source SHA-256 matches the plan; no plan drift exists")
    quiescence_receipt = evidence_path(task_dir, quiescence_evidence)

    output_root_exists = output_root.exists()
    if output_root_exists:
        accepted_requirement = (
            "Existing outputs must not be silently invalidated while the plan and reviewed source disagree."
        )
        boundary = (
            f"plan/source digest drift: expected {expected}, observed {actual}; "
            f"output root exists: {output_root}"
        )
        next_action = (
            "Perform a read-only migration assessment for the existing outputs before choosing a successor plan."
        )
        proof_plan = {
            "focused_test": (
                "Inventory the existing output provenance and the exact old/new source diff; write a migration "
                "assessment that names the safe successor action and save it under evidence/."
            ),
            "runtime_proof": (
                "Run a no-mutation validation of the existing outputs and save a fresh process/output trace under evidence/."
            ),
            "independent_review": (
                "A fresh reviewer verifies the provenance inventory, migration assessment, source diff, and no-mutation trace."
            ),
        }
    else:
        accepted_requirement = (
            "The execution plan and receipt must pin the reviewed source SHA-256 before launch."
        )
        boundary = (
            f"plan/source digest drift: expected {expected}, observed {actual}; "
            f"output root is absent: {output_root}"
        )
        next_action = (
            "Create a successor plan and receipt for the reviewed source, then run its no-launch preflight."
        )
        proof_plan = {
            "focused_test": (
                "Review the exact old/new source diff, write a successor plan and receipt pinning "
                f"{actual}, then run its focused validator; save the receipt under evidence/."
            ),
            "runtime_proof": (
                "Run the successor plan's no-launch preflight and save a fresh process/output trace under evidence/."
            ),
            "independent_review": (
                "A fresh reviewer verifies the source diff, successor SHA, quiescence receipt, and no-launch trace."
            ),
        }

    finding = {
        "finding_id": finding_id,
        "classification": INTERNAL,
        "accepted_requirement": accepted_requirement,
        "boundary": boundary,
        "next_action": next_action,
        "proof_requirements": REQUIRED_PROOF_ORDER,
        "proof_plan": proof_plan,
    }
    validated = validate_finding(finding)
    input_path = findings_path(task_dir)
    if input_path.exists():
        input_data = load_json(input_path, "findings.json")
        if input_data.get("schema") != FINDINGS_SCHEMA or not isinstance(input_data.get("findings"), list):
            raise CycleError("findings.json is not a valid task finding document")
        findings = list(input_data["findings"])
    else:
        input_data = {"schema": FINDINGS_SCHEMA}
        findings = []
    if any(isinstance(item, dict) and item.get("finding_id") == finding_id for item in findings):
        raise CycleError(f"{finding_id}: finding already exists; do not overwrite its frozen contract")

    receipt_path = task_dir / "evidence" / f"{finding_id}-plan-drift.json"
    write_json_atomic(
        receipt_path,
        {
            "schema": "agent-plan-drift-receipt/v1",
            "finding_id": finding_id,
            "detected_at": now_utc(),
            "plan": str(plan_path.resolve()),
            "source": str(source_path.resolve()),
            "expected_sha256": expected,
            "actual_sha256": actual,
            "output_root": str(output_root.resolve()),
            "output_root_exists": output_root_exists,
            "quiescence_evidence": quiescence_receipt,
        },
    )
    findings.append(validated)
    input_data["findings"] = findings
    write_json_atomic(input_path, input_data)
    reconciled = reconcile(task_dir)
    decision = select_next(load_cycle(task_dir))
    decision["registered"] = finding_id
    decision["drift_evidence"] = receipt_path.relative_to(task_dir).as_posix()
    decision["reconciled"] = reconciled
    return decision


def register_reconciliation_gap(
    task_dir: Path,
    batch_id: str,
    observation_evidence: str,
    evidence: str,
) -> dict[str, Any]:
    """Turn any measured desired/actual gap into one work order per item.

    An observation is evidence, not a prose status update. Every declared item
    is either backed by a satisfaction receipt or receives an internal
    repair/external recheck order. The helper never performs the domain action:
    it creates the durable, individually receipted work that owns that action.
    """
    batch_id = nonempty_string(batch_id, "--batch").lower()
    if not RECONCILIATION_COMPONENT_RE.fullmatch(batch_id):
        raise CycleError("--batch must be a lowercase durable identifier")
    observation_relative = evidence_path(task_dir, observation_evidence)
    receipt_evidence = evidence_path(task_dir, evidence)
    observation_path = task_dir / observation_relative
    observation = load_json(observation_path, "reconciliation observation")
    if observation.get("schema") != RECONCILIATION_OBSERVATION_SCHEMA:
        raise CycleError(
            f"reconciliation observation.schema must equal {RECONCILIATION_OBSERVATION_SCHEMA!r}"
        )
    scope_id = nonempty_string(observation.get("scope_id"), "reconciliation observation.scope_id").lower()
    if not RECONCILIATION_COMPONENT_RE.fullmatch(scope_id):
        raise CycleError("reconciliation observation.scope_id must be a lowercase durable identifier")
    desired_state = nonempty_string(observation.get("desired_state"), "reconciliation observation.desired_state")
    observed_at = parse_utc(observation.get("observed_at"), "reconciliation observation.observed_at")
    items = observation.get("items")
    if not isinstance(items, list) or not items:
        raise CycleError("reconciliation observation.items must be a non-empty list")

    findings: list[dict[str, Any]] = []
    satisfied: list[str] = []
    satisfaction_receipts: dict[str, str] = {}
    item_ids: set[str] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise CycleError("each reconciliation observation item must be an object")
        item_id = nonempty_string(raw_item.get("item_id"), "reconciliation observation.items[].item_id").lower()
        if not RECONCILIATION_COMPONENT_RE.fullmatch(item_id):
            raise CycleError("reconciliation observation item_id must be a lowercase durable identifier")
        if item_id in item_ids:
            raise CycleError(f"reconciliation observation repeats item_id {item_id!r}")
        item_ids.add(item_id)
        state = nonempty_string(raw_item.get("state"), f"{item_id}.state")
        if state == RECONCILIATION_SATISFIED:
            satisfaction_receipts[item_id] = evidence_path(
                task_dir,
                nonempty_string(raw_item.get("satisfaction_receipt"), f"{item_id}.satisfaction_receipt"),
            )
            satisfied.append(item_id)
            continue
        if state not in VALID_CLASSIFICATIONS:
            raise CycleError(
                f"{item_id}.state must be {RECONCILIATION_SATISFIED!r} or one of {sorted(VALID_CLASSIFICATIONS)}"
            )
        boundary = nonempty_string(raw_item.get("boundary"), f"{item_id}.boundary")
        next_action = nonempty_string(raw_item.get("next_action"), f"{item_id}.next_action")
        finding_id = f"RECONCILE-{batch_id}-{item_id}"
        requirement = (
            f"Scope {scope_id} must reach its declared desired state: {desired_state}. "
            f"Item {item_id} needs a satisfaction receipt or a measured external blocker with a named recheck."
        )
        if state == INTERNAL:
            finding = {
                "finding_id": finding_id,
                "classification": INTERNAL,
                "accepted_requirement": requirement,
                "boundary": boundary,
                "next_action": next_action,
                "proof_requirements": REQUIRED_PROOF_ORDER,
                "proof_plan": {
                    "focused_test": (
                        f"Perform the declared repair action for reconciliation item {item_id}: {next_action} "
                        "Save the exact local contract or test receipt under evidence/."
                    ),
                    "runtime_proof": (
                        f"Verify that reconciliation item {item_id} now satisfies its declared state with a real "
                        "runtime trace; save the trace under evidence/."
                    ),
                    "independent_review": (
                        f"A fresh reviewer verifies the {item_id} satisfaction receipt and its causal boundary."
                    ),
                },
            }
        else:
            blocker = nonempty_string(raw_item.get("blocker"), f"{item_id}.blocker")
            next_check = parse_utc(raw_item.get("next_check_at"), f"{item_id}.next_check_at")
            if next_check <= observed_at:
                raise CycleError(f"{item_id}.next_check_at must be after reconciliation observation.observed_at")
            finding = {
                "finding_id": finding_id,
                "classification": EXTERNAL,
                "accepted_requirement": requirement,
                "boundary": boundary,
                "next_action": next_action,
                "blocker": blocker,
                "last_checked_at": observed_at.isoformat().replace("+00:00", "Z"),
                "next_check_at": next_check.isoformat().replace("+00:00", "Z"),
                "last_check_evidence": receipt_evidence,
            }
        findings.append(validate_finding(finding))

    input_path = findings_path(task_dir)
    if input_path.exists():
        input_data = load_json(input_path, "findings.json")
        if input_data.get("schema") != FINDINGS_SCHEMA or not isinstance(input_data.get("findings"), list):
            raise CycleError("findings.json is not a valid task finding document")
        existing = list(input_data["findings"])
    else:
        input_data = {"schema": FINDINGS_SCHEMA}
        existing = []
    known_ids = {
        item.get("finding_id") for item in existing if isinstance(item, dict) and isinstance(item.get("finding_id"), str)
    }
    conflicts = sorted(finding["finding_id"] for finding in findings if finding["finding_id"] in known_ids)
    if conflicts:
        raise CycleError(f"reconciliation batch {batch_id} already has frozen findings: {', '.join(conflicts)}")

    receipt_path = task_dir / "evidence" / f"reconciliation-{batch_id}-registration.json"
    registration = {
        "schema": "agent-reconciliation-registration-receipt/v1",
        "batch_id": batch_id,
        "scope_id": scope_id,
        "desired_state": desired_state,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "observation_evidence": observation_relative,
        "observation_sha256": sha256_file(observation_path),
        "evidence": receipt_evidence,
        "satisfied_items": satisfied,
        "satisfaction_receipts": satisfaction_receipts,
        "registered_findings": [finding["finding_id"] for finding in findings],
    }
    if not findings:
        write_json_atomic(receipt_path, registration)
        return {
            "decision": "RECONCILIATION_SATISFIED",
            "scope_id": scope_id,
            "satisfied_items": satisfied,
            "registration_evidence": receipt_path.relative_to(task_dir).as_posix(),
        }
    existing.extend(findings)
    input_data["findings"] = existing
    write_json_atomic(input_path, input_data)
    reconciled = reconcile(task_dir)
    write_json_atomic(receipt_path, registration)
    decision = select_next(load_cycle(task_dir))
    decision["scope_id"] = scope_id
    decision["registered"] = [finding["finding_id"] for finding in findings]
    decision["satisfied_items"] = satisfied
    decision["registration_evidence"] = receipt_path.relative_to(task_dir).as_posix()
    decision["reconciled"] = reconciled
    return decision


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


def proof_receipt(
    task_dir: Path,
    supplied: str,
    finding_id: str,
    proof: str,
    result: str,
) -> tuple[dict[str, Any], str, str]:
    """Load and verify a typed receipt plus the raw evidence it binds."""
    receipt_relative = evidence_path(task_dir, supplied)
    receipt_path = task_dir / receipt_relative
    receipt = load_json(receipt_path, "proof receipt")
    if receipt.get("schema") != PROOF_RECEIPT_SCHEMA:
        raise CycleError(f"proof receipt.schema must equal {PROOF_RECEIPT_SCHEMA!r}")
    if receipt.get("finding_id") != finding_id:
        raise CycleError("proof receipt.finding_id does not match --finding")
    if receipt.get("proof") != proof:
        raise CycleError("proof receipt.proof does not match --proof")
    if receipt.get("result") != result:
        raise CycleError("proof receipt.result does not match --result")
    attempt_id = nonempty_string(receipt.get("attempt_id"), "proof receipt.attempt_id")
    if not ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise CycleError("proof receipt.attempt_id is not a durable identifier")
    recorded_at = parse_utc(receipt.get("recorded_at"), "proof receipt.recorded_at")
    evidence_relative = evidence_path(
        task_dir, nonempty_string(receipt.get("evidence_path"), "proof receipt.evidence_path")
    )
    if evidence_relative == receipt_relative:
        raise CycleError("proof receipt must bind a separate raw evidence artifact")
    claimed_evidence_sha = nonempty_string(receipt.get("evidence_sha256"), "proof receipt.evidence_sha256")
    if not SHA256_RE.fullmatch(claimed_evidence_sha):
        raise CycleError("proof receipt.evidence_sha256 must be a lowercase SHA-256 digest")
    actual_evidence_sha = sha256_file(task_dir / evidence_relative)
    if actual_evidence_sha != claimed_evidence_sha:
        raise CycleError("proof receipt evidence SHA-256 is stale")

    producer = receipt.get("producer")
    if not isinstance(producer, dict):
        raise CycleError("proof receipt.producer must be an object")
    producer_type = nonempty_string(producer.get("type"), "proof receipt.producer.type")
    producer_identity = nonempty_string(producer.get("identity"), "proof receipt.producer.identity")
    normalized_producer: dict[str, Any] = {"type": producer_type, "identity": producer_identity}
    normalized = dict(receipt)
    normalized["attempt_id"] = attempt_id
    normalized["recorded_at"] = recorded_at.isoformat().replace("+00:00", "Z")
    normalized["evidence_path"] = evidence_relative
    normalized["evidence_sha256"] = actual_evidence_sha
    if proof == "independent_review":
        if producer_type != "review":
            raise CycleError("independent review receipt requires producer.type='review'")
        reviewer = nonempty_string(receipt.get("reviewer"), "proof receipt.reviewer")
        if reviewer != producer_identity:
            raise CycleError("proof receipt reviewer must equal producer.identity")
        if receipt.get("fresh_context") is not True:
            raise CycleError("independent review receipt requires fresh_context=true")
        verdict = nonempty_string(receipt.get("verdict"), "proof receipt.verdict")
        if verdict != result:
            raise CycleError("independent review receipt verdict must equal result")
        normalized["reviewer"] = reviewer
        normalized["fresh_context"] = True
        normalized["verdict"] = verdict
    else:
        if producer_type != "command":
            raise CycleError(f"{proof} receipt requires producer.type='command'")
        normalized_producer["command"] = string_sequence(
            producer.get("command"), "proof receipt.producer.command"
        )
    normalized["producer"] = normalized_producer
    return normalized, receipt_relative, sha256_file(receipt_path)


def proof_record_from_receipt(
    receipt: dict[str, Any], receipt_relative: str, receipt_sha256: str,
) -> dict[str, Any]:
    record = {
        "result": receipt["result"],
        "attempt_id": receipt["attempt_id"],
        "recorded_at": receipt["recorded_at"],
        "receipt": receipt_relative,
        "receipt_sha256": receipt_sha256,
        "evidence": receipt["evidence_path"],
        "evidence_sha256": receipt["evidence_sha256"],
        "producer": receipt["producer"],
    }
    if receipt["proof"] == "independent_review":
        record.update({
            "reviewer": receipt["reviewer"],
            "fresh_context": True,
            "verdict": receipt["verdict"],
        })
    return record


def validate_stored_proof(
    task_dir: Path, finding_id: str, proof: str, record: dict[str, Any],
) -> None:
    result = nonempty_string(record.get("result"), f"{finding_id}.{proof}.result")
    receipt, receipt_relative, receipt_sha256 = proof_receipt(
        task_dir,
        nonempty_string(record.get("receipt"), f"{finding_id}.{proof}.receipt"),
        finding_id,
        proof,
        result,
    )
    expected = proof_record_from_receipt(receipt, receipt_relative, receipt_sha256)
    for key, value in expected.items():
        if record.get(key) != value:
            raise CycleError(f"{finding_id}.{proof} stored proof is stale at {key}")


def validate_evidence_files(task_dir: Path, cycle: dict[str, Any]) -> None:
    """Do not let a hand-edited queue point to evidence that is not on disk."""
    for raw in cycle["work_orders"]:
        order = validate_order(raw)
        if order["classification"] == EXTERNAL:
            evidence_path(task_dir, order.get("last_check_evidence"))
        for proof, record in order["proofs"].items():
            if not isinstance(record, dict):
                raise CycleError(f"{order['finding_id']}.{proof} proof record must be an object")
            if order.get("legacy_terminal_proofs"):
                evidence_path(
                    task_dir,
                    nonempty_string(record.get("evidence"), f"{order['finding_id']}.{proof}.evidence"),
                )
            else:
                validate_stored_proof(task_dir, order["finding_id"], proof, record)
        for index, record in enumerate(order["attempt_history"]):
            if not isinstance(record, dict):
                raise CycleError(f"{order['finding_id']}.attempt_history[{index}] must be an object")
            proof = nonempty_string(record.get("proof"), f"{order['finding_id']}.attempt_history[{index}].proof")
            validate_stored_proof(task_dir, order["finding_id"], proof, record)
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
    exhausted = refresh_budget_statuses(cycle)
    if exhausted:
        cycle["updated_at"] = now_utc()
        write_json_atomic(cycle_path(task_dir), cycle)
    order = find_order(cycle, finding_id)
    if order["classification"] != INTERNAL:
        raise CycleError(f"{finding_id}: external blockers do not accept proof records")
    if order["status"] in TERMINAL:
        if order["status"] == "BUDGET_EXHAUSTED":
            return select_next(cycle)
        raise CycleError(f"{finding_id}: terminal work order cannot accept new proof")
    if proof not in order["proof_requirements"]:
        raise CycleError(f"{finding_id}: {proof!r} is not a required proof")
    pending = pending_proofs(order)
    if not pending or proof != pending[0]:
        expected = pending[0] if pending else "no proof"
        raise CycleError(f"{finding_id}: proof order violation; expected {expected!r}, got {proof!r}")
    receipt, receipt_relative, receipt_sha256 = proof_receipt(
        task_dir, evidence, finding_id, proof, result
    )
    proof_record = proof_record_from_receipt(receipt, receipt_relative, receipt_sha256)
    used_attempt_ids = {
        item.get("attempt_id") for item in order["attempt_history"] if isinstance(item, dict)
    }
    used_receipt_digests = {
        item.get("receipt_sha256") for item in order["attempt_history"] if isinstance(item, dict)
    }
    if proof_record["attempt_id"] in used_attempt_ids:
        raise CycleError(f"{finding_id}: attempt_id {proof_record['attempt_id']!r} was already recorded")
    if proof_record["receipt_sha256"] in used_receipt_digests:
        raise CycleError(f"{finding_id}: identical proof receipt was already recorded")
    if proof == "independent_review":
        if reviewer is not None and nonempty_string(reviewer, "reviewer") != proof_record["reviewer"]:
            raise CycleError("--reviewer does not match the typed review receipt")
        if fresh_context and proof_record["fresh_context"] is not True:
            raise CycleError("--fresh-context does not match the typed review receipt")
    history_record = dict(proof_record)
    history_record["proof"] = proof
    order["attempt_history"].append(history_record)
    order["budget"]["tool_calls"] += 1
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
            "attempt_id": proof_record["attempt_id"],
            "receipt": proof_record["receipt"],
            "receipt_sha256": proof_record["receipt_sha256"],
            "evidence": proof_record["evidence"],
            "evidence_sha256": proof_record["evidence_sha256"],
            "causal_boundary": failure_boundary,
            "next_action": failure_action,
            "recorded_at": proof_record["recorded_at"],
        }
        order["status"] = "READY"
    else:
        order["proofs"][proof] = proof_record
        order["status"] = next_status(order)
    reason = budget_exhaustion_reason(order)
    if reason is not None:
        order["status"] = "BUDGET_EXHAUSTED"
        order["budget"]["exhausted_reason"] = reason
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
    budget_exhausted = [order for order in orders if order["status"] == "BUDGET_EXHAUSTED"]
    if budget_exhausted:
        order = budget_exhausted[0]
        return {
            "decision": "BUDGET_EXHAUSTED",
            "completed": False,
            "finding_id": order["finding_id"],
            "boundary": order.get("last_failure", {}).get("causal_boundary", order["boundary"]),
            "next_action": order.get("last_failure", {}).get("next_action", order["next_action"]),
            "budget_reason": order["budget"]["exhausted_reason"],
        }
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
    for key in (
        "finding_id", "status", "boundary", "next_action", "next_proof",
        "proof_instruction", "blocker", "next_check_at", "budget_reason",
    ):
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
    drift = sub.add_parser("register-plan-drift")
    drift.add_argument("--task-dir", type=Path, required=True)
    drift.add_argument("--finding", required=True)
    drift.add_argument("--plan", type=Path, required=True)
    drift.add_argument("--source", type=Path, required=True)
    drift.add_argument("--expected-sha256", required=True)
    drift.add_argument("--output-root", type=Path, required=True)
    drift.add_argument("--quiescence-evidence", required=True)
    drift.add_argument("--json", action="store_true")
    reconciliation = sub.add_parser("register-reconciliation-gap")
    reconciliation.add_argument("--task-dir", type=Path, required=True)
    reconciliation.add_argument("--batch", required=True)
    reconciliation.add_argument("--observation", required=True)
    reconciliation.add_argument("--evidence", required=True)
    reconciliation.add_argument("--json", action="store_true")
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
            if refresh_budget_statuses(cycle):
                cycle["updated_at"] = now_utc()
                write_json_atomic(cycle_path(task_dir), cycle)
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
        elif args.command == "register-plan-drift":
            result = register_plan_drift(
                task_dir,
                args.finding,
                args.plan.resolve(),
                args.source.resolve(),
                args.expected_sha256,
                args.output_root.resolve(),
                args.quiescence_evidence,
            )
        elif args.command == "register-reconciliation-gap":
            result = register_reconciliation_gap(task_dir, args.batch, args.observation, args.evidence)
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
