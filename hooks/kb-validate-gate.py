#!/usr/bin/env python3
"""Stop hook: BLOCK session close while the knowledge base is out of sync with code.

The forcing tier of the agent-docs-freshness system. Your kb-skeleton already
ships scripts/validate_kb.py (fails when a source area has no docs/kb/modules/
doc, a kb doc references a dead path, an INVARIANT points at a missing test, or
AGENTS.md has a dead pointer) -- but it only runs in CI (.github/workflows/kb.yml)
on push/PR. That means a whole session can drift with a stale KB and only get
caught after push, or never if the repo never wired the CI. This hook moves the
same check EARLIER: it runs the repo's OWN validate_kb.py at Stop and refuses to
end the session while it fails. Same pattern as problems-md-validator.py /
feature-list-validator.py: opt-in by artifact presence, blocking, escape-hatched.

Reuses the project's configured validator (its SOURCE_ROOTS etc.), does NOT
reinvent validation.

## Behaviour (stdin = Stop event JSON)
- Tier 2b (force docs to EXIST): a [LONG-RUN] project (feature_list.json present)
  with NO agent docs at all (docs/kb/ and docs/layers/ both absent) and no
  validator -> BLOCK; a long-run project must maintain a KB. Scoped to opted-in
  projects so scratch/throwaway repos are never nagged.
- Tier 2 (force docs to stay CURRENT): scripts/validate_kb.py exits 1 -> BLOCK
  with its output as the reason (missing module doc, dead path, dead pointer).
- No scripts/validate_kb.py + not [LONG-RUN] -> silent pass (opt-in).
- validate_kb.py exits 0 (clean) -> silent pass.
- validate_kb.py exits 2 / crashes / times out -> fail-OPEN (allow); infra issue,
  not a KB-drift signal, must never wedge a session shut.
- stop_hook_active=true -> silent pass (anti-loop, REQUIRED).

## Bypass
- env  CLAUDE_SKIP_KB_GATE=1
- file .claude/.skip-kb-gate  (project-level)

## Self-test (no-silent-validators invariant)
    python kb-validate-gate.py --self-test
Plants a failing validator (must block), a passing one (must allow), a missing
one (must allow), and an exit-2 infra error (must fail-open). Prints PASS/FAIL.

## Register: ~/.claude/settings.json Stop[].hooks[]
## Reference: ~/.claude/rules/agent-docs-freshness.md,
##   principle 21 (KB enforcement), templates/kb-skeleton/scripts/validate_kb.py
"""
from __future__ import annotations

import json
import os
import subprocess
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
BUDGET_NAME = "kb-validate"

VALIDATOR_REL = ("scripts", "validate_kb.py")
TIMEOUT_SEC = 25
MAX_REASON_CHARS = 1500


def _validator_path(cwd: Path) -> Path:
    return cwd.joinpath(*VALIDATOR_REL)


def _run_validator(cwd: Path):
    """Return (returncode, output). returncode None on infra failure."""
    script = _validator_path(cwd)
    try:
        out = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
        return out.returncode, (out.stderr or out.stdout or "")
    except Exception as e:  # noqa: BLE001 -- any failure = fail-open infra path
        return None, str(e)


def _is_longrun(cwd: Path) -> bool:
    """A project that explicitly opted into the long-run harness."""
    return (cwd / "feature_list.json").exists() or (
        cwd / ".claude" / "feature_list.json"
    ).exists()


def _has_agent_docs(cwd: Path) -> bool:
    """Any curated agent-facing knowledge base is present."""
    return (cwd / "docs" / "kb").is_dir() or (cwd / "docs" / "layers").is_dir()


