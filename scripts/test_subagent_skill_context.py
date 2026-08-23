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
    assert "INCONCLUSIVE" in context
    assert invoke({"hook_event_name": "SessionStart"}) == ""
    print("test_subagent_skill_context: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
