#!/usr/bin/env python3
"""PreToolUse: block destructive git operations.

Covers: reset --hard, push --force, branch -D, clean -fdx, checkout -- .,
amend on published commits. Bypass: ``# claude-bypass: git-destructive`` in
the command, or an exported CLAUDE_ALLOW_GIT_DESTRUCTIVE=1 before the session.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    GIT_FORCE_BRANCH_DELETE_PATTERNS,
    allow,
    any_match,
    bash_command,
    block,
    bypass,
    log,
    read_event,
)

PATTERNS = [
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+(push\s+)?(-f|--force(?!-with-lease))\b",
    r"\bgit\s+push\s+.*--force(?!-with-lease)",
    *GIT_FORCE_BRANCH_DELETE_PATTERNS,
    r"\bgit\s+clean\s+-[fdxX]{2,}",
    r"\bgit\s+clean\s+-[fdx]\s+-[fdx]",
    r"\bgit\s+checkout\s+--\s+\.",
    r"\bgit\s+restore\s+--source",
    r"\bgit\s+restore\s+--staged\s+--worktree\s+\.",
    r"\bgit\s+filter-(branch|repo)\b",
    r"\bgit\s+update-ref\s+-d\s+refs/heads/(main|master|prod(uction)?)",
    r"\bgit\s+rebase\s+.*-i.*\s+HEAD",  # interactive rebase - often destructive
    r"\bgit\s+reflog\s+expire\s+--expire=now",
    r"\bgit\s+gc\s+--prune=now\s+--aggressive",
]


def main() -> None:
    event = read_event()
    if event.get("tool_name") != "Bash":
        allow()

    cmd = bash_command(event.get("tool_input", {}))
    if not cmd:
        allow()

    hit = any_match(cmd, PATTERNS, command=True)
    if not hit:
        allow()

    if bypass("git-destructive", cmd, env_name="CLAUDE_ALLOW_GIT_DESTRUCTIVE"):
        log("WARN", "block_git_destructive", "bypass", hit, cmd)
        allow()

    log("BLOCK", "block_git_destructive", "deny", hit, cmd)
    block(
        f"Destructive git operation: /{hit}/.\n"
        "Это команды которые перетирают историю или теряют uncommitted работу.\n"
        "Перед выполнением:\n"
        "  1) подтверди у пользователя\n"
        "  2) сделай fresh backup branch: git branch backup-$(date +%s)\n"
        "  3) для разового обхода добавь в команду: # claude-bypass: git-destructive\n"
        "     Inline CLAUDE_ALLOW_GIT_DESTRUCTIVE=1 перед командой хуку не передаётся;\n"
        "     экспортируй переменную до запуска Claude, если нужен env-обход.\n"
        "Безопасные альтернативы:\n"
        "  reset --hard → reset --keep, или stash && reset\n"
        "  push --force → push --force-with-lease\n"
        "  branch -D → merge/rebase + git branch -d <merged-branch>\n"
        "  clean -fdx → проверить git status && targeted rm"
    )


if __name__ == "__main__":
    main()
