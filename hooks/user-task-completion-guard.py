#!/usr/bin/env python3
"""Turn actionable user requests into durable, evidence-bound work orders.

The global request ledger is an archive and reminder.  It must not be the only
place where a task lives: a reminder can be marked done without proving that
anything happened.  This hook records an actionable request in the current
repository at ``.agent/user-tasks/<REQ-id>/`` and makes the task's terminal
state depend on receipts that are actually present on disk.

The guard deliberately does not infer a plan, run commands, or turn a question
into work.  It records only a conservative action/recommendation request.  A
request that names a complete collection has one extra invariant: its
``state.json.items`` is the real inventory, and each item needs a receipt or a
measured external blocker.  This is a mode of every user task, not a separate
checkpoint-specific queue.

Measured desired/actual observations are equally durable: a structured
reconciliation observation below ``.agent/tasks`` must have a controller
registration receipt before Stop can close. The hook deliberately does not
extract observations from prose; untrusted prose is not a safe work order.
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


REQUEST_SCHEMA = "agent-user-task-request/v1"
STATE_SCHEMA = "agent-user-task-state/v1"
TERMINAL_RECEIPT_SCHEMA = "agent-user-task-terminal-receipt/v1"
RECONCILIATION_OBSERVATION_SCHEMA = "agent-reconciliation-observation/v1"
RECONCILIATION_REGISTRATION_SCHEMA = "agent-reconciliation-registration-receipt/v1"
ACTIVE_STATUSES = {"OPEN", "IN_PROGRESS"}
TERMINAL_STATUSES = {"COMPLETE", "BLOCKED_EXTERNAL"}
ITEM_STATUSES = {"PENDING", "RUNNING", "PASS", "BLOCKED_EXTERNAL"}
TASK_CAPTURE_ENV = "CLAUDE_USER_TASK_CAPTURE"

# Derived from the live request ledger's deliberately conservative classifier.
# Add a verb only after a measured miss; a broad "any imperative" matcher would
# turn questions and chat into blocking work orders.
REQUEST_WORDS = re.compile(
    r"\b(?:сделай|сделать|проверь|проверить|найди|найти|исследуй|исследовать|"
    r"посмотри|посмотреть|запиши|записать|внедри|внедрить|добавь|добавить|"
    r"исправь|исправить|запусти|запустить|почисти|почистить|создай|создать|"
    r"перенеси|перенести|подключи|подключить|обнови|обновить|проведи|провести|"
    r"проанализируй|проанализировать|расшифруй|расшифровать|синхронизируй|"
    r"синхронизировать|закрой|закрыть|доделай|доделать|сформируй|сформировать|"
    r"забери|забрать|продолжи|продолжить|давай|сделаем|внедрим|поставь|поставить|"
    r"протестируй|протестировать|протестируем|тестируй|тестировать|тестируем|"
    r"записывай|записывать|загружай|загружать|выгрузи|выгружать|сохрани|сохранять|"
    r"дополни|дополнить|дополняй|дополнять|"
    r"обсчитай|посчитай|пересчитай|обработай|прогони|отрендери|собери|сравни|"
    r"оцени|вычисли|calculate|compute|process|render|build|compare|evaluate|"
    r"fix|check|verify|research|find|add|implement|run|update|clean|create|move|"
    r"connect|sync|close|finish|continue|install|test)\b",
    re.IGNORECASE | re.UNICODE,
)
RECOMMENDATION_WORDS = re.compile(
    r"\b(?:надо|нужно|важно|пусть|лучше|стоит|хочу|следует|обязательно|"
    r"we\s+should|we\s+need|must|should|recommend|recommendation)\b",
    re.IGNORECASE | re.UNICODE,
)
QUESTION_ONLY = re.compile(
    r"^(?:а\s+)?(?:почему|зачем|как|что|есть\s+ли|можно\s+ли|"
    r"why|how|what|can\s+we|is\s+there)\b[^.!\n]*[?؟]?$",
    re.IGNORECASE | re.UNICODE,
)
COLLECTION_WORDS = re.compile(r"\b(?:все|всех|кажд(?:ый|ую|ые|ого|ых)|all|every|each)\b", re.IGNORECASE)
RECONCILIATION_COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_root(cwd: Path) -> Path | None:
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def session_id(event: dict[str, Any]) -> str:
    for key in ("session_id", "sessionId"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    return value or "unscoped"


def event_prompt(event: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message", "content"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def task_capture_enabled() -> bool:
    """Return whether this process is handling a direct user request.

    Inner automation may invoke a harness CLI with an instructional prompt (for
    example a semantic pre-push reviewer).  Such prompts are data for that
    automation, not new user work.  The caller must opt out explicitly so this
    guard never tries to infer provenance from the prompt's wording.
    """
    return os.environ.get(TASK_CAPTURE_ENV) != "0"


def classify_prompt(prompt: str) -> tuple[str, bool]:
    if REQUEST_WORDS.search(prompt):
        return "request", True
    if RECOMMENDATION_WORDS.search(prompt) and not QUESTION_ONLY.match(prompt):
        return "recommendation", True
    return "note", False


def requires_inventory(prompt: str) -> bool:
    """Collection is a task mode only when an actionable request names all items."""
    return bool(REQUEST_WORDS.search(prompt) and COLLECTION_WORDS.search(prompt))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain an object")
    return payload


def task_id_for(session: str, prompt: str) -> str:
    digest = hashlib.sha256(f"{session}\0{prompt}".encode("utf-8", "ignore")).hexdigest()[:12]
    return f"REQ-{digest.upper()}"


def task_root(root: Path, task_id: str) -> Path:
    return root / ".agent" / "user-tasks" / task_id


def request_path(root: Path, task_id: str) -> Path:
    return task_root(root, task_id) / "request.json"


def state_path(root: Path, task_id: str) -> Path:
    return task_root(root, task_id) / "state.json"


def terminal_receipt_path(root: Path, task_id: str) -> Path:
    return task_root(root, task_id) / "terminal-receipt.json"


def record_task(root: Path, event: dict[str, Any], prompt: str) -> dict[str, Any]:
    session = session_id(event)
    task_id = task_id_for(session, prompt)
    request_file = request_path(root, task_id)
    if request_file.exists():
        return load_json(request_file)
    kind, _ = classify_prompt(prompt)
    request = {
        "schema": REQUEST_SCHEMA,
        "task_id": task_id,
        "root": str(root.resolve()),
        "session_id": session,
        "kind": kind,
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8", "ignore")).hexdigest(),
        "requires_inventory": requires_inventory(prompt),
        "recorded_at": now_utc(),
    }
    state = {
        "schema": STATE_SCHEMA,
        "task_id": task_id,
        "request_sha256": request["prompt_sha256"],
        "status": "OPEN",
        "updated_at": now_utc(),
    }
    write_json_atomic(request_file, request)
    write_json_atomic(state_path(root, task_id), state)
    return request


def task_requests(root: Path, session: str | None = None) -> list[dict[str, Any]]:
    directory = root / ".agent" / "user-tasks"
    if not directory.is_dir():
        return []
    requests: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*/request.json")):
        try:
            request = load_json(path)
        except ValueError:
            continue
        if request.get("schema") != REQUEST_SCHEMA or request.get("root") != str(root.resolve()):
            continue
        if session is None or request.get("session_id") == session:
            requests.append(request)
    return requests


def evidence_file(task_dir: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative evidence path")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{label} evidence must be relative")
    resolved = (task_dir / relative).resolve()
    try:
        resolved.relative_to(task_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} evidence escapes the task directory") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} evidence file does not exist: {relative.as_posix()}")
    return resolved


def evidence_files(task_dir: Path, values: Any, label: str) -> None:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} must be a non-empty list of relative evidence paths")
    for value in values:
        evidence_file(task_dir, value, label)


def nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def reconciliation_item_ids(observation: dict[str, Any], task_dir: Path) -> tuple[list[str], list[str]]:
    """Return satisfied ids and the controller finding ids an observation requires.

    This intentionally checks only the receipt chain at Stop. The controller
    owns classification and proof-plan validation; the guard rejects a raw
    observation if that controller work was never registered.
    """
    items = observation.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("reconciliation observation.items must be a non-empty list")
    satisfied: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise ValueError("each reconciliation observation item must be an object")
        item_id = nonempty(raw_item.get("item_id"), "reconciliation item_id").lower()
        if not RECONCILIATION_COMPONENT_RE.fullmatch(item_id):
            raise ValueError(f"reconciliation item_id is not durable: {item_id!r}")
        if item_id in seen:
            raise ValueError(f"reconciliation observation repeats item_id {item_id!r}")
        seen.add(item_id)
        if raw_item.get("state") == "SATISFIED":
            evidence_file(task_dir, raw_item.get("satisfaction_receipt"), f"{item_id}.satisfaction_receipt")
            satisfied.append(item_id)
        else:
            unresolved.append(item_id)
    return satisfied, unresolved


def assess_reconciliation_observation(task_dir: Path, observation_path: Path) -> str | None:
    """Return an unregistered observation's exact defect, otherwise ``None``."""
    observation_relative = observation_path.relative_to(task_dir).as_posix()
    observation = load_json(observation_path)
    if observation.get("schema") != RECONCILIATION_OBSERVATION_SCHEMA:
        raise ValueError(f"schema must equal {RECONCILIATION_OBSERVATION_SCHEMA!r}")
    _, unresolved_items = reconciliation_item_ids(observation, task_dir)
    observation_sha256 = hashlib.sha256(observation_path.read_bytes()).hexdigest()

    registrations = sorted(observation_path.parent.glob("reconciliation-*-registration.json"))
    matched = False
    for registration_path in registrations:
        try:
            registration = load_json(registration_path)
        except ValueError:
            continue
        if registration.get("schema") != RECONCILIATION_REGISTRATION_SCHEMA:
            continue
        if registration.get("observation_evidence") != observation_relative:
            continue
        matched = True
        if registration.get("observation_sha256") != observation_sha256:
            continue
        batch_id = registration.get("batch_id")
        if not isinstance(batch_id, str) or not RECONCILIATION_COMPONENT_RE.fullmatch(batch_id):
            continue
        expected = [f"RECONCILE-{batch_id}-{item_id}" for item_id in unresolved_items]
        if registration.get("registered_findings") != expected:
            continue
        if expected:
            findings_file = task_dir / "findings.json"
            try:
                findings = load_json(findings_file).get("findings")
            except ValueError:
                continue
            actual = {
                item.get("finding_id") for item in findings
                if isinstance(item, dict) and isinstance(item.get("finding_id"), str)
            } if isinstance(findings, list) else set()
            if not set(expected).issubset(actual):
                continue
        return None
    if matched:
        return "controller registration receipt does not bind the current observation and every required finding"
    return "has no controller registration receipt"


