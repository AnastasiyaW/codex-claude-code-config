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
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safety_common import allow, block, log, read_event  # noqa: E402

# One definition of "what in this command can actually run", shared with the
# destructive guards. This copy is the one settings.json registers - a second,
# divergent copy under ~/.claude/hooks/ received an earlier repair and never
# ran, which an independent review caught by reading the manifest rather than
# the file. A swallowed ImportError here would repeat exactly that, so it is
# announced instead: a guard that quietly loses a security helper is a guard
# that is not there.
try:
    from safety_common import executable_text as _executable_text  # noqa: E402
except ImportError as error:  # pragma: no cover - deployment fault, not logic
    print(f"[transfer-contract-guard] safety_common.executable_text is missing "
          f"({error}); scanning the RAW command text, which over-blocks on "
          f"quoted and commented mentions.", file=sys.stderr)
    _executable_text = None


# Transfer records live in one shared directory, but a Stop gate belongs to one
# session. Without an owner, session A is blocked by session B's in-flight
# record -- collateral, and the usual answer to collateral is to switch the gate
# off. So a record records who opened it, and a live owner's open record only
# warns the others. Ownership is stamped automatically at PreToolUse; a record
# with no owner still blocks everyone, so this cannot become a silent escape.
SESSION_ROOT = Path(
    os.environ.get("CLAUDE_SESSION_ROOT")
    or (Path.home() / ".claude" / "projects")
)
# A live session's transcript is appended to continuously. Half an hour of
# silence means the owner is not going to close this record on its own.
FOREIGN_LIVE_SECONDS = int(os.environ.get("CLAUDE_TRANSFER_OWNER_TTL", "1800"))

# Ownership helpers now live in safety_common so both Stop gates share one
# definition; a second copy would drift and only one would get the next fix.
try:
    from safety_common import (  # noqa: E402
        same_session as _same_session,
        session_alive as _session_alive,
        transcripts_for as _transcripts_for,
    )
except ImportError:  # fail CLOSED: unknown liveness must never downgrade a block
    def _transcripts_for(session_id: str) -> list:
        return []

    def _same_session(a: str, b: str) -> bool:
        return True

    def _session_alive(session_id: str, now: float | None = None) -> bool:
        return False



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


def _event_session(event: dict[str, Any]) -> str:
    """Session id, however this harness spells it.

    Falls back to the transcript filename, which IS the session id and is
    present on every Stop event -- so ownership does not hinge on one key name.
    """
    for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
        value = _text(event.get(key))
        if value:
            return value
    transcript = _text(event.get("transcript_path"))
    if transcript:
        stem = Path(transcript).stem
        if stem and stem not in {".", ".."}:
            return stem
    # Last resort, and the only one that survives a payload that did not parse:
    # measured 2026-08-10, the harness exports CLAUDE_CODE_SESSION_ID into every
    # hook process. Ownership therefore does not depend on the event at all.
    return _text(os.environ.get("CLAUDE_CODE_SESSION_ID"))





def _foreign_and_live(contract: dict[str, Any], current_session: str) -> str:
    """Owner id when this record belongs to a different, still-live session.

    `opened_by` counts too. The stamp writes `session_id`, but a record opened by
    hand names its opener in `opened_by` - and reading only one key made those
    records look ownerless, so a peer's finished-but-old-shaped contract blocked
    every other session instead of only its own.
    """
    owner = _text(contract.get("session_id")) or _text(contract.get("opened_by"))
    if not owner or _same_session(owner, current_session):
        return ""
    return owner if _session_alive(owner) else ""


def _stamp_owner(path: Path, contract: dict[str, Any], session_id: str) -> None:
    """Record who opened this transfer, so its Stop gate is scoped to them."""
    if not session_id or _text(contract.get("session_id")):
        return
    try:
        contract["session_id"] = session_id
        path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        # Ownership is an optimisation for other sessions' Stop gates. Failing
        # to write it must never turn into a blocked transfer.
        pass


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
    # Read what executes, not what is written: a `grep` for the word rsync, a
    # comment mentioning scp, and a here-doc documenting an rsync flag are not
    # transfers. A here-doc piped into `bash -s` over ssh is one, and stays in
    # scope. See safety_common.executable_text for the rule and its limits.
    if _executable_text is not None:
        command = _executable_text(command)
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
    _stamp_owner(path, contract, _event_session(event))
    log("INFO", "transfer_contract", "allowed", f"{kind}:{expected_tool}", str(path))
    allow()


