#!/usr/bin/env python3
"""PreCompact hook: ensure a handoff exists across the compaction boundary.

Fires right before context compaction (Claude Code `PreCompact` event),
which is exactly the "context overflow" moment. Auto-compaction summarizes
the conversation and discards raw detail — if no fresh handoff was written,
nuanced state (paths, decisions, what-did-NOT-work) is lost.

What it does:
  - On `auto` (and `manual`) compaction, check for a FRESH handoff in
    <cwd>/.claude/handoffs/**/*.md (written within HANDOFF_FRESH_MINUTES).
  - If a fresh handoff exists -> print a short OK note, exit 0.
  - If NOT -> drop a marker file <cwd>/.claude/.precompact-handoff-needed
    AND write an AUTO-DRAFT handoff from the local Codex session log when
    available (best-effort fallback, not a semantic replacement)
    AND print a strong reminder to stdout (added to the compaction context),
    so the post-compact turn writes a handoff immediately.

The marker is surfaced again by session-handoff-check.py at the next
SessionStart (which also runs with source=compact right after auto-compact),
giving belt-and-suspenders coverage regardless of how a given Claude Code
version forwards PreCompact stdout.

Non-blocking by design: compaction cannot/should not be vetoed — the goal is
to guarantee the handoff gets written around it, not to stop it.

Register in ~/.claude/settings.json:
{
  "hooks": {
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "python path/to/precompact-handoff-guard.py",
        "statusMessage": "Ensuring handoff before context compaction..."
      }]
    }]
  }
}
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

# A handoff written within this window counts as "fresh" for this compaction.
HANDOFF_FRESH_MINUTES = 25
MARKER_NAME = ".precompact-handoff-needed"
AUTO_PROJECT_SLUG = "codex-auto"
MAX_RECENT_ITEMS = 8
MAX_TOOL_ITEMS = 12
MAX_SNIPPET_CHARS = 360

SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|sk-proj|gh[pousr]|rpa|xox[baprs])_[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b", re.I),
)


def read_event() -> dict:
    try:
        raw = sys.stdin.read()
        raw = raw.lstrip("\ufeff")
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def sanitize_snippet(value: object, limit: int = MAX_SNIPPET_CHARS) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    for pat in SECRET_PATTERNS:
        text = pat.sub("[redacted-token]", text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "..."
    return text


def append_unique(items: deque[str], value: object) -> None:
    text = sanitize_snippet(value)
    if text and (not items or items[-1] != text):
        items.append(text)


def extract_message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"input_text", "output_text", "text"}:
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts)


def session_id_from_event(event: dict) -> str | None:
    for key in ("session_id", "sessionId", "conversation_id", "conversationId", "thread_id", "threadId"):
        value = event.get(key)
        if value:
            return str(value)
    return None


def read_session_meta(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(120):
                line = f.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "session_meta":
                    payload = obj.get("payload")
                    return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def find_codex_session_log(event: dict, cwd: Path) -> Path | None:
    transcript = event.get("transcript_path") or event.get("transcriptPath")
    if transcript:
        p = Path(str(transcript)).expanduser()
        if p.exists():
            return p

    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        return None

    try:
        candidates = sorted(
            sessions_dir.rglob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:80]
    except Exception:
        return None

    sid = session_id_from_event(event)
    if sid:
        for p in candidates:
            if sid in p.name:
                return p
        for p in candidates:
            if read_session_meta(p).get("id") == sid:
                return p

    cwd_norm = str(cwd).replace("/", "\\").lower()
    for p in candidates:
        meta_cwd = str(read_session_meta(p).get("cwd") or "").replace("/", "\\").lower()
        if meta_cwd and meta_cwd == cwd_norm:
            return p
    return candidates[0] if candidates else None


def summarize_codex_log(path: Path | None) -> dict:
    result = {
        "meta": {},
        "recent_users": deque(maxlen=MAX_RECENT_ITEMS),
        "recent_assistants": deque(maxlen=MAX_RECENT_ITEMS),
        "recent_tools": deque(maxlen=MAX_TOOL_ITEMS),
    }
    if not path or not path.exists():
        return result

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                typ = obj.get("type")
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}

                if typ == "session_meta":
                    result["meta"] = payload
                    continue

                if typ == "event_msg":
                    ptype = payload.get("type")
                    msg = payload.get("message")
                    if ptype == "user_message":
                        append_unique(result["recent_users"], msg)
                    elif ptype == "agent_message" and isinstance(msg, str):
                        if msg.startswith("[external_agent_tool_call"):
                            append_unique(result["recent_tools"], msg)
                        elif not msg.startswith("[external_agent_tool_result"):
                            append_unique(result["recent_assistants"], msg)
                    continue

                if typ == "response_item":
                    rtype = payload.get("type")
                    if rtype == "function_call":
                        name = payload.get("name") or "tool"
                        append_unique(
                            result["recent_tools"],
                            f"{name}: {payload.get('arguments') or ''}",
                        )
                    elif rtype == "message":
                        role = payload.get("role")
                        text = extract_message_text(payload.get("content"))
                        if role == "user":
                            append_unique(result["recent_users"], text)
                        elif role == "assistant":
                            append_unique(result["recent_assistants"], text)
    except Exception:
        pass
    return result


def bullet_lines(items: object, empty: str) -> str:
    values = list(items or [])
    if not values:
        return f"- {empty}"
    return "\n".join(f"- {v}" for v in values)


def next_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 100):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{int(time.time())}{suffix}")


def write_auto_handoff_draft(event: dict, cwd: Path, claude_dir: Path, age: float | None) -> Path | None:
    handoffs_root = claude_dir / "handoffs"
    target_dir = handoffs_root / AUTO_PROJECT_SLUG
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    log_path = find_codex_session_log(event, cwd)
    summary = summarize_codex_log(log_path)
    meta = summary.get("meta") if isinstance(summary.get("meta"), dict) else {}
    sid = session_id_from_event(event) or str(meta.get("id") or "unknown-session")
    short_sid = re.sub(r"[^A-Za-z0-9_-]", "", sid)[:8] or "autosave"
    now_file = time.strftime("%Y-%m-%d_%H-%M")
    now_text = time.strftime("%Y-%m-%d %H:%M")
    target = next_unique_path(target_dir / f"{now_file}_{short_sid}-auto.md")

    source = str(log_path) if log_path else "Codex session log not found"
    newest = "none" if age is None else f"{int(age)} min old"
    body = f"""# Auto Session Handoff - {now_text}

