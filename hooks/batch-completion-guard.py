#!/usr/bin/env python3
"""Keep an explicit user batch from silently becoming one completed item.

The task-cycle controller deliberately starts only from evaluator-produced
``findings.json``.  A request such as "обсчитай все чекпоинты" is neither an
incident nor a finding, so without this bridge the agent can finish the first
item and leave the user request as unowned prose.

For a narrow set of explicit, action-oriented batch requests this hook writes a
durable request below ``.agent/batches/<intent-id>/``.  The agent must inventory
the real items in ``manifest.json`` before execution.  At Stop, every item must
have a real local receipt or the remaining set must be honestly external-blocked;
one completed checkpoint cannot close the batch.

It does not choose the inventory, execute commands, invent a retry, or schedule
background work.  Those are domain decisions made from the actual source and
runtime.  A homogeneous long-running batch should normally use one resumable
runner that advances this manifest, rather than a chat turn per item.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "agent-batch-request/v1"
MANIFEST_SCHEMA = "agent-batch-manifest/v1"
ITEM_STATUSES = {"PENDING", "RUNNING", "PASS", "BLOCKED_EXTERNAL"}
ACTIVE_STATUSES = {"PENDING", "RUNNING"}

# Deliberately narrow: a noun alone ("all checkpoints") or a status question
# must not create a batch obligation.  The user must ask to perform an action
# across a complete set.  More nouns belong here only after a measured miss.
ACTION = r"(?:обсчитай|посчитай|пересчитай|обработай|проверь|прогони|отрендери|собери|сравни|оцени|вычисли|calculate|compute|process|check|verify|run|render|build|compare|evaluate)"
QUANTIFIER = r"(?:все|всех|кажд(?:ый|ую|ые|ого|ых)|all|every|each)"
BATCH_NOUN = r"(?:чекпоинт\w*|checkpoint\w*|модел\w*|model\w*|изображени\w*|image\w*|файл\w*|file\w*|запис\w*|record\w*|строк\w*|row\w*|задач\w*|job\w*)"
BATCH_PATTERNS = (
    re.compile(rf"\b{ACTION}\b[^.?!\n]{{0,96}}\b{QUANTIFIER}\b[^.?!\n]{{0,96}}\b{BATCH_NOUN}\b", re.IGNORECASE),
    re.compile(rf"\b{QUANTIFIER}\b[^.?!\n]{{0,48}}\b{BATCH_NOUN}\b[^.?!\n]{{0,96}}\b{ACTION}\b", re.IGNORECASE),
)


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


def is_batch_request(prompt: str) -> bool:
    return any(pattern.search(prompt) for pattern in BATCH_PATTERNS)


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


def batch_root(root: Path, intent_id: str) -> Path:
    return root / ".agent" / "batches" / intent_id


def request_path(root: Path, intent_id: str) -> Path:
    return batch_root(root, intent_id) / "request.json"


def manifest_path(root: Path, intent_id: str) -> Path:
    return batch_root(root, intent_id) / "manifest.json"


def intent_id_for(root: Path, session: str, prompt: str) -> str:
    digest = hashlib.sha256(f"{root.resolve()}\0{session}\0{prompt}".encode("utf-8", "ignore")).hexdigest()
    return digest[:16]


def record_request(root: Path, event: dict[str, Any], prompt: str) -> dict[str, Any]:
    session = session_id(event)
    intent_id = intent_id_for(root, session, prompt)
    path = request_path(root, intent_id)
    if path.exists():
        return load_json(path)
    request = {
        "schema": REQUEST_SCHEMA,
        "intent_id": intent_id,
        "root": str(root.resolve()),
        "session_id": session,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8", "ignore")).hexdigest(),
        "status": "ACTIVE",
        "recorded_at": now_utc(),
    }
    write_json_atomic(path, request)
    return request


def active_requests(root: Path, session: str) -> list[dict[str, Any]]:
    directory = root / ".agent" / "batches"
    if not directory.is_dir():
        return []
    requests: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*/request.json")):
        try:
            request = load_json(path)
        except ValueError:
            continue
        if (
            request.get("schema") == REQUEST_SCHEMA
            and request.get("root") == str(root.resolve())
            and request.get("session_id") == session
            and request.get("status") == "ACTIVE"
        ):
            requests.append(request)
    return requests


def evidence_file(batch_dir: Path, value: Any, item_id: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{item_id}: evidence must be a non-empty path below the batch directory")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{item_id}: evidence must be relative")
    resolved = (batch_dir / relative).resolve()
    try:
        resolved.relative_to(batch_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"{item_id}: evidence escapes the batch directory") from exc
    if not resolved.is_file():
        raise ValueError(f"{item_id}: evidence file does not exist: {relative.as_posix()}")


def assess_manifest(root: Path, request: dict[str, Any]) -> tuple[str, str]:
    intent_id = str(request["intent_id"])
    path = manifest_path(root, intent_id)
    if not path.is_file():
        return "INCOMPLETE", f"missing {path.relative_to(root).as_posix()}"
    try:
        manifest = load_json(path)
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise ValueError(f"manifest.json.schema must equal {MANIFEST_SCHEMA!r}")
        if manifest.get("intent_id") != intent_id:
            raise ValueError("manifest intent_id does not match the recorded batch request")
        items = manifest.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("manifest.items must be a non-empty list from the real inventory")
        seen: set[str] = set()
        active = 0
        blocked = 0
        for raw in items:
            if not isinstance(raw, dict):
                raise ValueError("each manifest item must be an object")
            item_id = raw.get("item_id")
            if not isinstance(item_id, str) or not item_id.strip():
                raise ValueError("each manifest item needs a non-empty item_id")
            if item_id in seen:
                raise ValueError(f"duplicate item_id: {item_id}")
            seen.add(item_id)
            status = raw.get("status")
            if status not in ITEM_STATUSES:
                raise ValueError(f"{item_id}: unknown status {status!r}")
            if status in ACTIVE_STATUSES:
                active += 1
            elif status == "PASS":
                evidence_file(path.parent, raw.get("evidence"), item_id)
            else:
                blocked += 1
                blocker = raw.get("blocker")
                recheck = raw.get("recheck")
                if not isinstance(blocker, str) or not blocker.strip():
                    raise ValueError(f"{item_id}: BLOCKED_EXTERNAL requires a measured blocker")
                if not isinstance(recheck, str) or not recheck.strip():
                    raise ValueError(f"{item_id}: BLOCKED_EXTERNAL requires a named recheck")
                evidence_file(path.parent, raw.get("evidence"), item_id)
    except ValueError as exc:
        return "INCOMPLETE", str(exc)
    total = len(items)
    if active:
        return "INCOMPLETE", f"{total - active}/{total} items terminal; {active} remain PENDING or RUNNING"
    if blocked:
        return "BLOCKED_EXTERNAL", f"{total - blocked}/{total} items PASS; {blocked} are measured BLOCKED_EXTERNAL"
    return "COMPLETE", f"{total}/{total} items PASS with local receipts"


def close_request(root: Path, request: dict[str, Any], status: str) -> None:
    request = dict(request)
    request["status"] = status
    request["closed_at"] = now_utc()
    write_json_atomic(request_path(root, str(request["intent_id"])), request)


def user_prompt(event: dict[str, Any], cwd: Path | None = None) -> int:
    prompt = event_prompt(event)
    if not prompt or not is_batch_request(prompt):
        return 0
    root = repo_root(cwd or Path.cwd())
    if root is None:
        return 0
    request = record_request(root, event, prompt)
    intent_id = request["intent_id"]
    relative = manifest_path(root, intent_id).relative_to(root).as_posix()
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                f"[batch-completion] Explicit whole-set request {intent_id} recorded. Before executing, "
                f"inventory the real set in {relative}; keep every item PENDING/RUNNING/PASS/BLOCKED_EXTERNAL "
                "with local receipts. Do not stop after one item. For a long homogeneous run, launch or resume "
                "one manifest-backed runner rather than doing one chat turn per item."
            ),
        },
    }, ensure_ascii=False))
    return 0


def stop(event: dict[str, Any], cwd: Path | None = None) -> int:
    root = repo_root(cwd or Path.cwd())
    if root is None:
        return 0
    unresolved: list[str] = []
    for request in active_requests(root, session_id(event)):
        outcome, detail = assess_manifest(root, request)
        if outcome == "COMPLETE":
            close_request(root, request, "COMPLETE")
        elif outcome == "BLOCKED_EXTERNAL":
            close_request(root, request, "BLOCKED_EXTERNAL")
        else:
            unresolved.append(f"{request['intent_id']}: {detail}")
    if not unresolved:
        return 0
    print(json.dumps({
        "decision": "block",
        "reason": (
            "An explicit whole-set user request is not complete. "
            "Inventory the real batch, advance every actionable item, and save a local receipt per item; "
            "do not report one checkpoint as the requested set. Only a manifest with no PENDING/RUNNING items "
            "and measured BLOCKED_EXTERNAL remainder may end this session.\n- "
            + "\n- ".join(unresolved)
        ),
    }, ensure_ascii=False))
    return 0


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}
    if not isinstance(event, dict):
        return 0
    if event_prompt(event):
        return user_prompt(event)
    return stop(event)


if __name__ == "__main__":
    raise SystemExit(main())
