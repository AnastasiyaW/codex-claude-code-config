"""Hook commands use an interpreter that exists on the installing machine.

macOS and many Linux distributions have `python3` but no `python`; a registered
`python "<hook>"` then fails with `python: command not found` on every call, and
Claude Code only records a non-blocking hook error, so the guard never runs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "install_hooks.py"
SPEC = importlib.util.spec_from_file_location("install_hooks", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _which(available: set[str]):
    return lambda name: f"/usr/bin/{name}" if name in available else None


def main() -> int:
    cases = [
        ({"python", "python3"}, "python"),
        ({"python"}, "python"),
        ({"python3"}, "python3"),
        (set(), "python"),
    ]
    for available, expected in cases:
        with mock.patch.object(MODULE.shutil, "which", _which(available)):
            got = MODULE._python_launcher()
        assert got == expected, (sorted(available), got)

    target = Path("/home/u/.claude/claude-code-config/hooks/destructive-command-guard.py")
    with mock.patch.object(MODULE, "PYTHON_CMD", "python3"):
        assert MODULE._command_for(target, "PreToolUse") == f'python3 "{target.as_posix()}"'
        stale = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": f'python "{target.as_posix()}"'}]}]}}
        assert MODULE._merge_hook(stale, "PreToolUse", target, "Bash") == "repaired"
        assert stale["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == f'python3 "{target.as_posix()}"'
    print("test_install_hooks_launcher: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