def _stamp_written_contract(event: dict[str, Any]) -> bool:
    """Give a freshly written contract its owner, before any transfer runs.

    Stamping only at PreToolUse left a gap: a session that writes the record and
    then works for a while owns nothing on paper, so its in-flight record blocks
    every sibling session's Stop gate. Hit twice on 2026-08-09/10. The record is
    created by Write/Edit, so that is where ownership should be established.
    """
    if _text(event.get("tool_name")) not in {"Write", "Edit", "MultiEdit"}:
        return False
    raw = _text(_tool_input(event).get("file_path"))
    if not raw:
        return False
    path = _contract_path(raw, _event_cwd(event))
    if path is None or not path.is_file():
        return False
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(contract, dict):
        return False
    _stamp_owner(path, contract, _event_session(event))
    return True


def _post(event: dict[str, Any]) -> None:
    _stamp_written_contract(event)
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


def _stop_issues(root: Path, current_session: str) -> tuple[list[str], list[str]]:
    """Return (blocking issues for this session, notes about other sessions')."""
    issues: list[str] = []
    deferred: list[str] = []
    for path in _transfer_files(root):
        contract, error = _load(path)
        if error or contract is None:
            # A record too broken to parse has no readable owner, so it is
            # everyone's problem until someone repairs it.
            issues.append(f"{path.name}: {error}")
            continue
        owner = _foreign_and_live(contract, current_session)
        status = _text(contract.get("status"))
        if owner:
            if status in OPEN_STATUSES or _contract_errors(contract) or _verified_path_errors(contract, root):
                deferred.append(f"{path.name} (status={status}, owner session {owner} still live)")
            continue
        if status in OPEN_STATUSES:
            issues.append(
                f"{path.name}: status={status}; next_action={_text(contract.get('next_action')) or 'missing'}"
            )
        elif status in CLOSED_STATUSES:
            issues.extend(f"{path.name}: {item}" for item in _contract_errors(contract))
            issues.extend(f"{path.name}: {item}" for item in _verified_path_errors(contract, root))
    return issues, deferred


def _stop(event: dict[str, Any]) -> None:
    root = _repo_root(_event_cwd(event))
    issues, deferred = _stop_issues(root, _event_session(event))
    if deferred:
        sys.stderr.write(
            "[transfer_contract] left to their owners (live sessions, not yours): "
            + " | ".join(deferred)
            + "\n"
        )
    if issues:
        log("WARN", "transfer_contract", "blocked", "open-or-invalid-transfer", " | ".join(issues))
        block(
            "Open or unverifiable file transfer contracts remain. Finish the transfer, "
            "record verification/source cleanup, or mark the record failed/blocked with "
            "a closure_reason. " + " | ".join(issues[:5])
        )
    allow()