def assess_reconciliation_observations(root: Path) -> list[str]:
    """Find measured observations that were never converted into durable work."""
    evidence_root = root / ".agent" / "tasks"
    if not evidence_root.is_dir():
        return []
    unresolved: list[str] = []
    for observation_path in sorted(evidence_root.glob("*/evidence/reconciliation-*.json")):
        if observation_path.name.endswith("-registration.json"):
            continue
        task_dir = observation_path.parents[1]
        try:
            defect = assess_reconciliation_observation(task_dir, observation_path)
        except ValueError as exc:
            defect = str(exc)
        if defect:
            relative = observation_path.relative_to(root).as_posix()
            unresolved.append(f"{relative}: {defect}")
    return unresolved


def assess_items(task_dir: Path, state: dict[str, Any]) -> tuple[str, str]:
    raw_items = state.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return "INCOMPLETE", "collection task needs a non-empty state.json.items inventory"
    seen: set[str] = set()
    active = 0
    blocked = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            return "INCOMPLETE", "each collection item must be an object"
        try:
            item_id = nonempty(raw.get("item_id"), "collection item_id")
            if item_id in seen:
                raise ValueError(f"duplicate collection item_id: {item_id}")
            seen.add(item_id)
            status = raw.get("status")
            if status not in ITEM_STATUSES:
                raise ValueError(f"{item_id}: unknown item status {status!r}")
            if status in {"PENDING", "RUNNING"}:
                active += 1
                continue
            evidence_files(task_dir, raw.get("evidence"), f"{item_id}.evidence")
            if status == "BLOCKED_EXTERNAL":
                blocked += 1
                nonempty(raw.get("blocker"), f"{item_id}.blocker")
                nonempty(raw.get("recheck"), f"{item_id}.recheck")
        except ValueError as exc:
            return "INCOMPLETE", str(exc)
    total = len(raw_items)
    if active:
        return "INCOMPLETE", f"{total - active}/{total} collection items terminal; {active} remain PENDING or RUNNING"
    if blocked:
        return "BLOCKED_EXTERNAL", f"{total - blocked}/{total} collection items PASS; {blocked} are measured BLOCKED_EXTERNAL"
    return "COMPLETE", f"{total}/{total} collection items PASS with local receipts"


