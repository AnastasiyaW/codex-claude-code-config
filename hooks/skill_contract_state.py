#!/usr/bin/env python3
"""Small, fail-closed state bridge for Codex subagent skill contracts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


STATE_VERSION = 1
STATE_DIR_ENV = "CODEX_SKILL_CONTRACT_STATE_DIR"


def state_root() -> Path:
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex" / "state" / "agent-skill-contracts"


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pending_path(session_id: str, tool_use_id: str) -> Path:
    return state_root() / _key(session_id) / "pending" / f"{_key(tool_use_id)}.json"


def agent_path(session_id: str, agent_id: str) -> Path:
    return state_root() / _key(session_id) / "agents" / f"{_key(agent_id)}.json"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("state_version") != STATE_VERSION:
        return None
    return payload


def save_pending(session_id: str, tool_use_id: str, payload: dict) -> None:
    write_json(
        pending_path(session_id, tool_use_id),
        {"state_version": STATE_VERSION, **payload},
    )


def bind_agent(session_id: str, tool_use_id: str, agent_id: str) -> bool:
    pending = read_json(pending_path(session_id, tool_use_id))
    if pending is None:
        return False
    pending["agent_id"] = agent_id
    write_json(agent_path(session_id, agent_id), pending)
    return True


def load_agent(session_id: str, agent_id: str) -> dict | None:
    return read_json(agent_path(session_id, agent_id))