def _self_test() -> int:
    """Prove the ownership rule on real files in a real temp tree."""
    import tempfile

    global SESSION_ROOT
    fails: list[str] = []
    base_contract = {
        "schema_version": 1,
        "transfer_id": "t",
        "status": "planned",
        "source": "ssh://host/src",
        "destination": "rclone://remote:dst",
        "purpose": "p",
        "motivation": "m",
        "next_action": "n",
        "deadline": "2026-08-10T00:00:00+03:00",
        "operation": {"kind": "copy", "tool": "rclone", "settings": "s"},
        "verification": {"plan": ["check"], "performed": False},
        "source_cleanup": {"planned": False, "performed": False, "verified": False, "reason": "r"},
    }

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        sessions = tmp / "projects"
        (sessions / "slug").mkdir(parents=True)
        SESSION_ROOT = sessions
        # the shared helper resolves the root per call from the env,
        # so the seam this test relies on has to be set there too
        os.environ["CLAUDE_SESSION_ROOT"] = str(sessions)
        live, stale, mine = "live-owner", "stale-owner", "my-session"
        (sessions / "slug" / f"{live}.jsonl").write_text("{}", encoding="utf-8")
        old = sessions / "slug" / f"{stale}.jsonl"
        old.write_text("{}", encoding="utf-8")
        ancient = time.time() - FOREIGN_LIVE_SECONDS - 600
        os.utime(old, (ancient, ancient))

        repo = tmp / "repo"
        transfers = repo / ".claude" / "transfers"
        transfers.mkdir(parents=True)

        def put(name: str, **over: Any) -> Path:
            record = json.loads(json.dumps(base_contract))
            record.update(over)
            path = transfers / f"{name}.json"
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return path

        cases = [
            ("open record owned by me", {"session_id": mine}, True),
            ("open record, owner still live", {"session_id": live}, False),
            ("open record, owner gone stale", {"session_id": stale}, True),
            ("open record with no owner at all", {}, True),
            ("closed record, owner live", {"session_id": live, "status": "cancelled",
                                           "closure_reason": "c"}, False),
            # A record opened by hand names its opener in `opened_by`. Reading
            # only `session_id` made it look ownerless, so one peer's record
            # blocked every other session's Stop instead of only its owner's.
            ("open record, opened_by a live session", {"opened_by": live}, False),
            ("open record, opened_by a stale session", {"opened_by": stale}, True),
            ("open record, opened_by me", {"opened_by": mine}, True),
        ]
        for label, over, should_block in cases:
            for leftover in transfers.glob("*.json"):
                leftover.unlink()
            put("case", **over)
            issues, deferred = _stop_issues(repo, mine)
            if bool(issues) != should_block:
                fails.append(f"{label}: expected block={should_block}, issues={issues}, deferred={deferred}")

        # A malformed record has no readable owner and must block everyone.
        for leftover in transfers.glob("*.json"):
            leftover.unlink()
        (transfers / "broken.json").write_text("{not json", encoding="utf-8")
        if not _stop_issues(repo, mine)[0]:
            fails.append("unparseable record did not block")

        # A closed record whose own schema is broken must still block its owner.
        for leftover in transfers.glob("*.json"):
            leftover.unlink()
        path = put("mine-broken", session_id=mine, status="verified")
        if not _stop_issues(repo, mine)[0]:
            fails.append("verified record without evidence did not block its owner")

        # Stamping: writes once, never overwrites an existing owner.
        for leftover in transfers.glob("*.json"):
            leftover.unlink()
        path = put("stamp")
        record = json.loads(path.read_text(encoding="utf-8"))
        _stamp_owner(path, record, mine)
        if json.loads(path.read_text(encoding="utf-8")).get("session_id") != mine:
            fails.append("owner was not stamped onto an unowned record")
        _stamp_owner(path, json.loads(path.read_text(encoding="utf-8")), "someone-else")
        if json.loads(path.read_text(encoding="utf-8")).get("session_id") != mine:
            fails.append("existing owner was overwritten")

        # Writing a contract must establish ownership, whether or not a transfer
        # command ever runs -- that gap is what wedged sibling sessions twice.
        for leftover in transfers.glob("*.json"):
            leftover.unlink()
        written = put("written")
        event = {"tool_name": "Write", "session_id": mine, "cwd": str(repo),
                 "tool_input": {"file_path": str(written)}}
        if not _stamp_written_contract(event):
            fails.append("writing a contract was not recognised as a stamping opportunity")
        if json.loads(written.read_text(encoding="utf-8")).get("session_id") != mine:
            fails.append("a contract written by Write was left without an owner")
        for label, bad_event in (
            ("a file outside transfers/", {"tool_name": "Write", "session_id": mine,
                                           "cwd": str(repo),
                                           "tool_input": {"file_path": str(repo / "notes.json")}}),
            ("a non-write tool", {"tool_name": "Read", "session_id": mine, "cwd": str(repo),
                                  "tool_input": {"file_path": str(written)}}),
            ("no path at all", {"tool_name": "Write", "session_id": mine, "cwd": str(repo),
                                "tool_input": {}}),
        ):
            if _stamp_written_contract(bad_event):
                fails.append(f"{label} was treated as a contract write")

        if _session_alive("no-such-session"):
            fails.append("an unknown session was reported alive")
        if _session_alive("../escape"):
            fails.append("a path-traversing session id was not rejected")

        # The id must survive whichever key this harness uses, including the
        # transcript-filename fallback that Stop events always carry.
        saved_env = os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        try:
            for label, event, expected in (
                ("snake_case", {"session_id": mine}, mine),
                ("camelCase", {"sessionId": mine}, mine),
                ("transcript fallback", {"transcript_path": f"/x/y/{mine}.jsonl"}, mine),
                ("nothing usable, no env", {"transcript_path": ""}, ""),
            ):
                got = _event_session(event)
                if got != expected:
                    fails.append(f"session id from {label}: expected {expected!r}, got {got!r}")
            # The env var is what survives a payload that did not parse, but it
            # must never outrank an id the event actually carried.
            os.environ["CLAUDE_CODE_SESSION_ID"] = "env-owner"
            if _event_session({}) != "env-owner":
                fails.append("env fallback did not supply the session id for an empty event")
            if _event_session({"session_id": mine}) != mine:
                fails.append("env fallback overrode an id present in the event")
        finally:
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            if saved_env is not None:
                os.environ["CLAUDE_CODE_SESSION_ID"] = saved_env

    for line in fails:
        print("FAIL:", line)
    print("transfer-contract-guard self-test:", "FAILED" if fails else "ok")
    return 1 if fails else 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
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
