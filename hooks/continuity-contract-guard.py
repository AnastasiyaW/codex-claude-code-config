#!/usr/bin/env python3
"""PreToolUse guard for safe continuation across coding-agent harnesses.

Claude Code and Codex can share the repository, but they do not share the
previous agent's intent.  A small, versionable JSON contract supplies that
missing control-plane state.  This hook protects continuation mode from the
most damaging accidental reset: overwriting an existing tracked file with
Write, expanding outside the declared scope, or replacing a large region.

No contract means no gate for new projects and ordinary one-shot work.  A
repository that already has handoff state must create the contract before
editing existing code; otherwise the handoff would remain advisory only.  A
malformed contract is fail-closed because silently ignoring a declared boundary
is worse than asking for repair.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

CONTRACT_RELATIVE = Path(".claude") / "continuity" / "CONTINUITY.json"
ALT_CONTRACT_RELATIVE = Path(".agent") / "continuity" / "CONTINUITY.json"
INTERNAL_PREFIXES = (
    ".claude/continuity/",
    ".agent/continuity/",
)


def read_event() -> dict[str, Any]:
    try:
        raw = sys.stdin.read().lstrip("\ufeff")
        value = json.loads(raw) if raw.strip() else {}
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def normalize(path: str | Path) -> str:
    value = str(path).replace("\\", "/").lower()
    while value.startswith("./"):
        value = value[2:]
    return value


def has_continuation_state(root: Path) -> bool:
    return any(
        candidate.exists()
        for candidate in (
            root / ".claude" / "handoffs",
            root / ".claude" / "HANDOFF.md",
            root / ".agent" / "handoffs",
        )
    )


def is_internal_continuity_path(root: Path, raw_path: str) -> bool:
    rel = relative_path(root, raw_path)
    return rel is not None and any(rel.startswith(prefix) for prefix in INTERNAL_PREFIXES)


def repo_root_for(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return Path(result.stdout.strip()).resolve()
    except OSError:
        return None


def contract_path(root: Path) -> Path | None:
    configured = os.environ.get("AGENT_CONTINUITY_FILE", "").strip()
    candidates = []
    if configured:
        configured_path = Path(configured)
        candidates.append(
            configured_path if configured_path.is_absolute() else root / configured_path
        )
    candidates.extend((root / CONTRACT_RELATIVE, root / ALT_CONTRACT_RELATIVE))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_contract(root: Path) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    path = contract_path(root)
    if path is None:
        return None, None, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, path, f"invalid continuity contract: {exc}"
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return None, path, "continuity contract must be an object with schema_version=1"
    return value, path, None


def event_paths(event: dict[str, Any]) -> list[str]:
    tool = str(event.get("tool_name") or "")
    if tool not in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        return []
    tool_input = event.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            return []
    if not isinstance(tool_input, dict):
        return []

    paths: list[str] = []
    for key in ("file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if value:
            paths.append(str(value))
    edits = tool_input.get("edits") or []
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict):
                value = edit.get("file_path") or edit.get("path")
                if value:
                    paths.append(str(value))
    return list(dict.fromkeys(paths))


def relative_path(root: Path, raw_path: str) -> str | None:
    try:
        path = Path(raw_path).expanduser().resolve()
        return normalize(path.relative_to(root))
    except (OSError, ValueError):
        return None


def git_status_paths(root: Path) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "-uall"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.rsplit(" -> ", 1)[-1]
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        paths.add(normalize(raw))
    return {p for p in paths if not any(p.startswith(prefix) for prefix in INTERNAL_PREFIXES)}


def is_tracked(root: Path, rel: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def lines(value: object) -> int:
    text = str(value or "")
    return text.count("\n") + (1 if text else 0)


def explicit_replan() -> str | None:
    mode = os.environ.get("AGENT_CONTINUITY_MODE", "").strip().lower()
    reason = os.environ.get("AGENT_CONTINUITY_REASON", "").strip()
    if mode == "replan" and reason:
        return reason
    return None


def scope_files(contract: dict[str, Any]) -> set[str]:
    scope = contract.get("scope")
    if isinstance(scope, dict):
        values = scope.get("files") or scope.get("paths") or []
    else:
        values = contract.get("changed_files") or []
    if not isinstance(values, list):
        return set()
    return {normalize(value) for value in values if isinstance(value, str)}


def should_enforce_scope(contract: dict[str, Any]) -> bool:
    scope = contract.get("scope")
    return isinstance(scope, dict) and bool(scope.get("enforce"))


def protect_unlisted(contract: dict[str, Any]) -> bool:
    scope = contract.get("scope")
    if isinstance(scope, dict) and "protect_unlisted" in scope:
        return bool(scope.get("protect_unlisted"))
    return False


def edit_payload(event: dict[str, Any]) -> list[tuple[str, str, str]]:
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            return []
    if not isinstance(tool_input, dict):
        return []
    if tool == "Edit":
        return [
            (
                str(tool_input.get("file_path") or tool_input.get("path") or ""),
                str(tool_input.get("old_string") or ""),
                str(tool_input.get("new_string") or ""),
            )
        ]
    if tool == "MultiEdit":
        result = []
        for edit in tool_input.get("edits") or []:
            if isinstance(edit, dict):
                result.append(
                    (
                        str(edit.get("file_path") or edit.get("path") or tool_input.get("file_path") or ""),
                        str(edit.get("old_string") or ""),
                        str(edit.get("new_string") or ""),
                    )
                )
        return result
    return []


def decision_for_event(
    event: dict[str, Any],
    root: Path,
    contract: dict[str, Any] | None,
    *,
    existing_status: set[str] | None = None,
    tracked_paths: set[str] | None = None,
) -> tuple[str, str]:
    """Return (allow|block|context, reason) for deterministic tests and wrapper."""
    tool = str(event.get("tool_name") or "")
    paths = event_paths(event)
    if not paths:
        return "allow", ""
    if contract is None:
        if has_continuation_state(root) and any(
            not is_internal_continuity_path(root, raw) for raw in paths
        ):
            return "block", (
                "This repository already has handoff state but no CONTINUITY.json. "
                "Create .claude/continuity/CONTINUITY.json from the current Git baseline "
                "before editing existing code; this prevents Claude/Codex from silently "
                "restarting the implementation."
            )
        return "context", (
            "[continuity] No CONTINUITY.json found for this repository. "
            "For Claude/Codex handoff work, create the shared contract before editing."
        )
    mode = str(contract.get("mode") or "continuation").lower()
    if mode in {"new", "greenfield"}:
        return "allow", ""
    if mode != "continuation":
        return "block", f"unsupported continuity mode '{mode}'; repair CONTINUITY.json"

    reason = explicit_replan()
    if reason:
        return "context", f"[continuity] Explicit replan mode enabled: {reason}"

    rel_paths = [relative_path(root, raw) for raw in paths]
    if any(rel is None for rel in rel_paths):
        return "block", "Continuation contract cannot protect a path outside the active Git repository"
    normalized_paths = [rel for rel in rel_paths if rel is not None]

    if should_enforce_scope(contract):
        allowed = scope_files(contract)
        # Сам контракт под охрану не попадает. Без этого он запрещает дополнять себя:
        # объём проверяется по СТАРОЙ редакции, значит добавить в неё собственный путь
        # уже нельзя, и единственным выходом остаётся обойти хук. Помощник
        # `is_internal_continuity_path` для этого и заведён — выше он применяется в ветке
        # «контракта нет», здесь его не хватало. Замечено 25.08.2026 на попытке расширить
        # объём после согласованной передачи файлов.
        outside = [rel for rel in normalized_paths
                   if rel not in allowed
                   and not any(rel.startswith(prefix) for prefix in INTERNAL_PREFIXES)]
        if outside:
            return "block", (
                "Continuation scope violation: these paths are outside the declared scope: "
                + ", ".join(outside)
                + ". Extend the contract or explicitly start replan mode."
            )

    current_status = existing_status if existing_status is not None else git_status_paths(root)
    baseline = contract.get("baseline") or {}
    baseline_paths = {
        normalize(value)
        for value in baseline.get("preexisting_paths", [])
        if isinstance(value, str)
    }
    if protect_unlisted(contract):
        allowed = scope_files(contract)
        unexplained = [
            rel for rel in sorted(baseline_paths & current_status)
            if rel not in allowed and rel in normalized_paths
        ]
        if unexplained:
            return "block", (
                "Continuation would modify pre-existing work outside the approved files: "
                + ", ".join(unexplained)
                + ". Preserve it, claim it in the contract, or explicitly replan."
            )

    tracked = tracked_paths if tracked_paths is not None else {
        rel for rel in normalized_paths if is_tracked(root, rel)
    }
    if tool == "Write":
        existing = [rel for rel in normalized_paths if rel in tracked]
        if existing:
            return "block", (
                "Continuation guard blocks Write over existing tracked file(s): "
                + ", ".join(existing)
                + ". Use a focused Edit or explicitly start replan mode; this prevents silent rewrites."
            )

    if tool in {"Edit", "MultiEdit"}:
        payloads = edit_payload(event)
        max_old = max((lines(old) for _, old, _ in payloads), default=0)
        if max_old >= 200:
            return "block", (
                f"Continuation guard blocks a large replacement ({max_old} old lines). "
                "Split it into focused edits or explicitly start replan mode."
            )
        for raw_path, old, new in payloads:
            rel = relative_path(root, raw_path) if raw_path else None
            if rel is None or not old:
                continue
            try:
                current_lines = len((root / rel).read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                current_lines = 0
            old_count = lines(old)
            if current_lines >= 100 and old_count >= 80 and old_count / current_lines >= 0.75:
                return "block", (
                    f"Continuation guard blocks a near-whole-file replacement in {rel} "
                    f"({old_count}/{current_lines} lines). Split the change or explicitly replan."
                )

    return "allow", ""


def emit(decision: str, reason: str) -> None:
    if decision == "block":
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    elif decision == "context":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": reason,
            }
        }, ensure_ascii=False))


def main() -> int:
    event = read_event()
    raw_paths = event_paths(event)
    if not raw_paths:
        return 0
    root = repo_root_for(Path(raw_paths[0]).expanduser())
    if root is None:
        return 0
    contract, path, error = load_contract(root)
    if error:
        # A malformed contract must not block repairing the contract. The missing-contract
        # branch below already exempts these paths; without the same exemption here, the
        # only way out of a bad contract was to write it with something other than the
        # edit tools -- which is how a guard teaches people to route around it. Found
        # 2026-08-04 while bootstrapping a contract in a fresh worktree.
        if all(is_internal_continuity_path(root, raw) for raw in raw_paths):
            emit("context", f"[continuity] repairing an invalid contract: {error}")
            return 0
        emit("block", f"{error} at {path}")
        return 0
    decision, reason = decision_for_event(event, root, contract)
    emit(decision, reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
