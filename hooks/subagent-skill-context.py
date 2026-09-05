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
The assigned task and explicit user instructions outrank a skill's methodology.
Apply skills inside that scope; do not let a skill silently narrow, redirect,
pause, or add an approval boundary to the requested outcome. If a skill
instruction genuinely causes a pause or divergence, name the exact skill and
instruction in the result. A skill preference is not BLOCKED_EXTERNAL evidence.
If a matching skill is missing, do not stop: send a bounded skill-search task
when delegation is available, inventory local and curated/upstream candidates,
and audit their SKILL.md, task-relevant references, scripts, dependencies,
permissions, provenance, license, and instruction conflicts with
`skills/agent-harness-design/references/agent-skill-install-checklist.md`. Use
an accepted candidate. If none passes, research primary sources, create and
validate the smallest local skill that fills the routed gap, then resume the
original task. Never install or run unreviewed third-party code.
Finish with exactly one three-line receipt. Line 1 is `Skill disposition: USED
<skill(s)> | NO_MATCH | GAP_RESOLVED <requested> -> <accepted-or-created>;
checklist=<local checked receipt path> | PAUSED_BY_SKILL <skill> :: <local
SKILL.md>#L<line> :: <exact instruction copied from that line>`.
Line 2 is `Decision basis: OBSERVED | PRIMARY_DOC |
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
