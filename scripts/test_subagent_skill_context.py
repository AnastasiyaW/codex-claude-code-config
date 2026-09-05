"""Regression proof for the Codex SubagentStart evidence/skill context hook."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HOOK = Path(__file__).resolve().parent.parent / "hooks" / "subagent-skill-context.py"


def invoke(event: dict) -> str:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def main() -> int:
    raw = invoke({"hook_event_name": "SubagentStart", "agent_id": "child-1"})
    payload = json.loads(raw)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
    assert "smallest available skill set" in context
    assert "Memory and earlier assistant text are search leads" in context
    assert "explicit user instructions outrank a skill's methodology" in context
    assert "name the exact skill and" in context
    assert "A skill preference is not BLOCKED_EXTERNAL evidence" in context
    assert "send a bounded skill-search task" in context
    assert "agent-skill-install-checklist.md" in context
    assert "research-backed" in context and "BUILD_RESEARCHED" in context
    assert "baseline" in context and "held-out" in context
    assert "update triggers" in context and "rollback" in context
    assert "Skill disposition:" in context
    assert "INCONCLUSIVE" in context
    assert invoke({"hook_event_name": "SessionStart"}) == ""
    print("test_subagent_skill_context: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
