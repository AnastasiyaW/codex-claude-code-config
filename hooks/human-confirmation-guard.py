#!/usr/bin/env python3
"""PreToolUse: fail closed for destructive intent until the host can prove approval.

Universal "human-in-the-loop" gate for any operation that removes / drops /
deletes / terminates / overwrites. Replaces narrow catastrophic-only check
with broad destructive-intent detection, plus a safe-target whitelist so
routine cleanup (build/, dist/, node_modules/, /tmp/, .cache/) doesn't
prompt the user.

Replit incident pattern (Aug 2026, Jason Lemkin)
================================================
An agent can write any marker, phrase, timestamp, or local file that it can
then present to this hook. None of those are human authorization. The current
Claude/Codex hook event contains neither a host-signed approval result nor a
trusted transcript/approval API, so this hook cannot distinguish an actual
user decision from a forged one. Non-whitelisted destructive operations must
therefore remain blocked rather than forge a green result.

Verdict matrix
==============
| destructive intent | target whitelist | host-verifiable approval | result |
|---|---|---|---|
| no                 | n/a              | -              | allow |
| yes                | all targets safe | -              | allow (silent) |
| yes                | non-safe target  | unavailable in current hook API | **BLOCK** |

Design notes
============
- Command text, environment flags, git state, and any file writable by the
  agent are not approval credentials.
- A future allow path must verify a host-issued, single-use approval record
  bound to the canonical action digest, targets, session, expiry, and approver.
- This hook does not perform backups (see pre_db_snapshot, pre_fs_snapshot
  for that). It is the gate, not the safety net.

Bypass of *this* hook
=====================
There is intentionally no bypass for this hook. Until a host-verifiable
approval interface exists, destructive ops remain blocked. CI/CD pipelines
should not run inside Claude Code sessions.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    GIT_FORCE_BRANCH_DELETE_PATTERNS,
    allow,
    any_match,
    bash_command,
    block,
    log,
    read_event,
)

# =============================================================================
# Destructive intent patterns — case-insensitive
# Broad: any operation that removes / drops / deletes / terminates / overwrites
# =============================================================================
DESTRUCTIVE_INTENT = [
    # Filesystem
    r"\brm\s+-[a-z]*r[a-z]*\s+",      # rm -rf, rm -r, rm -Rf, etc
    r"\brmdir\s+",
    r"(?:^|[;&|])\s*mv\s+",
    r"\bmove-item\b",
    # PowerShell, which this guard explicitly accepts as a tool and which is the
    # primary shell on this machine. An independent review scanned the raw list
    # and found `Remove-Item` - the commonest destructive PowerShell command -
    # matched NOTHING at all, along with Clear-Content, Stop-Service and the
    # machine-stopping verbs. Only `Move-Item` was covered, by luck of naming.
    r"\bremove-item\b",
    r"\bclear-content\b",
    r"\bstop-service\b",
    r"\bstop-computer\b",
    r"\brestart-computer\b",
    r"\bremove-partition\b",
    r"\bformat-volume\b",
    r"\brobocopy\b.*\/(?:move|mov)\b",
    r"\brclone\s+move\b",
    r"\bfind\s+\S+.*-delete\b",
    r"\bmkfs\.[a-z0-9]+\s+/dev/",
    r"\bdd\s+if=\S+\s+of=/dev/[sh]d[a-z]",
    r"\bshred\s+",
    r"\b:\s*\(\s*\)\s*\{\s*:\s*\|\s*:",  # fork bomb

    # Database
    r"\bDROP\s+(TABLE|DATABASE|SCHEMA|VIEW|INDEX|MATERIALIZED\s+VIEW)\b",
    r"\bTRUNCATE\b",
    r"\bDELETE\s+FROM\s+\w+",  # ВСЕГДА требует confirm — даже с WHERE
    r"\bdropdb\b",
    r"\bmongo\s+.*\bdropDatabase\b",
    r"\bmongo\s+.*\bdrop\(\)",  # collection.drop()
    r"\bredis-cli\s+.*\bflushall\b",
    r"\bredis-cli\s+.*\bflushdb\b",
    r"\bredis-cli\s+.*\bdel\s+",

    # Containers / orchestration
    r"\bdocker\s+rm\b",
    r"\bdocker\s+rmi\b",
    r"\bdocker\s+volume\s+rm\b",
    r"\bdocker\s+network\s+rm\b",
    r"\bdocker\s+system\s+prune\b",
    r"\bdocker-compose\s+down\b",
    r"\bdocker\s+compose\s+down\b",
    r"\bkubectl\s+delete\b",
    r"\bhelm\s+uninstall\b",
    r"\bhelm\s+delete\b",

    # Cloud APIs (curl DELETE / cli delete commands)
    r"\bcurl\s+[^|]*-X\s+DELETE\b",
    r"\bcurl\s+[^|]*--request\s+DELETE\b",
    r"\baws\s+\w+\s+(delete|terminate|remove)-\w+",
    r"\bgcloud\s+\w+(\s+\w+)*\s+delete\b",
    r"\baz\s+\w+(\s+\w+)*\s+delete\b",
    r"\bcloudflared\s+tunnel\s+delete\b",
    r"\bwrangler\s+delete\b",
    r"\bgh\s+(repo|pr|release|workflow)\s+delete\b",
    r"\bgh\s+api\s+[^|]*-X\s+DELETE\b",
    r"\bgh\s+api\s+[^|]*--method\s+DELETE\b",

    # Git destructive (also covered by block_git_destructive)
    r"\bgit\s+reset\s+[^|]*--hard\b",
    # The wildcard stops at a command separator and the flag is matched
    # case-exactly (this module applies IGNORECASE to every pattern, so the
    # exactness is scoped inline). Two false positives measured 2026-09-04
    # against the old `push\s+[^|]*(-f\b|--force\b)`: a push followed later in
    # the same line by an unrelated `commit -F` was read as a force, because
    # `[^|]*` crossed `&&` and IGNORECASE folded -F into -f; and
    # `--force-with-lease` -- the alternative this very guard recommends --
    # was blocked, because `--force\b` matches its prefix.
    r"\bgit\s+push\b[^|;&\n]*?\s(?-i:(?:-[a-zA-Z]*f|--force))\b(?!-with-lease)",
    *GIT_FORCE_BRANCH_DELETE_PATTERNS,
    r"\bgit\s+clean\s+-[fdx]+",
    r"\bgit\s+filter-branch\b",
    r"\bgit\s+filter-repo\b",
    r"\bgit\s+reflog\s+expire\s+.*--expire=now",

    # Process / system
    r"\bkill\s+-9\b",
    r"\bkill\s+-KILL\b",
    r"\bpkill\s+-9\b",
    r"\bkillall\b",
    r"\bshutdown\s+",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",

    # Service / systemd (stopping prod services)
    r"\bsystemctl\s+stop\b",
    r"\bsystemctl\s+disable\b",
    r"\bservice\s+\S+\s+stop\b",

    # Packages
    r"\bapt(?:-get)?\s+(remove|purge|autoremove)\b",
    r"\bdpkg\s+--remove\b",
    r"\bdpkg\s+--purge\b",
    r"\bpip\s+uninstall\b",
    r"\bpip3\s+uninstall\b",
    r"\bnpm\s+uninstall\b",
    r"\bnpm\s+rm\b",
    r"\byarn\s+remove\b",
    r"\bbrew\s+(uninstall|remove)\b",
    r"\bcargo\s+uninstall\b",
    r"\bgem\s+uninstall\b",

    # Network / firewall
    r"\biptables\s+-[FXZ]\b",
    r"\bufw\s+reset\b",
    r"\bufw\s+--force\s+reset\b",
    r"\bip\s+link\s+(delete|del)\b",
    r"\bip\s+route\s+(flush|delete|del)\b",

    # Communication APIs (irreversible)
    r"\bgh\s+pr\s+close\b",
    r"\bgh\s+issue\s+close\b",

    # IAM / permissions
    r"\baws\s+iam\s+(delete|remove)-\w+",
    r"\baws\s+s3(?:api)?\s+rb\b",  # remove bucket
    r"\baws\s+s3\s+rm\s+",          # rm objects
]

# =============================================================================
# Safe target whitelist — patterns indicating the rm/delete affects only
# routine build artifacts / caches / temp data.
# If ALL non-flag args of an `rm` / `find -delete` match a safe pattern,
# we allow without confirmation.
# =============================================================================
SAFE_TARGET_PATTERNS = [
    # Build artifacts
    r"^node_modules/?$",
    r"/node_modules/?$",
    r"^dist/?$",
    r"/dist/?$",
    r"^build/?$",
    r"/build/?$",
    r"^target/?$",          # Rust/Java
    r"/target/?$",
    r"^out/?$",
    r"/out/?$",
    r"^\.next/?$",
    r"/\.next/?$",
    r"^\.nuxt/?$",
    r"^\.svelte-kit/?$",

    # Caches
    r"^__pycache__/?$",
    r"/__pycache__/?$",
    r"^\.pytest_cache/?$",
    r"^\.cache/?$",
    r"/\.cache/?$",
    r"^\.tox/?$",
    r"^\.venv/?$",
    r"^venv/?$",
    r"^\.mypy_cache/?$",
    r"^\.ruff_cache/?$",
    r"^\.gradle/?$",
    r"^\.idea/?$",
    r"^\.vscode/?$",
    r"^coverage/?$",
    r"^htmlcov/?$",
    r"^\.coverage$",

    # Temp paths (system tmp)
    r"^/tmp/",
    r"^/var/tmp/",
    r"^/private/tmp/",        # macOS
    r"\bAppData/Local/Temp/", # Windows via Git Bash

    # Common temp file patterns
    r"\.tmp(\s|$|/)",
    r"\.bak(\s|$|/)",
    r"\.swp(\s|$|/)",
    r"\.swo(\s|$|/)",
    r"\.pyc(\s|$|/)",
    r"\.DS_Store(\s|$|/)",
    r"Thumbs\.db(\s|$|/)",
    r"\.log(\s|$|/)",         # log rotations
    r"\.orig(\s|$|/)",        # merge artifacts
    r"\.rej(\s|$|/)",         # patch reject
]

def is_target_safe(target: str) -> bool:
    """Check if a single rm target matches a safe pattern."""
    for pat in SAFE_TARGET_PATTERNS:
        if re.search(pat, target, re.IGNORECASE):
            return True
    return False


def extract_rm_targets(cmd: str) -> list[str]:
    """Pull non-flag arguments from an rm-like command. Best-effort tokenize."""
    # Strip comment lines (bypass markers etc) before tokenizing
    cmd_no_comments = re.sub(r"#[^\n]*", "", cmd)
    try:
        tokens = shlex.split(cmd_no_comments, posix=True)
    except ValueError:
        return []
    targets: list[str] = []
    rm_seen = False
    for tok in tokens:
        if tok in ("rm", "rmdir") or tok.endswith("/rm") or tok.endswith("/rmdir"):
            rm_seen = True
            continue
        if not rm_seen:
            continue
        if tok.startswith("-"):
            continue
        # Stop at shell metacharacters that bash split would have caught earlier
        if tok in (";", "&&", "||", "|", "&"):
            rm_seen = False
            continue
        targets.append(tok)
    return targets


def all_targets_safe(cmd: str) -> bool:
    """For rm-like commands: True if every non-flag arg is in safe whitelist."""
    targets = extract_rm_targets(cmd)
    if not targets:
        return False
    return all(is_target_safe(t) for t in targets)


def main() -> None:
    event = read_event()
    if event.get("tool_name") not in {"Bash", "PowerShell"}:
        allow()
    cmd = bash_command(event.get("tool_input", {}))
    if not cmd:
        allow()

    # Step 1: any destructive intent?
    hit = any_match(cmd, DESTRUCTIVE_INTENT, command=True)
    if not hit:
        allow()

    # Step 2: rm-like command on only-safe targets — allow silently
    is_rm_like = bool(re.search(r"\b(rm|rmdir)\b", cmd))
    if is_rm_like and all_targets_safe(cmd):
        log("INFO", "require_human_confirmation", "safe-target", hit, cmd[:200])
        allow()

    log("BLOCK", "require_human_confirmation", "approval-interface-unavailable", hit, cmd[:300])
    block(
        "Эта операция destructive и заблокирована.\n\n"
        f"Detected pattern: /{hit}/\n\n"
        "Текущий hook API не передаёт проверяемую запись одобрения от user. "
        "Маркер в команде, фраза, timestamp, env или файл, который может создать agent, "
        "не являются доказательством human approval.\n\n"
        "Нужен host-issued одноразовый approval record, привязанный к действию, target, "
        "session и expiry. Пока такого интерфейса нет, destructive operation не выполняется.\n\n"
        "Исключения: только whitelisted routine build/cache/temp targets."
    )


if __name__ == "__main__":
    main()
