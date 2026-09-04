#!/usr/bin/env python3
"""Run a command and capture sanitized bug-reproduction evidence as JSON."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|token|password|secret)\s*[:=]\s*)[^\s]+"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|npm_[A-Za-z0-9]{20,})\b"),
]


def redact(value: str) -> str:
    result = value
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            result = pattern.sub(r"\1[REDACTED]", result)
        else:
            result = pattern.sub("[REDACTED]", result)
    return result


def limit_output(value: str, maximum: int) -> tuple[str, bool]:
    cleaned = redact(value)
    if len(cleaned) <= maximum:
        return cleaned, False
    head = maximum // 2
    tail = maximum - head
    return cleaned[:head] + "\n... [output truncated] ...\n" + cleaned[-tail:], True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="evidence")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-output", type=int, default=6000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Provide a command after --")
    if args.timeout <= 0 or args.max_output < 500:
        parser.error("timeout must be > 0 and max-output must be >= 500")
    cwd = args.cwd.expanduser().resolve()
    if not cwd.is_dir():
        parser.error(f"cwd is not a directory: {cwd}")

    started = time.perf_counter_ns()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            timeout=args.timeout,
            check=False,
        )
        exit_code: int | None = completed.returncode
        stdout_raw = completed.stdout.decode("utf-8", errors="replace")
        stderr_raw = completed.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exit_code = None
        stdout_raw = (error.stdout or b"").decode("utf-8", errors="replace")
        stderr_raw = (error.stderr or b"").decode("utf-8", errors="replace")
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000

    stdout, stdout_truncated = limit_output(stdout_raw, args.max_output)
    stderr, stderr_truncated = limit_output(stderr_raw, args.max_output)
    result = {
        "schema_version": 1,
        "label": args.label,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "cwd": str(cwd),
        "runtime": f"Python {platform.python_version()} on {platform.system()} {platform.machine()}",
        "duration_ms": round(duration_ms, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "secrets_redacted": True,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    outcome = "TIMEOUT" if timed_out else f"exit {exit_code}"
    print(f"{args.label}: {outcome} in {duration_ms:.1f} ms -> {output}")


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"Capture failed: {error}", file=sys.stderr)
        raise SystemExit(1)