def evaluate(cwd: Path) -> str | None:
    """Pure decision: return a full block-reason string, or None to allow.

    Two blocking conditions, both escape-hatched by the caller:
      2b. adoption -- a [LONG-RUN] project (feature_list.json) with NO agent docs
          at all and no validator: force the KB to be CREATED.
      2.  currency -- an adopted repo whose scripts/validate_kb.py exits 1: force
          the KB to stay in sync (missing module doc, dead path, dead pointer).
    None otherwise: not opted in, KB clean (rc 0), or infra failure (rc 2 / crash
    / timeout = fail-open, must never wedge a session shut).
    """
    validator = _validator_path(cwd)

    # Tier 2b -- force docs to EXIST for a project that declared itself long-run.
    if _is_longrun(cwd) and not _has_agent_docs(cwd) and not validator.exists():
        return (
            "This project is [LONG-RUN] (feature_list.json) but carries NO agent "
            "docs: docs/kb/ and docs/layers/ are both absent. A long-run project "
            "must maintain a knowledge base. Scaffold the kb-skeleton (docs/kb/ + "
            "scripts/validate_kb.py) or start a docs/layers/ tree before ending."
        )

    # Tier 2 -- force the adopted KB to stay current.
    if not validator.exists():
        return None  # opt-in: repo has no scripts/validate_kb.py
    rc, output = _run_validator(cwd)
    if rc != 1:
        return None  # rc 0 clean; rc 2 / None = fail-open
    body = (output or "").strip() or "validate_kb.py reported the KB is out of sync."
    if len(body) > MAX_REASON_CHARS:
        body = body[:MAX_REASON_CHARS] + "\n  ... (truncated)"
    # validate_kb.py belongs to the repository being checked, and its stdout is
    # delivered into the model's context as the block reason. Frame it as data
    # so a repo cannot smuggle instructions through its own validator.
    if untrusted_block is not None:
        body = untrusted_block(body, "repository scripts/validate_kb.py stdout")
    return (
        "Knowledge base is out of sync with the code -- scripts/validate_kb.py "
        "failed. Fix the kb doc or the code reference before ending the session "
        "(local mirror of the CI gate).\n\n" + body
    )


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()

    try:
        # Strip a leading UTF-8 BOM (some shells/harnesses prepend one) before
        # parsing -- mirrors safety_common.read_event(). Without this, a BOM'd
        # stdin raises JSONDecodeError and the gate silently fails open.
        raw = sys.stdin.read().lstrip("\ufeff").strip()
        event = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return 0
    # Anti-loop with a budget, not a one-shot surrender (safety_common).
    if event.get("stop_hook_active"):
        if stop_budget_exhausted is None or stop_budget_exhausted(BUDGET_NAME):
            return 0
    if os.environ.get("CLAUDE_SKIP_KB_GATE"):
        return 0

    cwd = Path.cwd()
    if (cwd / ".claude" / ".skip-kb-gate").exists():
        return 0

    reason_body = evaluate(cwd)
    if reason_body is None:
        return 0

    reason = reason_body + (
        "\n\nBypass: CLAUDE_SKIP_KB_GATE=1  or  touch .claude/.skip-kb-gate"
    )
    if stop_budget_consume is not None:
        stop_budget_consume(BUDGET_NAME, cwd)
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def _self_test() -> int:
    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as td:
        # adopted + failing validator (rc 1) -> must block
        bad = Path(td) / "bad"
        (bad / "scripts").mkdir(parents=True)
        _validator_path(bad).write_text(
            "import sys\n"
            "print('KB validation FAILED: references missing path `gone.py`', file=sys.stderr)\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        r = evaluate(bad)
        if not r or "FAILED" not in r:
            print("SELF-TEST FAIL: failing KB validator did not block")
            ok = False

        # adopted + passing validator (rc 0) -> must allow
        good = Path(td) / "good"
        (good / "scripts").mkdir(parents=True)
        _validator_path(good).write_text(
            "import sys\nprint('[OK] KB consistent.')\nsys.exit(0)\n", encoding="utf-8"
        )
        if evaluate(good) is not None:
            print("SELF-TEST FAIL: passing KB validator wrongly blocked")
            ok = False

        # not adopted (no validator) -> must allow (opt-in)
        none = Path(td) / "none"
        none.mkdir()
        if evaluate(none) is not None:
            print("SELF-TEST FAIL: repo without validator should pass")
            ok = False

        # infra: validator exits 2 (missing docs/kb) -> must fail-open (allow)
        infra = Path(td) / "infra"
        (infra / "scripts").mkdir(parents=True)
        _validator_path(infra).write_text(
            "import sys\nprint('missing docs/kb/', file=sys.stderr)\nsys.exit(2)\n",
            encoding="utf-8",
        )
        if evaluate(infra) is not None:
            print("SELF-TEST FAIL: exit-2 infra error should fail-open")
            ok = False

        # tier 2b: [LONG-RUN] (feature_list.json) + no docs + no validator -> block
        lr = Path(td) / "longrun_nodocs"
        lr.mkdir()
        (lr / "feature_list.json").write_text('{"features": []}', encoding="utf-8")
        r2b = evaluate(lr)
        if not r2b or "LONG-RUN" not in r2b:
            print("SELF-TEST FAIL: long-run project without docs not blocked")
            ok = False

        # tier 2b negative: [LONG-RUN] WITH docs/kb -> allowed (no validator)
        lrok = Path(td) / "longrun_withdocs"
        (lrok / "docs" / "kb").mkdir(parents=True)
        (lrok / "feature_list.json").write_text('{"features": []}', encoding="utf-8")
        if evaluate(lrok) is not None:
            print("SELF-TEST FAIL: long-run project WITH docs wrongly blocked")
            ok = False

        # tier 2b negative: NOT long-run + no docs + no validator -> allowed
        plain = Path(td) / "plain_nodocs"
        plain.mkdir()
        if evaluate(plain) is not None:
            print("SELF-TEST FAIL: non-long-run repo without docs should pass")
            ok = False

    print("SELF-TEST: PASS" if ok else "SELF-TEST: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