def assess_task(root: Path, request: dict[str, Any]) -> tuple[str, str]:
    task_id = nonempty(request.get("task_id"), "request task_id")
    path = state_path(root, task_id)
    if not path.is_file():
        return "INCOMPLETE", f"missing {path.relative_to(root).as_posix()}"
    try:
        state = load_json(path)
        if state.get("schema") != STATE_SCHEMA:
            raise ValueError(f"state.json.schema must equal {STATE_SCHEMA!r}")
        if state.get("task_id") != task_id:
            raise ValueError("state task_id does not match request")
        if state.get("request_sha256") != request.get("prompt_sha256"):
            raise ValueError("state request_sha256 does not match request")
        status = state.get("status")
        if status in ACTIVE_STATUSES:
            return "INCOMPLETE", f"state status is {status}; write the result and its local receipt"
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"unknown task status {status!r}")
        if request.get("requires_inventory"):
            outcome, detail = assess_items(path.parent, state)
            if outcome == "INCOMPLETE":
                return outcome, detail
            if outcome != status:
                raise ValueError(f"state status {status} disagrees with collection outcome {outcome}")
            # The per-item receipts carry the evidence, but nothing carried the OUTCOME.
            # This branch used to return here, before state.result was ever looked at, so a
            # collection could close COMPLETE with every item receipted and no result at
            # all - the Stop message asks for "the result and its local receipt" and only
            # the receipt half was enforced. Found by a negative control on this assessor,
            # 2026-08-27: five mutations of a real state.json, and this was the one that
            # came back green.
            if status == "COMPLETE":
                nonempty(state.get("result"), "state.result")
            return outcome, detail
        evidence_files(path.parent, state.get("evidence"), "state.evidence")
        if status == "COMPLETE":
            nonempty(state.get("result"), "state.result")
            return "COMPLETE", "task has a result and local receipt"
        nonempty(state.get("blocker"), "state.blocker")
        nonempty(state.get("recheck"), "state.recheck")
        return "BLOCKED_EXTERNAL", "task has a measured external blocker and named recheck"
    except ValueError as exc:
        return "INCOMPLETE", str(exc)


