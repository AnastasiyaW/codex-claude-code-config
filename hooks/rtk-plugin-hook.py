#!/usr/bin/env python3
"""PreToolUse hook for the plugin: hand Bash/PowerShell input to a verified RTK.

RTK rewrites `git status` into `rtk git status`, so the shell must resolve
`rtk` on PATH; the binary found there is the one checked against the pinned
release hash in scripts/rtk_integration.py. Fail-open by construction: no RTK
on PATH, a different binary, a timeout or any RTK error prints nothing and
exits 0, leaving the command untouched.

    python hooks/rtk-plugin-hook.py --self-test
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

INTEGRATION = Path(__file__).resolve().parent.parent / "scripts" / "rtk_integration.py"
TIMEOUT_S = 10


def pinned_sha256() -> str:
    spec = importlib.util.spec_from_file_location("rtk_integration", INTEGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PINNED_BINARY_SHA256


def verified_binary(pinned: str) -> str | None:
    found = shutil.which("rtk")
    if not found:
        return None
    try:
        digest = hashlib.sha256(Path(found).read_bytes()).hexdigest()
    except OSError:
        return None
    return found if digest == pinned else None


def rewrite(stdin: bytes, pinned: str) -> bytes:
    binary = verified_binary(pinned)
    if binary is None:
        return b""
    try:
        result = subprocess.run([binary, "hook", "claude"], input=stdin, capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return b""
    return result.stdout if result.returncode == 0 and result.stdout.lstrip().startswith(b"{") else b""


def main() -> int:
    try:
        sys.stdout.buffer.write(rewrite(sys.stdin.buffer.read(), pinned_sha256()))
    except Exception:  # noqa: BLE001 - a compression hint must never cost a tool call
        pass
    return 0


def self_test() -> int:
    sample = b'{"tool_name":"Bash","tool_input":{"command":"git status"},"hook_event_name":"PreToolUse"}'
    pinned = pinned_sha256()
    saved = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = ""
        assert rewrite(sample, pinned) == b"", "no RTK on PATH must pass through"
    finally:
        os.environ["PATH"] = saved
    assert rewrite(sample, "0" * 64) == b"", "an unpinned binary must pass through"
    if verified_binary(pinned):
        out = rewrite(sample, pinned)
        assert b'"rtk git status"' in out, out
        assert rewrite(b"not json", pinned) == b"", "RTK error text must not reach Claude"
        print("[PASS] rtk-plugin-hook self-test (verified RTK on PATH)")
    else:
        print("[PASS] rtk-plugin-hook self-test (no verified RTK on PATH: pass-through cases only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else main())
