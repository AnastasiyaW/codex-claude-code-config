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
Before the first material action, read the task-bound agent-skill-contract in
the assigned brief. Treat `client-profile`, `required-skills`, and
`missing-skills` as distinct facts: read every required SKILL.md and never claim
a missing or other-client-only skill was loaded. Read no unrelated skills. If
the route has no high-confidence match, identify the smallest available skill set
that actually fits; do not load every skill. For a factual or technical
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
an accepted candidate. If none passes, build a research-backed, production-
quality local skill: ground it in real task evidence and current primary
sources, record accepted and rejected guidance, structure it for progressive
disclosure, add deterministic assets only where recurring work justifies them,
compare it with a no-skill or prior-version baseline on realistic and held-out
tasks, independently review it, and record its owner, version, source freshness,
update triggers, and rollback. Quality is measured by behavior and
maintainability, not file count. Use the checklist's typed schemas: per-source
research maps to exact skill lines; eval/review metrics are recomputed from
case observations; original-task proof is task-bound and cannot reuse any
skill-build artifact. Record `Decision: BUILD_RESEARCHED` in the checked
receipt, then resume the original task and save a separate terminal JSON receipt
for that task. Never install or run unreviewed third-party code.
Finish with `Task route: <task-sha256 copied from the bound contract>`, then
`Skill disposition: USED
<skill(s)> | NO_MATCH | GAP_RESOLVED <requested> -> <accepted-or-created>;
checklist=<local checked receipt path> | PAUSED_BY_SKILL <skill> :: <local
SKILL.md>#L<line> :: <exact instruction copied from that line>`.
Then add `Decision basis: OBSERVED | PRIMARY_DOC | USER_CONSTRAINT |
INCONCLUSIVE | NO_DECISION` and `Evidence: <current command/path/URL; for
USER_CONSTRAINT use user request: <exact constraint>; or N/A only for
NO_DECISION>`. For GAP_RESOLVED also add `Continuation: RESUMED
task-sha256=<same digest> :: <completed original-task action>` and
`Continuation evidence: <local terminal JSON receipt>`. Never use MEMORY as a
basis, and never report NO_MATCH when the bound route lists required or missing skills.
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