**Session ID:** {sid}
**Status:** AUTO-DRAFT
**Working directory:** {cwd}
**Project:** {AUTO_PROJECT_SLUG}
**Source log:** {source}

## Goal
Auto-inferred from recent user messages:
{bullet_lines(summary.get("recent_users"), "No recent user messages found in the local session log.")}

## Done
Automatic fallback captured recent assistant updates:
{bullet_lines(summary.get("recent_assistants"), "No assistant progress messages found in the local session log.")}

## What did NOT work (and why)
- A semantic handoff was not fresh at compaction time; newest handoff before this auto-draft: {newest}.
- This file is generated mechanically from the Codex JSONL log. It may miss decisions, exact diffs, verification results, and background task state.

## Current state
- Context reached `PreCompact`; this file exists so the next chat has a durable transfer artifact.
- `session-handoff-check.py` should surface this file on the next SessionStart.
- Prefer a human-quality handoff written by the agent if one appears later.

## Key decisions
- Preserve transfer context first; quality refinement can happen immediately after compaction.
- Do not treat this AUTO-DRAFT as final proof of completed work.

## Single next step
Read this auto-draft, inspect the working tree and latest tool outputs, then write or supersede it with a normal handoff before continuing substantial work.

## Recent tool calls
{bullet_lines(summary.get("recent_tools"), "No recent tool calls found in the local session log.")}
"""
    try:
        target.write_text(body, encoding="utf-8")
        index = handoffs_root / "INDEX.md"
        if not index.exists():
            index.write_text("# Handoffs Index\n\n", encoding="utf-8")
        with index.open("a", encoding="utf-8") as f:
            f.write(
                f"- {time.strftime('%Y-%m-%d %H:%M')} | {short_sid} | "
                f"{AUTO_PROJECT_SLUG} | AUTO-DRAFT before context compaction | AUTO-DRAFT\n"
            )
        return target
    except Exception:
        return None


# Handoff filenames carry their own timestamp: YYYY-MM-DD_HH-MM_<session>.md
_FILENAME_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})[_T](\d{2})[-:](\d{2})")


def _age_from_filename(path: Path) -> float | None:
    """Minutes since the timestamp encoded in the filename, or None if absent."""
    m = _FILENAME_TS.search(path.name)
    if not m:
        return None
    try:
        stamp = datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None
    return (datetime.now() - stamp).total_seconds() / 60


def newest_handoff_age_minutes(handoffs_dir: Path, handoff_old: Path) -> float | None:
    """Minutes since the most recent handoff was written, or None if none.

    Age comes from the timestamp in the FILENAME where there is one. mtime is
    forgeable by ordinary work: a merge, checkout or sync rewrites it on every
    handoff it touches, and a restored handoff from months ago would then read
    as just-written. Here that matters more than anywhere else -- this guard
    runs while the conversation is being compacted, so a false "fresh" means
    the session's state is discarded with nothing written down.
    """
    now = time.time()
    best: float | None = None
    if handoffs_dir.exists():
        for p in handoffs_dir.rglob("*.md"):
            if p.name == "INDEX.md":
                continue
            age = _age_from_filename(p)
            if age is None:
                age = (now - p.stat().st_mtime) / 60
            if best is None or age < best:
                best = age
    if handoff_old.exists():
        age = (now - handoff_old.stat().st_mtime) / 60
        if best is None or age < best:
            best = age
    return best


def main() -> int:
    event = read_event()
    trigger = str(event.get("trigger", "auto"))

    cwd = Path(event.get("cwd") or ".").expanduser()
    claude_dir = cwd / ".claude"
    if not claude_dir.exists():
        return 0  # not a Claude Code project

    handoffs_dir = claude_dir / "handoffs"
    handoff_old = claude_dir / "HANDOFF.md"
    marker = claude_dir / MARKER_NAME

    age = newest_handoff_age_minutes(handoffs_dir, handoff_old)
    fresh = age is not None and age < HANDOFF_FRESH_MINUTES

    if fresh:
        # Good — a handoff already captures current state. Clear any stale marker.
        try:
            if marker.exists():
                marker.unlink()
        except Exception:
            pass
        print(
            f"[precompact] OK: fresh handoff exists ({int(age)} min old). "
            f"State preserved across compaction."
        )
        return 0

    # No fresh handoff at the overflow moment — create a best-effort draft,
    # record it, and shout so the agent upgrades it after compaction.
    auto_handoff = write_auto_handoff_draft(event, cwd, claude_dir, age)
    try:
        marker_info = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "trigger": trigger,
            "newest_handoff_min": None if age is None else int(age),
        }
        if auto_handoff:
            marker_info["auto_handoff"] = str(auto_handoff)
        marker.write_text(json.dumps(marker_info), encoding="utf-8")
    except Exception:
        pass

    auto_line = (
        f"AUTO-DRAFT written: {auto_handoff}\n"
        if auto_handoff
        else "AUTO-DRAFT could not be written; write the handoff manually.\n"
    )
    print(
        "=" * 60 + "\n"
        "[precompact] CONTEXT IS BEING COMPACTED — NO FRESH HANDOFF.\n"
        + "=" * 60 + "\n"
        + auto_line
        + f"Trigger: {trigger}. The raw conversation detail is about to be "
        "summarized away.\n"
        "IMMEDIATELY after compaction, before any other work, write a handoff "
        "to .claude/handoffs/<project-slug>/YYYY-MM-DD_HH-MM_<session-short-id>.md "
        "(format: .claude/rules/session-handoff.md; <=1500 tokens; goal / done / "
        "what did NOT work / current state / key decisions / single next step) "
        "and append one line to .claude/handoffs/INDEX.md. "
        "This is the near-overflow exception in finish-the-task.md.\n"
        + "=" * 60
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
