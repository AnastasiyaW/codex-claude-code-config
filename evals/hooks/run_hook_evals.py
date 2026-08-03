#!/usr/bin/env python3
"""Eval runner for safety/lifecycle hooks (harness tests, not model tests).

Why: 28 wired hooks had zero tests; a false-positive bug in
session-drift-validator lived unnoticed from install until 2026-06-09.
Per skills/agent-harness-design/references/agent-evals.md every mechanical guard needs fixtures with
mechanical pass/fail checks.

Each case in cases.json:
  {
    "id": "...",
    "hook": "<file name in HOOKS_DIR>",
    "stdin": { ... },              # JSON event fed to the hook
    "expect": "allow" | "block" | "output" | "no-output",
    "reason_contains": "...",      # optional, for expect=block
    "stdout_contains": [...],      # for expect=output
    "stdout_not_contains": [...],  # for expect=output
    "files": {"rel/path": "content"},  # sandbox files (cwd = sandbox)
    "command_file": "rel/path"     # optional: file whose content becomes
  }                                #   stdin.tool_input.command

Sandboxing: every case runs with cwd = a fresh temp dir and
USERPROFILE/HOME pointed at it, so hooks that consult ~/.claude
(global handoff store, global CLAUDE.md, safety log) see an empty,
deterministic world and leave no traces in the real one.

Usage:
  python run_hook_evals.py            # HOOKS_DIR defaults to the ACTIVE
                                      # dir ~/.claude/claude-code-config/hooks
  HOOKS_DIR=<path> python run_hook_evals.py   # e.g. the repo copy
Exit code: 0 = all pass, 1 = failures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_HOOKS = Path.home() / ".claude" / "claude-code-config" / "hooks"
HOOKS_DIR = Path(os.environ.get("HOOKS_DIR", str(DEFAULT_HOOKS)))


def clean_env(sandbox: Path) -> dict:
    """Real env minus bypass/skip vars, with HOME redirected to the sandbox."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE_ALLOW_", "CLAUDE_SKIP_"))
    }
    env["USERPROFILE"] = str(sandbox)  # Path.home() on Windows
    env["HOME"] = str(sandbox)        # Path.home() on POSIX
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_case(case: dict) -> tuple[bool, str]:
    hook = HOOKS_DIR / case["hook"]
    if not hook.exists():
        return False, f"hook not found: {hook}"

    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        for rel, content in case.get("files", {}).items():
            p = sandbox / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        stdin_obj = case.get("stdin", {})
        if case.get("command_file"):
            content = (sandbox / case["command_file"]).read_text(encoding="utf-8")
            stdin_obj.setdefault("tool_input", {})["command"] = content

        proc = subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(stdin_obj),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=sandbox,
            env=clean_env(sandbox),
            timeout=60,
        )
        out = proc.stdout or ""

        decision = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    decision = obj.get("decision")
                    reason = obj.get("reason", "")
                    break
                except json.JSONDecodeError:
                    continue
        else:
            reason = ""

        expect = case["expect"]
        if expect == "allow":
            if decision == "block":
                return False, f"expected allow, got block: {reason[:120]}"
            return True, ""
        if expect == "block":
            if decision != "block":
                return False, f"expected block, got allow (stdout: {out[:120]!r})"
            want = case.get("reason_contains")
            if want and want not in reason:
                return False, f"block reason lacks {want!r}: {reason[:120]}"
            return True, ""
        if expect == "output":
            for s in case.get("stdout_contains", []):
                if s not in out:
                    return False, f"stdout lacks {s!r} (got: {out[:200]!r})"
            for s in case.get("stdout_not_contains", []):
                if s in out:
                    return False, f"stdout must NOT contain {s!r}"
            return True, ""
        if expect == "no-output":
            if out.strip():
                return False, f"expected no output, got: {out[:200]!r}"
            if decision == "block":
                return False, f"expected no output, got block: {reason[:120]}"
            return True, ""
        return False, f"unknown expect: {expect}"


def main() -> int:
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    failures = 0
    for case in cases:
        ok, msg = run_case(case)
        mark = "PASS" if ok else "FAIL"
        line = f"[{mark}] {case['hook']:35s} {case['id']}"
        if not ok:
            line += f"\n        {msg}"
            failures += 1
        print(line)
    total = len(cases)
    print(f"\n{total - failures}/{total} passed (hooks dir: {HOOKS_DIR})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
