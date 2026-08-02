#!/usr/bin/env python3
"""Regression tests for directory-creation-guard.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "directory-creation-guard.py"


def run_hook(command: str, tool: str = "PowerShell") -> tuple[bool, str]:
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "cwd": str(ROOT),
        "tool_input": {"command": command},
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    blocked = '"decision": "block"' in out or '"decision":"block"' in out
    return blocked, out


def assert_blocked(command: str, needle: str) -> None:
    blocked, out = run_hook(command)
    assert blocked, f"expected block for {command!r}, got {out!r}"
    assert needle in out, f"expected {needle!r} in {out!r}"


def assert_allowed(command: str, tool: str = "PowerShell") -> None:
    blocked, out = run_hook(command, tool=tool)
    assert not blocked, f"expected allow for {command!r}, got {out!r}"


def main() -> int:
    assert_allowed("Write-Output ok")
    assert_allowed("New-Item -ItemType Directory -Path docs/new-section")
    assert_allowed("mkdir reports/hook-evidence/run-001", tool="Bash")
    assert_blocked("New-Item -ItemType Directory -Path random-new-folder", "project root")
    assert_allowed(
        "New-Item -ItemType Directory -Path example-app; "
        "Set-Content -Path example-app/.folder-meta.json -Value '{\"label\":\"PROJECT_ROOT\"}'"
    )
    assert_blocked("mkdir .tmp/probe-run", "lifecycle marker")
    assert_allowed(
        "mkdir .tmp/probe-run; "
        "Set-Content .tmp/probe-run/.folder-meta.json '{\"label\":\"TEMP_REPRODUCIBLE\"}'"
    )
    assert_allowed("mkdir .tmp/probe-run; New-Item -ItemType File -Path .tmp/probe-run/_DELETE_OK.md")
    assert_blocked("mkdir datasets/smoke-images", "looks dataset")
    assert_allowed(
        "mkdir datasets/smoke-images; "
        "Set-Content datasets/smoke-images/.folder-meta.json '{\"label\":\"DATASET_REBUILDABLE\"}'",
        tool="Bash",
    )
    desktop_probe = (Path.home() / "Desktop" / "random-test").as_posix()
    assert_blocked(
        f"New-Item -ItemType Directory -Path {desktop_probe}",
        "loose folder",
    )
    assert_allowed(
        "mkdir scratch/probe && touch scratch/probe/.delete-ok",
        tool="Bash",
    )
    print("test_directory_creation_guard: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
