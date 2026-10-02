#!/usr/bin/env python3
"""PreToolUse: fail closed for destructive intent until the host can prove approval.

Universal "human-in-the-loop" gate for any irreversible operation that removes /
drops / deletes / terminates / overwrites. Replaces narrow catastrophic-only check
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
    executable_text,
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
    # cmd.exe deletes reached through a wrapper; a bare `rd`/`del` as the first
    # word of a segment is caught structurally by decide(), not by this list
    r"\bcmd(?:\.exe)?\s+/[ck]\s+.*\b(?:rd|rmdir|del|erase)\b",
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

    # Communication APIs. `gh pr close` without `-d` / `--delete-branch`
    # preserves the branch and GitHub supports reopening the pull request, so it
    # is reversible project state, not deletion.
    r"\bgh\s+pr\s+close\b[^|;&\n]*\s(?:-d|--delete-branch)\b",
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
    r"\.swp(\s|$|/)",
    r"\.swo(\s|$|/)",
    r"\.pyc(\s|$|/)",
    r"\.DS_Store(\s|$|/)",
    r"Thumbs\.db(\s|$|/)",
]

# Temporary files may be removed without asking (owner directive 2026-09-26:
# "временные файлы можно удалять без разрешения, а то они копятся").
# Temporary = strictly inside an OS temp root (from the OS, not a list: on this
# machine TEMP is D:\tmp), or a target whose OWN name is one that a tool generates
# for scratch. A human-chosen name like `.tmp-notes` is not proof (review
# 2026-09-26), and a matching name higher up the path whitelists nothing.
# simplification: `tmp` + 8 [a-z0-9_] can collide with a real folder such as
# `tmpservers1`; tighten to a sibling check if that ever happens.
TEMP_NAME_PATTERNS = [
    r"^tmp[a-z0-9_]{8}$",                        # tempfile.mkdtemp() default names
    r"^pytest-of-[^/]+$",                        # pytest basetemp
]
DELETE_COMMANDS = {"rm", "rmdir", "remove-item", "ri", "del", "erase", "rd"}
# Remove-Item parameters without a value; any other -Param consumes the next token.
PS_SWITCHES = {"recurse", "r", "force", "whatif", "verbose", "confirm"}
PS_PATH_PARAMS = {"path", "literalpath", "lp", "pspath"}
# Owner approval 2026-10-02 is bound to this remote and this closed set only.
# Do not turn names such as `production-bench` into a blanket deletion bypass.
WORKSHOP_VM_SSH_TARGET = "ws@workshop-vm"
WORKSHOP_VM_APPROVED_DOCKER_CONTAINERS = frozenset({
    "qwen3-8b-bench",
    "qwen3-8b-bench2",
    "qwen3vl-4b-bench",
})


def _norm(target: str) -> str:
    s = target.strip().strip("'\"").replace("\\", "/")
    m = re.match(r"^/([a-zA-Z])(?=/|$)", s)  # git-bash /d/tmp -> D:/tmp
    if m:
        s = f"{m.group(1).upper()}:{s[2:] or '/'}"
    return s


def _temp_roots() -> list[str]:
    import os
    import tempfile
    raw = {tempfile.gettempdir(), os.environ.get("TEMP", ""), os.environ.get("TMP", ""),
           "/tmp", "/var/tmp", "/private/tmp"}
    return sorted({_norm(r).rstrip("/").lower() for r in raw if r})


def is_temp_target(target: str) -> bool:
    t = _norm(target).rstrip("/")
    low = t.lower()
    if any(low.startswith(root + "/") and len(low) > len(root) + 1 for root in _temp_roots()):
        return True
    parent, _, last = t.rpartition("/")
    if not any(re.match(p, last, re.IGNORECASE) for p in TEMP_NAME_PATTERNS):
        return False
    # the name counts only where tools actually drop it: directly in a repo root
    # (pytest basetemp, tempfile in cwd), not anywhere on disk (review round 2)
    return bool(parent) and (Path(parent) / ".git").exists()


def is_target_safe(target: str) -> bool:
    """One delete target is routine build/cache/temp. Imported by dev_artifact_sweep."""
    t = _norm(target)
    if not t or re.search(r"[$%`]", t):   # unexpanded variable: target unknown
        return False
    if "/../" in f"/{t}/":                 # traversal out of a safe dir
        return False
    if re.match(r"^[A-Za-z]{2,}:", t):     # PowerShell provider (HKCU:, Env:, Cert:)
        return False
    if is_temp_target(t):
        return True
    for pat in SAFE_TARGET_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def delete_targets(segment: str) -> list[str] | None:
    """Targets of an rm / Remove-Item segment, or None if the segment is not a delete."""
    try:  # posix=False: posix mode would eat Windows backslashes
        toks = [t.strip("'\"") for t in shlex.split(re.sub(r"(?m)#[^\n]*", "", segment), posix=False)]
    except ValueError:
        return None
    while toks and toks[0].lower() in {"sudo", "command", "&"}:
        toks = toks[1:]
    if not toks:
        return None
    verb = toks[0].lower().rsplit("/", 1)[-1].removesuffix(".exe")
    if verb not in DELETE_COMMANDS:
        return None
    targets: list[str] = []
    rest = toks[1:]
    i = 0
    end_of_flags = False
    while i < len(rest):
        tok = rest[i]
        if not end_of_flags and tok == "--":
            end_of_flags = True
        elif not end_of_flags and tok.startswith("-") and len(tok) > 1:
            name = tok[1:].lower()
            if name in PS_PATH_PARAMS and i + 1 < len(rest):
                targets.extend(x for x in rest[i + 1].split(",") if x)
                i += 1
            elif name in PS_SWITCHES or ":" in name or name.startswith("-"):
                pass  # value-less switch, -Confirm:$false, --recursive
            elif verb in {"rm", "rmdir"} and name.isalpha() and len(name) <= 3:
                pass  # POSIX rm -rf / -r / -f
            elif i + 1 < len(rest):
                i += 1  # -ErrorAction SilentlyContinue: skip the value
        else:
            targets.extend(x for x in tok.split(",") if x)
        i += 1
    return targets


def is_ephemeral_docker_rm(segment: str) -> bool:
    """Allow exactly the owner-approved stopped-container cleanup, never force.

    This is a one-scope exception: the SSH target and every container name are
    closed. `docker rm` without `--force` still fails for a running container.
    All other Docker-destructive routes remain confirmation-required.
    """
    try:
        toks = [t.strip("'\"") for t in shlex.split(segment, posix=False)]
    except ValueError:
        return False
    if (len(toks) >= 6 and toks[0:2] == ["tailscale", "ssh"]
            and toks[2] == WORKSHOP_VM_SSH_TARGET
            and toks[3:5] == ["docker", "rm"]):
        targets = toks[5:]
    else:
        return False
    if not targets or any(target == "--" or target.startswith("-") for target in targets):
        return False
    return all(target in WORKSHOP_VM_APPROVED_DOCKER_CONTAINERS for target in targets)


def split_segments(text: str) -> list[str]:
    """Split on && || ; | newline, but never inside '...' or "..." (a commit
    message saying "step; del old" is not a del command - review round 2)."""
    out: list[str] = []
    buf: list[str] = []
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif text.startswith(("&&", "||"), i):
            out.append("".join(buf))
            buf = []
            i += 2
            continue
        elif c in ";|\n":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    out.append("".join(buf))
    return out


def decide(cmd: str) -> tuple[bool, str | None]:
    """(allowed, hit). Every destructive segment must delete routine targets only.

    A segment is destructive when it matches DESTRUCTIVE_INTENT OR its command
    word is a delete verb (rm without -r, del, rd, ri, erase): review 2026-09-26
    found those verbs passing untouched because no pattern named them.
    """
    whole_hit = any_match(cmd, DESTRUCTIVE_INTENT, command=True)
    flagged = False
    for seg in (s.strip() for s in split_segments(executable_text(cmd))):
        if not seg:
            continue
        if is_ephemeral_docker_rm(seg):
            flagged = True
            continue
        targets = delete_targets(seg)
        seg_hit = any_match(seg, DESTRUCTIVE_INTENT)
        if targets is None and not seg_hit:
            continue
        flagged = True
        if not targets or not all(is_target_safe(t) for t in targets):
            return False, seg_hit or "delete-command-word"
    if whole_hit and not flagged:
        return False, whole_hit  # a hit no single segment carries: stay closed
    return True, whole_hit or ("delete-command-word" if flagged else None)


def main() -> None:
    event = read_event()
    if event.get("tool_name") not in {"Bash", "PowerShell"}:
        allow()
    cmd = bash_command(event.get("tool_input", {}))
    if not cmd:
        allow()

    # No destructive intent, or every destructive segment deletes only routine
    # build/cache/temp targets -> allow silently.
    allowed, hit = decide(cmd)
    if allowed:
        if hit:
            log("INFO", "require_human_confirmation", "safe-target", hit, cmd[:200])
        allow()

    log("BLOCK", "require_human_confirmation", "approval-interface-unavailable", hit, cmd[:300])
    # A leftover git lock is the one deletion an agent can settle itself: the
    # tool below proves "no owner" (age + no older git process) before unlinking.
    lock_hint = ""
    if re.search(r"\.lock\b", cmd, re.IGNORECASE):
        lock_hint = (
            "Если это зависший git-лок (.git/index.lock и т.п.), не удаляй его rm. "
            "Выполни: python ~/.claude/claude-code-config/scripts/git_stale_lock.py <repo> --remove "
            "— он удалит лок только при доказанном отсутствии владельца и проверит git status.\n\n"
        )
    block(
        lock_hint +
        "Эта операция destructive и заблокирована.\n\n"
        f"Detected pattern: /{hit}/\n\n"
        "Текущий hook API не передаёт проверяемую запись одобрения от user. "
        "Маркер в команде, фраза, timestamp, env или файл, который может создать agent, "
        "не являются доказательством human approval.\n\n"
        "Нужен host-issued одноразовый approval record, привязанный к действию, target, "
        "session и expiry. Пока такого интерфейса нет, destructive operation не выполняется.\n\n"
        "Исключения: только whitelisted routine build/cache/temp targets."
    )


def self_test() -> int:
    """Negative controls: every must-block case blocks, every temp/build delete passes."""
    import tempfile
    tmp = tempfile.gettempdir()
    repo_root = Path(__file__).resolve().parents[1]
    allow_cases = [
        "rm -rf /tmp/x",
        f"rm -rf {tmp}/claude-scratch/abc",
        f'Remove-Item -Recurse -Force "{tmp}\\claude\\x"',
        f"Remove-Item -LiteralPath '{tmp}\\a.txt' -ErrorAction SilentlyContinue",
        f"rm -rf {repo_root.as_posix()}/tmp0c9bxbq2",
        f"rm -rf {repo_root.as_posix()}/pytest-of-sandbox",
        "rm -rf build && rm -rf dist",
        f"del {tmp}\\stale.txt",
        'git commit -m "step; del old; rm tmp"',                  # quoted text is not a command
        "echo 'a | rm -rf /data'",
        "cat > s.sh <<'EOF'\nrm -rf /workspace/sample/project\nEOF",   # heredoc body is not executed
        "ls -la",
        "tailscale ssh ws@workshop-vm docker rm qwen3-8b-bench qwen3-8b-bench2 qwen3vl-4b-bench",
    ]
    block_cases = [
        f"rm -rf {tmp}",                                   # the temp root itself
        f"rm -rf {tmp}/../Users",                           # traversal
        "rm -rf $TMPDIR/x",                                 # unexpanded variable
        "Remove-Item -Recurse -Force C:\\agent-home\\project",
        "rm -rf /tmp/x && git reset --hard",                # piggy-backed destructive op
        "rm -rf build; DROP TABLE users",
        "Remove-Item HKCU:\\Software\\tmp12345678",         # registry provider
        f"Remove-Item {tmp}\\x, D:\\data",                   # one unsafe target in a list
        "Remove-Item -Path D:\\data -ErrorAction SilentlyContinue",
        "rm -rf /workspace/sample/.tmpfiles/../../etc",     # traversal through a temp name
        "rm -rf ~/project",
        # review 2026-09-26 round 1: delete verbs no pattern named
        "ri -Recurse -Force C:\\agent-home\\project",
        "del -Recurse -Force C:\\agent-home\\project",
        "rd /s /q C:\\agent-home\\important",
        "del /s /q C:\\agent-home\\important",
        "erase C:\\data\\file.txt",
        "cmd /c rd /s /q C:\\agent-home\\important",
        "rm C:\\data\\important.txt",
        "rm -f secret.key",
        "Get-ChildItem C:\\data | Remove-Item",
        # a scratch-looking NAME is not proof when a human chose it
        "rm -rf /workspace/sample/.tmp-notes",
        "rm -rf /workspace/sample/.tmp-notes/important",
        "rm -rf /srv/data/.temp-backups",
        # Backup, rejected patch, and logs may be the sole human evidence. An
        # extension alone does not prove a file is regenerable or disposable.
        "rm -f C:/work/only-copy.bak",
        "rm -f C:/work/merge.orig",
        "rm -f C:/work/failed.rej",
        "rm -f C:/work/audit.log",
        "rm -rf /workspace/sample/tmpabcdefgh/important",    # name above the target
        "rm -rf C:/work/tmpservers1",                        # mkdtemp-like name outside a repo root
        "git commit -m 'ok'; del C:\\data\\x",               # real del after a quoted message
        "docker rm -f qwen3-8b-bench",
        "docker rm production-db",
        "docker rm qwen3-8b-bench",
        "tailscale ssh ws@production-vm docker rm qwen3-8b-bench",
        "tailscale ssh ws@workshop-vm docker rm production-bench",
        "tailscale ssh ws@workshop-vm docker rm --force qwen3-8b-bench",
    ]
    fails = [f"should allow: {c}" for c in allow_cases if not decide(c)[0]]
    fails += [f"should block: {c}" for c in block_cases if decide(c)[0]]
    for f in fails:
        print("SELF-TEST FAIL:", f)
    print(f"SCANNED: allow={len(allow_cases)} block={len(block_cases)}")
    print("SELF-TEST", "PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    main()
