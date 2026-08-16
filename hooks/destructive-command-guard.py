#!/usr/bin/env python3
"""PreToolUse: block catastrophically destructive shell commands.

Covers: rm -rf on root/home/*, database DROP/TRUNCATE, docker/k8s mass delete,
mkfs/dd on block devices. Bypass: CLAUDE_ALLOW_DESTRUCTIVE=1.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    allow,
    any_match,
    bash_command,
    block,
    bypass,
    log,
    read_event,
)

# Require both recursive and force options, regardless of whether they are
# combined (`-rf`) or passed separately (`-r -f`, `--recursive --force`).
RM_RECURSIVE_FORCE = (
    r"\brm\b"
    r"(?=[^;\n]*\s(?:-[a-z]*r[a-z]*|--recursive)(?=\s|$))"
    r"(?=[^;\n]*\s(?:-[a-z]*f[a-z]*|--force)(?=\s|$))"
)

# Patterns are regexes. Case-insensitive match via safety_common.any_match.
PATTERNS = [
    # Filesystem catastrophes - only truly dangerous paths
    # rm -rf on filesystem root or bare wildcards
    rf"{RM_RECURSIVE_FORCE}[^;\n]*\s+/(?:\s|$|[;&|#])",
    rf"{RM_RECURSIVE_FORCE}[^;\n]*\s+/\*",
    rf"{RM_RECURSIVE_FORCE}[^;\n]*\s+\*\s*(?:$|[;&|#])",
    # rm -rf on user home
    rf"{RM_RECURSIVE_FORCE}[^;\n]*\s+~(?:\s|$|/|[;&|#])",
    rf"{RM_RECURSIVE_FORCE}[^;\n]*\s+\$HOME(?:\s|$|/)",
    rf"{RM_RECURSIVE_FORCE}[^;\n]*\s+~/(?:\s|$|[;&|#])",
    # rm -rf on critical system dirs
    rf"{RM_RECURSIVE_FORCE}[^;\n]*\s+/(etc|usr|var|boot|sys|proc|lib|lib64|sbin|bin|root|home)(?:/)?(?:\s|$|[;&|#])",
    r"\bfind\s+/\s+.*-delete\b",
    r"\bmkfs\.[a-z0-9]+\s+/dev/",
    r"\bdd\s+if=\S+\s+of=/dev/[sh]d[a-z]",
    r"\b:\s*\(\s*\)\s*\{\s*:\s*\|\s*:",  # fork bomb

    # Database destruction
    r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",
    r"\bTRUNCATE\s+TABLE\b",
    r"\bdropdb\b",
    r"\bmongo\s+.*\bdropDatabase\b",
    r"\bredis-cli\s+.*\bflushall\b",
    r"\bDELETE\s+FROM\s+\w+\s*(;|$)",  # DELETE without WHERE

    # Container/orchestration mass delete
    r"\bdocker\s+rm\s+-f\s+\$\(docker\s+ps",
    r"\bdocker\s+system\s+prune\s+.*-a.*--volumes",
    r"\bdocker-compose\s+down\s+.*-v",
    r"\bkubectl\s+delete\s+(ns|namespace|all)\b",
    r"\bkubectl\s+delete\s+.*--all\b",
    r"\bhelm\s+uninstall\b.*-n\s+(prod|production)",
]


def main() -> None:
    event = read_event()
    tool_name = event.get("tool_name", "")
    if tool_name != "Bash":
        allow()

    cmd = bash_command(event.get("tool_input", {}))
    if not cmd:
        allow()

    hit = any_match(cmd, PATTERNS, command=True)
    if not hit:
        allow()

    if bypass("destructive", cmd):
        log("WARN", "block_destructive", "bypass", hit, cmd)
        # Say it out loud. Measured 2026-08-16: CLAUDE_ALLOW_DESTRUCTIVE=1 was
        # live in the inherited environment, so this guard was passing every
        # catastrophic command in the session while looking armed - the log line
        # above is the only trace, and nobody reads a log they do not know to
        # open. A bypass that leaves no visible mark is indistinguishable from a
        # guard that is not there.
        source = ("environment CLAUDE_ALLOW_DESTRUCTIVE"
                  if os.environ.get("CLAUDE_ALLOW_DESTRUCTIVE", "").strip().lower()
                  in {"1", "true", "yes", "on"} else "an in-command bypass marker")
        print(f"[destructive-command-guard] BYPASSED via {source}: /{hit}/ matched "
              f"and was allowed through. Unset it to restore the gate.", file=sys.stderr)
        allow()

    log("BLOCK", "block_destructive", "deny", hit, cmd)
    block(
        "Destructive pattern detected: "
        f"/{hit}/. Этот hook блокирует катастрофические операции.\n"
        "Если действие намеренное и обратимость понятна:\n"
        "  1) сначала подтверди у пользователя цель и бэкап\n"
        "  2) запусти с CLAUDE_ALLOW_DESTRUCTIVE=1 в той же сессии\n"
        "Список категорий: rm -rf root/home, DROP/TRUNCATE, kubectl delete all, docker prune --volumes, dd/mkfs."
    )


if __name__ == "__main__":
    main()