def record_terminal_receipt(root: Path, request: dict[str, Any], outcome: str) -> None:
    """Bind an already-validated terminal state to the project task.

    The archive ledger reads this small receipt rather than treating a hand-edited
    ``state.json.status`` as completion. A later state edit changes its hash and
    requires the guard to validate it again before the projection closes.
    """
    task_id = nonempty(request.get("task_id"), "request task_id")
    state_bytes = state_path(root, task_id).read_bytes()
    write_json_atomic(terminal_receipt_path(root, task_id), {
        "schema": TERMINAL_RECEIPT_SCHEMA,
        "task_id": task_id,
        "outcome": outcome,
        "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
        "recorded_at": now_utc(),
    })


def user_prompt(event: dict[str, Any], cwd: Path | None = None) -> int:
    if not task_capture_enabled():
        return 0
    prompt = event_prompt(event)
    _, actionable = classify_prompt(prompt)
    if not prompt or not actionable:
        return 0
    root = repo_root(cwd or Path.cwd())
    if root is None:
        return 0
    request = record_task(root, event, prompt)
    task_id = request["task_id"]
    relative = task_root(root, task_id).relative_to(root).as_posix()
    inventory = " This request names a complete set: fill state.json.items from the real inventory." if request["requires_inventory"] else ""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                f"[user-task] Recorded {task_id} at {relative}. Continue this user task until state.json is "
                "COMPLETE with a result and real evidence, or BLOCKED_EXTERNAL with a measured blocker, "
                f"named recheck, and evidence.{inventory} Do not replace work with a prose promise."
            ),
        },
    }, ensure_ascii=False))
    return 0


def stop(event: dict[str, Any], cwd: Path | None = None) -> int:
    root = repo_root(cwd or Path.cwd())
    if root is None:
        return 0
    unresolved = assess_reconciliation_observations(root)
    for request in task_requests(root, session_id(event)):
        outcome, detail = assess_task(root, request)
        if outcome == "INCOMPLETE":
            unresolved.append(f"{request['task_id']}: {detail}")
        else:
            record_terminal_receipt(root, request, outcome)
    if not unresolved:
        return 0
    print(json.dumps({
        "decision": "block",
        "reason": (
            "A durable user task or measured reconciliation gap has no evidence-bound terminal state. "
            "Continue the work; then save its local receipt and state.json result, or record the actual external "
            "blocker and named recheck. A reconciliation observation must be registered through "
            "task-cycle-controller.py register-reconciliation-gap; a collection must inventory every item rather "
            "than closing after one.\n- "
            + "\n- ".join(unresolved)
        ),
    }, ensure_ascii=False))
    return 0


def session_start(event: dict[str, Any], cwd: Path | None = None) -> int:
    root = repo_root(cwd or Path.cwd())
    if root is None:
        return 0
    open_tasks: list[str] = []
    for request in task_requests(root):
        outcome, _ = assess_task(root, request)
        if outcome == "INCOMPLETE":
            open_tasks.append(str(request["task_id"]))
    if open_tasks:
        visible = ", ".join(open_tasks[:8])
        more = f" (+{len(open_tasks) - 8} more)" if len(open_tasks) > 8 else ""
        print(f"[user-task] Open durable user tasks in this repository: {visible}{more}. Read their request.json/state.json before repeating work.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--session-start", action="store_true")
    args = parser.parse_args(argv)
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}
    if not isinstance(event, dict):
        return 0
    if args.session_start:
        return session_start(event)
    if event_prompt(event):
        return user_prompt(event)
    return stop(event)


if __name__ == "__main__":
    raise SystemExit(main())
