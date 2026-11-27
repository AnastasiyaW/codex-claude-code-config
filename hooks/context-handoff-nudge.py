#!/usr/bin/env python3
"""Tell the agent to write a handoff before the app auto-compacts the chat.

The app compacts by itself at `autoCompactWindow` (settings.json, 500k on this
machine, owner 2026-11-01). A hook cannot type /compact, so this hook covers the
other half: once the context is near that window and no fresh handoff exists,
it injects an instruction to write one now. PostToolUse and UserPromptSubmit.
Never blocks; prints nothing below the threshold.
"""
import json
import os
import sys
import time
from pathlib import Path

# 60k below the 500k window: room for the handoff turn itself.
NUDGE_AT = int(os.environ.get("CLAUDE_HANDOFF_NUDGE_TOKENS", "440000"))
HANDOFF_FRESH_MINUTES = 25  # same value as precompact-handoff-guard.py
REPEAT_MINUTES = 15
TAIL_BYTES = 4 * 1024 * 1024
STATE_DIR = Path.home() / ".claude" / "state" / "handoff-nudge"


def context_tokens(transcript: Path) -> int | None:
    with transcript.open("rb") as f:
        f.seek(max(0, transcript.stat().st_size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") != "assistant" or o.get("isSidechain"):
            continue
        u = (o.get("message") or {}).get("usage")
        if u:
            return sum(int(u.get(k) or 0) for k in
                       ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return None


def fresh_handoff(cwd: Path, now: float) -> bool:
    root = cwd / ".claude" / "handoffs"
    limit = now - HANDOFF_FRESH_MINUTES * 60
    return root.is_dir() and any(p.stat().st_mtime >= limit for p in root.rglob("*.md")
                                 if p.name != "INDEX.md")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    transcript = Path(data.get("transcript_path") or "")
    if not transcript.is_file():
        return 0
    tokens = context_tokens(transcript)
    if tokens is None or tokens < NUDGE_AT:
        return 0
    now = time.time()
    if fresh_handoff(Path(data.get("cwd") or os.getcwd()), now):
        return 0
    mark = STATE_DIR / f"{data.get('session_id', 'unknown')}.last"
    if mark.exists() and now - mark.stat().st_mtime < REPEAT_MINUTES * 60:
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    mark.touch()
    msg = (f"[handoff-nudge] Context is about {tokens // 1000}k tokens; the app auto-compacts at the "
           "500k window. Write the session handoff NOW (session-handoff.md format with Closure Audit, "
           "into <cwd>/.claude/handoffs/<project>/ plus an INDEX line), then continue the task.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": data.get("hook_event_name") or "PostToolUse",
        "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
