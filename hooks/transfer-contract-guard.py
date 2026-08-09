#!/usr/bin/env python3
"""Guard file transfers with a durable, handoff-friendly contract.

The same hook is registered for PreToolUse, PostToolUse and Stop:

* PreToolUse blocks clone/copy/move/sync commands without a complete
  ``# transfer-contract: .claude/transfers/<id>.json`` marker.
* PostToolUse reminds the agent to record the command result and verify the
  destination before touching the source.
* Stop blocks a session while a transfer is planned/running/awaiting proof.

The hook never deletes a source and never invents verification evidence. A
second agent can therefore resume from one small JSON record instead of
reconstructing intent from shell history.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safety_common import allow, block, log, read_event  # noqa: E402


TRANSFER_MARKER = re.compile(
    r"(?:^|[\s;&])#\s*transfer-contract\s*:\s*(?P<path>[^\r\n]+)",
    re.IGNORECASE,
)
STATUS_VALUES = {"planned", "running", "verification_pending", "verified", "failed", "blocked", "cancelled"}
OPEN_STATUSES = {"planned", "running", "verification_pending"}
CLOSED_STATUSES = {"verified", "failed", "blocked", "cancelled"}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _event_cwd(event: dict[str, Any]) -> Path:
    raw = _text(event.get("cwd"))
    return Path(raw).expanduser() if raw else Path.cwd()


def _tool_input(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("tool_input") or {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _repo_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / ".claude").exists() or (candidate / ".agent").exists():
            return candidate
    return current


def _contract_path(marker: str, cwd: Path) -> Path | None:
    raw = marker.strip().strip('"\'')
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        return None
    parts = {part.lower() for part in candidate.parts}
    parent = candidate.parent
    if parent.name.lower() != "transfers" or parent.parent.name.lower() not in {".claude", ".agent", ".codex"}:
        return None
    if candidate.suffix.lower() != ".json" or not parts:
        return None
    return candidate


def _marker_path(command: str, cwd: Path) -> Path | None:
    match = TRANSFER_MARKER.search(command)
    return _contract_path(match.group("path"), cwd) if match else None


def _transfer_kind(command: str) -> tuple[str, str] | None:
    checks = (
        (r"\bgit\s+clone\b", "clone", "git"),
        (r"\bgh\s+repo\s+clone\b", "clone", "gh"),
        (r"\brobocopy\b", "move" if re.search(r"/(?:move|mov)\b", command, re.I) else "copy", "robocopy"),
        (r"\brclone\s+(?:copy|copyto)\b", "copy", "rclone"),
        (r"\brclone\s+move\b", "move", "rclone"),
        (r"\brclone\s+sync\b", "sync", "rclone"),
        (r"\brsync\b", "sync", "rsync"),
        (r"\bscp\b", "copy", "scp"),
        (r"\bsftp\b", "copy", "sftp"),
        (r"\bxcopy\b", "copy", "xcopy"),
        (r"\bcopy-item\b", "copy", "powershell"),
        (r"\bmove-item\b", "move", "powershell"),
        (r"(?:^|[;&|])\s*copy\s+", "copy", "copy"),
        (r"(?:^|[;&|])\s*move\s+", "move", "move"),
        (r"(?:^|[;&|])\s*cp\s+", "copy", "cp"),
    )
    for pattern, kind, tool in checks:
        if re.search(pattern, command, re.IGNORECASE):
            return kind, tool
    return None


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return False


def _valid_deadline(value: Any) -> bool:
    raw = _text(value)
    if not raw:
        return False
    try:
        dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _contract_errors(contract: Any, *, pre_transfer: bool = False) -> list[str]:
    if not isinstance(contract, dict):
        return ["record must be a JSON object"]
    errors: list[str] = []
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not _nonempty(contract.get("transfer_id")):
        errors.append("transfer_id is required")
    status = _text(contract.get("status"))
    if status not in STATUS_VALUES:
        errors.append(f"status must be one of {sorted(STATUS_VALUES)}")
    if pre_transfer and status not in {"planned", "running"}:
        errors.append("before the command status must be planned or running")
    for name in ("source", "destination", "purpose", "motivation", "next_action"):
        if not _nonempty(contract.get(name)):
            errors.append(f"{name} is required")
    if not _valid_deadline(contract.get("deadline")):
        errors.append("deadline must be an ISO-8601 date/time")

    operation = contract.get("operation")
    if not isinstance(operation, dict):
        errors.append("operation must be an object")
    else:
        for name in ("kind", "tool", "settings"):
            if not _nonempty(operation.get(name)):
                errors.append(f"operation.{name} is required")

    verification = contract.get("verification")
    if not isinstance(verification, dict):
        errors.append("verification must be an object")
    else:
        plan = verification.get("plan")
        if not isinstance(plan, list) or not plan or not all(_nonempty(item) for item in plan):
            errors.append("verification.plan must contain at least one check")
        if not isinstance(verification.get("performed"), bool):
            errors.append("verification.performed must be boolean")

    cleanup = contract.get("source_cleanup")
    if not isinstance(cleanup, dict):
        errors.append("source_cleanup must be an object")
    else:
        for name in ("planned", "performed", "verified"):
            if not isinstance(cleanup.get(name), bool):
                errors.append(f"source_cleanup.{name} must be boolean")
        if not _nonempty(cleanup.get("reason")):
            errors.append("source_cleanup.reason is required")

    if status == "verified":
        if not isinstance(verification, dict) or verification.get("performed") is not True:
            errors.append("verified transfer requires verification.performed=true")
        if not isinstance(verification, dict) or _text(verification.get("result")).lower() not in {"pass", "passed", "ok"}:
            errors.append("verified transfer requires verification.result=pass")
        evidence = verification.get("evidence") if isinstance(verification, dict) else None
        if not isinstance(evidence, list) or not evidence or not all(_nonempty(item) for item in evidence):
            errors.append("verified transfer requires non-empty verification.evidence")
        if isinstance(cleanup, dict) and cleanup.get("planned") and not (
            cleanup.get("performed") is True and cleanup.get("verified") is True
        ):
            errors.append("verified transfer requires performed+verified source cleanup when cleanup is planned")

    if status in {"failed", "blocked", "cancelled"} and not _nonempty(contract.get("closure_reason")):
        errors.append(f"{status} transfer requires closure_reason")
    return errors


def _load(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot read {path}: {exc}"
    errors = _contract_errors(value)
    return (value, None) if not errors else (None, "; ".join(errors))


def _tool_matches(operation: dict[str, Any], expected: str) -> bool:
    values = [_text(operation.get("tool")).lower(), _text(operation.get("command_family")).lower()]
    return any(value == expected or expected in value or value in expected for value in values if value)


def _pre(event: dict[str, Any]) -> None:
    tool = _text(event.get("tool_name"))
    if tool not in {"Bash", "PowerShell"}:
        allow()
    command = _text(_tool_input(event).get("command"))
    detected = _transfer_kind(command)
    if detected is None:
        allow()
    cwd = _event_cwd(event)
    marker = TRANSFER_MARKER.search(command)
    if marker is None:
        block(
            "Transfer command detected but no durable contract was provided. "
            "Create .claude/transfers/<id>.json first, then append "
            "'# transfer-contract: .claude/transfers/<id>.json' to the command."
        )
    path = _contract_path(marker.group("path"), cwd)
    if path is None:
        block("Transfer contract path must be a JSON file under .claude/transfers/, .agent/transfers/ or .codex/transfers/.")
    if not path.is_file():
        block(f"Transfer contract does not exist: {path}. Write the contract before starting the transfer.")
    contract, error = _load(path)
    if error or contract is None:
        block(f"Invalid transfer contract {path}: {error}")
    errors = _contract_errors(contract, pre_transfer=True)
    kind, expected_tool = detected
    operation = contract.get("operation", {})
    if _text(operation.get("kind")).lower() != kind:
        errors.append(f"operation.kind={kind!r} is required for this command")
    if not _tool_matches(operation, expected_tool):
        errors.append(f"operation.tool must describe {expected_tool!r} for this command")
    if errors:
        block(f"Transfer contract is incomplete ({path}): " + "; ".join(errors))
    log("INFO", "transfer_contract", "allowed", f"{kind}:{expected_tool}", str(path))
    allow()


def _post(event: dict[str, Any]) -> None:
    tool = _text(event.get("tool_name"))
    if tool not in {"Bash", "PowerShell"}:
        allow()
    command = _text(_tool_input(event).get("command"))
    detected = _transfer_kind(command)
    if detected is None:
        allow()
    response = event.get("tool_response") or {}
    if not isinstance(response, dict):
        response = {}
    failed = bool(response.get("interrupted")) or response.get("exit_code", 0) not in (0, "0", None)
    outcome = "failed" if failed else "verification_pending"
    sys.stderr.write(
        f"[transfer_contract] {outcome}: update the marked contract, verify the destination, "
        "and record source cleanup explicitly before closing the task.\n"
    )
    allow()


def _local_path(value: Any, root: Path) -> Path | None:
    raw = _text(value)
    if not raw or re.match(r"^(?:[a-z]+://|[^\\/\s]+@[^\\/\s:]+:)", raw, re.I):
        return None
    try:
        candidate = Path(raw).expanduser()
        return (candidate if candidate.is_absolute() else root / candidate).resolve()
    except OSError:
        return None


def _verified_path_errors(contract: dict[str, Any], root: Path) -> list[str]:
    if _text(contract.get("status")) != "verified":
        return []
    errors: list[str] = []
    destination = _local_path(contract.get("destination"), root)
    if destination is not None and not destination.exists():
        errors.append(f"destination is absent: {destination}")
    cleanup = contract.get("source_cleanup") or {}
    source = _local_path(contract.get("source"), root)
    if cleanup.get("planned") and cleanup.get("performed") and source is not None and source.exists():
        errors.append(f"source still exists after claimed cleanup: {source}")
    return errors


def _transfer_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in (Path(".claude") / "transfers", Path(".agent") / "transfers", Path(".codex") / "transfers"):
        directory = root / relative
        if directory.is_dir():
            paths.extend(sorted(directory.glob("*.json")))
    return paths


def _stop(event: dict[str, Any]) -> None:
    root = _repo_root(_event_cwd(event))
    issues: list[str] = []
    for path in _transfer_files(root):
        contract, error = _load(path)
        if error or contract is None:
            issues.append(f"{path.name}: {error}")
            continue
        status = _text(contract.get("status"))
        if status in OPEN_STATUSES:
            issues.append(
                f"{path.name}: status={status}; next_action={_text(contract.get('next_action')) or 'missing'}"
            )
        elif status in CLOSED_STATUSES:
            issues.extend(f"{path.name}: {item}" for item in _contract_errors(contract))
            issues.extend(f"{path.name}: {item}" for item in _verified_path_errors(contract, root))
    if issues:
        log("WARN", "transfer_contract", "blocked", "open-or-invalid-transfer", " | ".join(issues))
        block(
            "Open or unverifiable file transfer contracts remain. Finish the transfer, "
            "record verification/source cleanup, or mark the record failed/blocked with "
            "a closure_reason. " + " | ".join(issues[:5])
        )
    allow()


def main() -> None:
    event = read_event()
    if not event:
        allow()
    event_name = _text(event.get("hook_event_name"))
    tool = _text(event.get("tool_name"))
    if event_name == "Stop" or (not tool and "transcript_path" in event):
        _stop(event)
    if event_name == "PostToolUse" or "tool_response" in event:
        _post(event)
    _pre(event)


if __name__ == "__main__":
    main()
