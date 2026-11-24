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
    "route_state": { ... },          # optional Codex agent route under sandbox HOME
    "command_file": "rel/path"     # optional: file whose content becomes
  }                                #   stdin.tool_input.command

Sandboxing: every case runs with cwd = a fresh temp dir and
USERPROFILE/HOME pointed at it, so hooks that consult ~/.claude
(global handoff store, global CLAUDE.md, safety log) see an empty,
deterministic world and leave no traces in the real one.

Optional case fields:
    "kind": "regression" | "capability"   # default regression
    "source": "..."                       # incident, correction or rule it came from

Trials (Anthropic, "Demystifying evals for AI agents"): one run of a case is a
trial. With --trials k every case runs k times and the summary reports
pass@k (at least one trial passed) and pass^k (every trial passed). A
regression case must pass in all k trials; one failing trial is a failure,
not noise. A capability case may fail: it measures a skill still being
built, and when every capability case passes all trials the set is
saturated and those cases belong in the regression set.

Usage:
  python run_hook_evals.py [--trials K] [--json OUT]
  HOOKS_DIR=<path> python run_hook_evals.py   # e.g. the repo copy
Exit code (three states):
  0 every regression case passed in every trial;
  1 a regression case failed in at least one trial;
  2 no failure, but some trial could not run (hook missing, timeout, crash).
"""
from __future__ import annotations

import argparse
import json
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
# The default must follow the checkout that owns these fixtures.  Pointing via
# Path.home() can make an uninstalled branch silently test the older live tree.
DEFAULT_HOOKS = HERE.parents[1] / "hooks"
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


PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
KINDS = ("regression", "capability")


def run_case(case: dict) -> tuple[str, str]:
    """One trial of a case: PASS, FAIL, or UNKNOWN when it could not run."""
    hook = HOOKS_DIR / case["hook"]
    if not hook.exists():
        return UNKNOWN, f"hook not found: {hook}"
    try:
        ok, msg = _judge(case, hook)
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return UNKNOWN, f"trial did not run: {exc}"
    return (PASS if ok else FAIL), msg


def _judge(case: dict, hook: Path) -> tuple[bool, str]:

    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        for rel, content in case.get("files", {}).items():
            p = sandbox / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        stdin_obj = case.get("stdin", {})
        route_state = case.get("route_state")
        if route_state is not None:
            session_id = str(stdin_obj.get("session_id") or "")
            agent_id = str(stdin_obj.get("agent_id") or "")
            if not session_id or not agent_id:
                raise ValueError("route_state requires stdin.session_id and stdin.agent_id")
            session_key = hashlib.sha256(session_id.encode()).hexdigest()
            agent_key = hashlib.sha256(agent_id.encode()).hexdigest()
            state_path = (
                sandbox / ".codex" / "state" / "agent-skill-contracts"
                / session_key / "agents" / f"{agent_key}.json"
            )
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"state_version": 1, **route_state}), encoding="utf-8"
            )
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
        # A crashed hook prints no block, so "allow" would read it as a pass.
        if "Traceback (most recent call last)" in (proc.stderr or ""):
            raise OSError("hook crashed: " + proc.stderr.strip().splitlines()[-1][:200])
        # Claude hook protocol: exit 2 blocks with the reason on stderr; any other
        # non-zero exit is an error, not a decision.
        if proc.returncode not in (0, 2):
            raise OSError(f"hook exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}")
        out = proc.stdout or ""
        if proc.returncode == 2:
            out = json.dumps({"decision": "block", "reason": (proc.stderr or "").strip()}) + "\n" + out

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


def summarize(results: list[dict]) -> dict:
    """pass@k and pass^k per kind, over cases whose trials all ran."""
    out: dict = {}
    for kind in KINDS:
        rows = [r for r in results if r["kind"] == kind]
        ran = [r for r in rows if UNKNOWN not in r["trials"]]
        n = len(ran)
        out[kind] = {
            "cases": len(rows),
            "not_run": len(rows) - n,
            "pass_at_k": sum(PASS in r["trials"] for r in ran) / n if n else None,
            "pass_hat_k": sum(set(r["trials"]) == {PASS} for r in ran) / n if n else None,
            "flaky": sorted(r["id"] for r in ran if PASS in r["trials"] and FAIL in r["trials"]),
        }
    return out


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run hook evals with repeated trials.")
    parser.add_argument("--trials", type=int, default=1, help="trials per case (k)")
    parser.add_argument("--json", type=Path, help="write per-case trials and the summary here")
    args = parser.parse_args(argv)
    if args.trials < 1:
        parser.error("--trials must be at least 1")
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        kind = case.get("kind", "regression")
        trials: list[str] = []
        messages: list[str] = []
        if kind not in KINDS:
            trials, messages, kind = [UNKNOWN], [f"kind must be one of {KINDS}"], "regression"
        else:
            for _ in range(args.trials):
                state, msg = run_case(case)
                trials.append(state)
                if msg and msg not in messages:
                    messages.append(msg)
        results.append({"id": case["id"], "hook": case["hook"], "kind": kind,
                        "expect": case["expect"], "source": case.get("source"),
                        "trials": trials, "messages": messages})
        if set(trials) == {PASS}:
            mark = PASS
        elif FAIL in trials:
            mark = "FLAKY" if PASS in trials else FAIL
        else:
            mark = UNKNOWN
        line = f"[{mark}] {case['hook']:35s} {case['id']}"
        if args.trials > 1 and mark != PASS:
            line += f"  ({trials.count(PASS)}/{len(trials)} trials passed)"
        if kind == "capability":
            line += "  [capability]"
        for msg in messages:
            line += f"\n        {msg}"
        print(line)

    k = args.trials
    summary = summarize(results)
    refuse = sum(1 for r in results if r["expect"] == "block")
    print(f"\nk={k} trials per case; refuse (block) cases: {refuse}, act cases: {len(results) - refuse}")
    for kind, row in summary.items():
        if row["cases"]:
            print(f"{kind}: {row['cases']} cases, pass@{k} {_pct(row['pass_at_k'])}, "
                  f"pass^{k} {_pct(row['pass_hat_k'])}, flaky {len(row['flaky'])}, "
                  f"not run {row['not_run']}")
    cap = summary["capability"]
    if cap["cases"] and not cap["not_run"] and cap["pass_hat_k"] == 1:
        print("capability set saturated: every case passed every trial; move them to regression")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"trials": k, "hooks_dir": str(HOOKS_DIR),
                                         "summary": summary, "cases": results},
                                        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"hooks dir: {HOOKS_DIR}")
    if any(FAIL in r["trials"] for r in results if r["kind"] == "regression"):
        return 1
    if any(UNKNOWN in r["trials"] for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
