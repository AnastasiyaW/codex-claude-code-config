#!/usr/bin/env python3
"""Codex SubagentStart: add skill routing and evidence discipline to every child.

Codex's documented SubagentStart event provides the child identity and profile,
not the parent's task prompt.  It therefore cannot honestly choose a named
skill or stop the launch.  It can, however, inject a compact, universal
instruction that requires each child to choose the smallest relevant skill and
to keep decisions tied to current sources.
"""
from __future__ import annotations

import json
import sys


CONTEXT = """<subagent-skill-and-evidence-context>
Before the first material action, identify the smallest available skill set that
matches this assigned task and read each selected SKILL.md. Do not load every
skill; if no skill matches, say so explicitly. For a factual or technical
decision, use a current repository observation, probe, primary documentation,
or explicit user constraint. Memory and earlier assistant text are search leads,
not confirmation. If no source is available, retrieve one or return
INCONCLUSIVE; do not agree merely because a premise was asserted. For an
explicit request to challenge a claim, use epistemic-challenge when available.
Finish with exactly one receipt: `Decision basis: OBSERVED | PRIMARY_DOC |
USER_CONSTRAINT | INCONCLUSIVE | NO_DECISION`, followed by `Evidence: <current
command/path/URL; for USER_CONSTRAINT use `user request: <exact constraint>`;
or N/A only for NO_DECISION>`. Never use MEMORY as a basis.
</subagent-skill-and-evidence-context>"""


def main() -> int:
    try:
        event = json.loads(sys.stdin.read().lstrip("\ufeff"))
    except (json.JSONDecodeError, EOFError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "SubagentStart":
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": CONTEXT,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
