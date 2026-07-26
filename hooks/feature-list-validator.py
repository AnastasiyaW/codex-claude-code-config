#!/usr/bin/env python3
"""Stop hook: validate feature_list.json state discipline (R1 resumable context).

Companion to problems-md-validator.py. Where that guards PROBLEMS.md, this
guards the feature_list.json state machine used by long-running projects
(see ~/.claude/rules/long-run-harness.md + no-pre-existing-evasion.md). A
resumed session can only TRUST feature_list.json if it stays honest; this
hook enforces the two invariants that rot silently across sessions:

1. WIP=1 -- at most one feature may be `status: "in-progress"` at a time.
   Two in-progress = an agent quietly opened a second feature when the first
   hit friction; days later both are half-done with no verified evidence.
2. done-needs-evidence -- a feature marked `done` MUST carry non-empty
   `evidence` (a durable artifact: test output, commit hash, handoff ref).
   `done` with empty evidence is the "declared victory too early" failure.

Also rejects any `status` outside {not-started, in-progress, blocked, done}.

## Behaviour (hook mode, stdin = Stop event JSON)
- Valid / no feature_list.json found -> silent pass (file is opt-in).
- Invalid -> emit {"decision":"block","reason":...} with specifics.
- stop_hook_active=true -> silent pass (anti-loop, REQUIRED).

## Bypass
- env CLAUDE_SKIP_FEATURE_CHECK=1
- file .claude/.skip-feature-check (project-level)

## Self-test (no-silent-validators.md invariant 4)
    python feature-list-validator.py --self-test
Plants a known-bad (WIP=2 + done-empty-evidence) that MUST flag and a
known-good that MUST pass; prints SCANNED: + PASS/FAIL; exit 0/1.

## Register (NOT wired by default -- add to settings.json Stop[] when ready)
    {"hooks":{"Stop":[{"hooks":[{"type":"command",
      "command":"python ~/.claude/claude-code-config/hooks/feature-list-validator.py",
      "statusMessage":"feature_list.json validation..."}]}]}}

## Reference
- ~/.claude/rules/long-run-harness.md (WIP=1, feature_list schema)
- ~/.claude/rules/no-pre-existing-evasion.md (done = durable artifacts)
- ~/.claude/rules/no-silent-validators.md (fail-loud, self-test)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from safety_common import (  # noqa: E402
        stop_budget_consume,
        stop_budget_exhausted,
        untrusted_block,
    )
except ImportError:  # fail-open: keep the original one-shot behaviour
    stop_budget_consume = stop_budget_exhausted = untrusted_block = None  # type: ignore[assignment]

# Gate name for the shared Stop-hook rejection budget (safety_common).
BUDGET_NAME = "feature-list"

VALID_STATUS = {"not-started", "in-progress", "blocked", "done"}
MIN_EVIDENCE_CHARS = 12


def find_feature_list(cwd: Path):
    for p in (cwd / "feature_list.json", cwd / ".claude" / "feature_list.json"):
        if p.exists() and p.is_file():
            return p
    return None


def _clip(value, limit: int = 60) -> str:
    """Shorten a repository-supplied field before it reaches the block reason."""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[:limit] + "..."


def validate(data) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["feature_list.json root is not an object"]
    features = data.get("features")
    if not isinstance(features, list):
        return ["feature_list.json has no 'features' list"]

    in_progress = [f for f in features
                   if isinstance(f, dict) and f.get("status") == "in-progress"]
    if len(in_progress) > 1:
        ids = ", ".join(_clip(f.get("id", "?"), 40) for f in in_progress)
        errors.append(
            "WIP=1 violated: %d features in-progress (%s). Block one with "
            "reason in evidence, or roll it back to not-started." % (len(in_progress), _clip(ids, 240)))

    for f in features:
        if not isinstance(f, dict):
            errors.append("a feature entry is not an object")
            continue
        fid = _clip(f.get("id", "?"), 40)
        st = f.get("status")
        if st not in VALID_STATUS:
            errors.append("%s: invalid status %s (use %s)"
                          % (fid, _clip(repr(st), 40), "/".join(sorted(VALID_STATUS))))
        if st == "done":
            ev = (f.get("evidence") or "")
            ev = ev.strip() if isinstance(ev, str) else ""
            if len(ev) < MIN_EVIDENCE_CHARS:
                errors.append(
                    "%s: status=done but evidence empty/too short -- done needs a "
                    "durable artifact (test output / commit hash / handoff ref)." % fid)
    return errors


def _self_test() -> int:
    bad = {"features": [
        {"id": "f1", "status": "in-progress"},
        {"id": "f2", "status": "in-progress"},
        {"id": "f3", "status": "done", "evidence": ""},
        {"id": "f4", "status": "shipped"},
    ]}
    good = {"features": [
        {"id": "f1", "status": "in-progress"},
        {"id": "f2", "status": "done",
         "evidence": "L1 tsc clean; L2 ctest 23/23 (commit a1b2c3d); L3 manual verify 2026-06-10"},
        {"id": "f3", "status": "blocked", "evidence": "waiting on prod activation"},
        {"id": "f4", "status": "not-started"},
    ]}
    eb, eg = validate(bad), validate(good)
    ok = len(eb) >= 3 and len(eg) == 0
    print("SCANNED: self_test_cases=2 bad_errors=%d good_errors=%d" % (len(eb), len(eg)))
    if not ok:
        print("[ERR] self-test FAILED: bad=%r good=%r" % (eb, eg))
        return 1
    print("[OK] feature-list-validator self-test passed")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()

    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return 0

    # Anti-loop with a budget, not a one-shot surrender (safety_common).
    if event.get("stop_hook_active"):
        if stop_budget_exhausted is None or stop_budget_exhausted(BUDGET_NAME):
            return 0
    if os.environ.get("CLAUDE_SKIP_FEATURE_CHECK"):
        return 0

    cwd = Path.cwd()
    if (cwd / ".claude" / ".skip-feature-check").exists():
        return 0

    fl = find_feature_list(cwd)
    if fl is None:
        return 0
    try:
        data = json.loads(fl.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0  # malformed JSON is a different concern; do not block on it

    errors = validate(data)
    if not errors:
        return 0

    rel = fl.relative_to(cwd) if cwd in fl.parents else fl
    # The violation lines quote repository content (feature ids, statuses), so
    # they are framed as data — a feature_list.json must not be able to address
    # the agent through the block reason.
    detail = "".join("  - %s\n" % e for e in errors[:8])
    if len(errors) > 8:
        detail += "  ... and %d more\n" % (len(errors) - 8)
    if untrusted_block is not None:
        detail = untrusted_block(detail.rstrip("\n"), "quoted from feature_list.json")
    reason = ("feature_list.json (%s) has %d state violation(s) "
              "(R1 resumable-context discipline):\n%s\n" % (rel, len(errors), detail))
    reason += ("\nTo unblock: enforce WIP=1 (one in-progress), give every `done` "
               "feature real evidence, use only not-started/in-progress/blocked/done. "
               "Bypass: CLAUDE_SKIP_FEATURE_CHECK=1")
    if stop_budget_consume is not None:
        stop_budget_consume(BUDGET_NAME)
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
