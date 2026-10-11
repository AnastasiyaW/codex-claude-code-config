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
| destructive intent | target whitelist | owner request in transcript | result |
|---|---|---|---|
| no                 | n/a              | -              | allow |
| yes                | all targets safe | -              | allow (silent) |
| plain file delete  | non-safe target  | yes, names every target | allow + audit record |
| yes                | non-safe target  | absent / other kind of op | **BLOCK** |

Owner request (2026-10-06, owner: "поправь хук, чтобы ты сама удаляла по моей просьбе")
======================================================================================
The approval source is the session transcript the HOST writes (event
`transcript_path`), not anything in the command: the latest entry with
`type=user`, `origin.kind=human`, not `isMeta`, not a sidechain. Hook feedback,
task notifications and tool results carry other markers and never count.
A plain file delete (rm/rmdir/del/rd/erase/Remove-Item, also inside
`ssh host '...'`, `bash -c`, `powershell -Command`) is allowed when that prompt
asks to delete (imperative; no negation, "нет", "оставь", no question) and
EVERY target is named as a whole token: the full absolute path always counts;
the bare file name (with extension) counts only for a non-recursive delete
without "из/from" phrasing. The agent's previous answer is consulted only when
the prompt is a bare go-ahead ("да", "да, удаляй"). Hard limits stay regardless:
relative paths, globs, variables, @(), UNC, traversal, `.git`, `~/.claude`,
`.ssh`, system dirs, drive roots, home folders and their direct children,
registry/providers, `xargs rm`, and any non-file destructive op (DROP, docker,
git reset, kill...). Any exception inside the guard blocks (fail closed).
Every allow writes an audit line to
~/.claude/logs/deletion-approvals.jsonl. Residual risk: the transcript is a
local file an agent could write to; a command that references the transcript
itself is refused, file-tool writes to it are out of this hook's reach.

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
There is intentionally no bypass marker for this hook: command text is never
approval. CI/CD pipelines should not run inside Claude Code sessions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
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
    # owner-approved list delete (approved_by_owner checks the list); a lone --show only reads it
    # delete_from_list.py is judged in decide() (LIST_MENTION): any mention is a delete unless
    # it is a strict read-only --show call or a one-line git command (review round 9).
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
    r"\bfind\b.*-exec(?:dir)?\s+\\?(?:rm|rmdir|unlink|shred)\b",   # review 2026-10-06 round 3
    r"\[(?:system\.)?io\.(?:file|directory)\]::delete\b",
    r"\bunlink\s+",
    r"\bxargs\b[^|;&\n]*?\b(?:rm|rmdir|del|shred|unlink)\b",  # targets from stdin (review 2026-10-06)
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
DELETE_COMMANDS = {"rm", "rmdir", "remove-item", "ri", "del", "erase", "rd", "unlink"}
# Words after which the next word is again a command (grouping, wrappers, script blocks).
COMMAND_PREFIXES = {"sudo", "command", "&", "{", "(", "then", "do", "else", "time", "nohup", "nice",
                    "exec", "env", "%", "foreach-object", "foreach", "!", "xargs"}
# Remove-Item parameters without a value; any other -Param consumes the next token.
PS_SWITCHES = {"recurse", "r", "force", "whatif", "verbose", "confirm"}
PS_PATH_PARAMS = {"path", "literalpath", "lp", "pspath"}
# Owner approval 2026-10-02 is bound to one remote and a closed set of containers only.
# Do not turn names such as `production-bench` into a blanket deletion bypass.
# The host and container names are private infrastructure, so they live in a local file
# outside this public repository: {"ephemeral_docker_ssh_target": "user@host",
# "ephemeral_docker_containers": ["name", ...]}. Missing/invalid file -> no exception at all.
LOCAL_CONFIG = Path.home() / ".claude" / "local" / "human-confirmation-guard.json"


def _local_config() -> dict:
    try:
        cfg = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


_CFG = _local_config()
WORKSHOP_VM_SSH_TARGET = str(_CFG.get("ephemeral_docker_ssh_target") or "")
WORKSHOP_VM_APPROVED_DOCKER_CONTAINERS = frozenset(
    c for c in (_CFG.get("ephemeral_docker_containers") or []) if isinstance(c, str) and c)


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
        toks = [t.strip("'\"") for t in shlex.split(re.sub(r"(?m)(?:^|(?<=\s))#[^\n]*", "", segment), posix=False)]
    except ValueError:
        return None
    def norm_word(w: str) -> str:  # \rm, r''m, r`m (PowerShell escape) all run `rm`
        return re.sub(r"[\\'\"`]", "", w).lower().rsplit("/", 1)[-1].removesuffix(".exe")
    while toks and (norm_word(toks[0]) in COMMAND_PREFIXES or toks[0].endswith(("{", "("))
                    or re.fullmatch(r"\w+=\S*|\d+|-\w+", toks[0])):
        toks = toks[1:]
    if not toks:
        return None
    verb = norm_word(toks[0])
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


MOVE_FLAGS = {"-f", "--force", "-T", "--no-target-directory", "-v", "--verbose"}


def move_overwrite_targets(segment: str) -> list[str] | None:
    """Destination of `mv [-f|-T|-v] SRC DST`: the file a replacement overwrites (owner 2026-10-11).
    None for any other shape (several sources, -t, unknown flags), which stays unapproved."""
    # simplification: POSIX mv only; a Move-Item replacement still needs an explicit delete request
    try:
        toks = [t.strip("'\"") for t in shlex.split(segment, posix=False)]
    except ValueError:
        return None
    if not toks or toks[0].rsplit("/", 1)[-1] != "mv":
        return None
    flags = [t for t in toks[1:] if t.startswith("-")]
    operands = [t for t in toks[1:] if not t.startswith("-")]
    if any(f not in MOVE_FLAGS for f in flags) or len(operands) != 2:
        return None
    return [operands[1]]


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
            and WORKSHOP_VM_SSH_TARGET and toks[2] == WORKSHOP_VM_SSH_TARGET
            and toks[3:5] == ["docker", "rm"]):
        targets = toks[5:]
    else:
        return False
    if not targets or any(target == "--" or target.startswith("-") for target in targets):
        return False
    return all(target in WORKSHOP_VM_APPROVED_DOCKER_CONTAINERS for target in targets)


# ssh options that take an argument (OpenSSH 9.x synopsis: -B -b -c -D -E -e -F -I -i -J -L -l
# -m -O -o -P -p -Q -R -S -W -w). Review 2026-10-06: missing B/P let `ssh -B eth0 host rm ...` through.
SSH_OPTS_WITH_ARG = set("BbcDEeFIiJLlmOoPpQRSWw")
REMOTE_WRAPPERS = {"sudo", "nice", "command", "env", "nohup", "exec"}
UNPARSED = "\x00unparsed-ssh"
INNER_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}


def remote_command(segment: str) -> str | None:
    """The command a `[timeout N] ssh [opts] host CMD` / `tailscale ssh host CMD` segment runs remotely.

    A delete sent over ssh is the same delete: review 2026-10-06 found a plain
    `ssh host 'rm /data/x'` passing untouched because the segment's command word is ssh.
    Returns None when the segment is not ssh, UNPARSED when it is ssh we cannot read.
    """
    try:
        toks = shlex.split(segment, posix=True)
    except ValueError:
        return UNPARSED if re.match(r"\s*(?:\S*/)?(?:tailscale\s+)?ssh(?:\.exe)?\s", segment) else None
    i = 0
    while i < len(toks):
        if toks[i] == "timeout" and i + 1 < len(toks) and re.fullmatch(r"\d+[smhd]?", toks[i + 1]):
            i += 2
        elif toks[i] in REMOTE_WRAPPERS or re.fullmatch(r"\w+=\S*", toks[i]):
            i += 1
        else:
            break
    word = toks[i].rsplit("/", 1)[-1].lower().removesuffix(".exe") if i < len(toks) else ""
    if word in INNER_SHELLS and i + 2 < len(toks) and re.fullmatch(r"-[a-z]*c", toks[i + 1]):
        return toks[i + 2]  # bash -c '<cmd>': the string is the command (review 2026-10-06)
    if word in {"powershell", "pwsh"}:
        j = i + 1
        while j < len(toks) and toks[j].lower() not in {"-c", "-command", "-encodedcommand", "-ec"}:
            j += 1
        if j + 1 < len(toks):
            return UNPARSED if toks[j].lower() in {"-encodedcommand", "-ec"} else " ".join(toks[j + 1:])
    if i < len(toks) and toks[i] == "tailscale" and toks[i + 1:i + 2] == ["ssh"]:
        i += 2
    elif i < len(toks) and toks[i].rsplit("/", 1)[-1].removesuffix(".exe") == "ssh":
        i += 1
    else:
        return None  # ssh only as an argument (rsync -e ssh, which ssh): nothing runs remotely here
    while i < len(toks) and toks[i].startswith("-") and toks[i] != "--":
        flags = toks[i][1:]
        i += 1
        for pos, c in enumerate(flags):  # combined flags: -Tp 2222, -p2222, -4vi key
            if c in SSH_OPTS_WITH_ARG:
                if pos == len(flags) - 1:
                    i += 1  # the argument is the next token
                break
    if i < len(toks) and toks[i] == "--":
        i += 1
    if i >= len(toks):
        return None  # no host: nothing runs remotely
    rest = toks[i + 1:]  # toks[i] is the host
    return " ".join(rest) if rest else None


def split_segments(text: str) -> list[str]:
    """Split on && || ; | newline, but never inside '...' or "..." (a commit
    message saying "step; del old" is not a del command - review round 2)."""
    out: list[str] = []
    buf: list[str] = []
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and quote != "'" and i + 1 < len(text):
            buf.append(text[i:i + 2])  # \" \; \<newline> are literal to the shell (review 2026-10-06)
            i += 2
            continue
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


def substitutions(text: str) -> list[str]:
    """Bodies of $(...) and `...` outside single quotes: they execute (review 2026-10-06)."""
    out: list[str] = []
    i, quote = 0, None
    while i < len(text):
        c = text[i]
        if c == "\\" and quote != "'":
            i += 2
            continue
        if quote == "'":
            quote = None if c == "'" else quote
        elif c == "'" and quote is None:
            quote = "'"
        elif c == '"':
            quote = None if quote == '"' else '"'
        elif text.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            out.append(text[i + 2:j - 1])
            i = j
            continue
        elif c == "`":
            j = text.find("`", i + 1)
            if j == -1:
                out.append(text[i + 1:])
                break
            out.append(text[i + 1:j])
            i = j + 1
            continue
        i += 1
    return out


def hidden_deletes(segment: str) -> list[str]:
    """Sub-commands that start with a delete verb in command position inside a segment:
    `{ rm x; }`, `if true; then rm x`, `& { del x }`, `1 | % { ri x }` (review 2026-10-06 round 3)."""
    out: list[str] = []
    pieces = re.split(r"[{}()]|\b(?:then|do|else|time|nohup|exec)\b", segment)
    for piece in pieces[1:]:
        if piece.strip() and delete_targets(piece.strip()) is not None:
            out.append(piece.strip())
    return out


def decide(cmd: str) -> tuple[bool, str | None]:
    """(allowed, hit). Every destructive segment must delete routine targets only.

    A segment is destructive when it matches DESTRUCTIVE_INTENT OR its command
    word is a delete verb (rm without -r, del, rd, ri, erase): review 2026-09-26
    found those verbs passing untouched because no pattern named them.
    """
    # review round 9: fail closed on the list script (line breaks, backticks, runpy argv tricks
    # all still mention it) and on inline-Python deletes the verb patterns never saw.
    # review round 11: shell quoting splits a name ('' "" \ `) - match on the de-quoted text too
    dequoted = re.sub(r"[\"'`\\]", "", cmd)
    if (LIST_MENTION.search(cmd) or LIST_MENTION.search(dequoted)) and not _benign_list_mention(cmd):
        return False, "delete_from_list run"
    if INLINE_PY_DELETE.search(cmd):
        return False, "inline python delete"
    if GLOB_SCRIPT.search(cmd):  # review round 10: the script name hidden behind a shell glob
        return False, "python script given by a glob"
    whole_hit = any_match(cmd, DESTRUCTIVE_INTENT, command=True)
    flagged = False
    for inner in substitutions(cmd):
        ok, ihit = decide(inner)
        if not ok:
            return False, ihit or "substitution-delete"
        flagged = flagged or bool(ihit)
    segments = split_segments(executable_text(cmd))
    if re.search(r"\\[\"']", cmd):
        # executable_text (shared helper) does not honour \" and would mask `echo \"a; rm x; b\"`
        # as a quoted echo argument; with escaped quotes present judge the raw split as well.
        segments += split_segments(cmd)
    for seg in (s.strip() for s in segments):
        if not seg:
            continue
        if is_ephemeral_docker_rm(seg):
            flagged = True
            continue
        remote = remote_command(seg)
        if remote == UNPARSED:
            return False, "unparsed-remote-or-inner-command"
        if remote:
            ok, rhit = decide(remote)
            if not ok:
                return False, rhit or "remote-delete"
            flagged = flagged or bool(rhit)
            continue
        targets = delete_targets(seg)
        if targets is None:
            hidden = hidden_deletes(seg)
            if hidden:
                targets = [t for h in hidden for t in (delete_targets(h) or [])] or []
        seg_hit = any_match(seg, DESTRUCTIVE_INTENT)
        if targets is None and not seg_hit:
            continue
        flagged = True
        if not targets or not all(is_target_safe(t) for t in targets):
            return False, seg_hit or "delete-command-word"
    if whole_hit and not flagged:
        return False, whole_hit  # a hit no single segment carries: stay closed
    return True, whole_hit or ("delete-command-word" if flagged else None)


# ---------------------------------------------------------------------------
# Owner-requested deletes (see module docstring). Hardened after the 2026-10-06
# independent review (REJECT): substring naming, relative paths, the agent's own
# text widening scope, "remove X from file", crash-on-malformed transcript.
# ---------------------------------------------------------------------------
# Imperative / infinitive only: "вроде удалила" reports a past deletion, it is not a request.
DELETE_INTENT = re.compile(
    r"\b(?:удали(?:те)?|удаляй(?:те)?|удалить|удалим|снеси(?:те)?|снести|сотри(?:те)?|стереть|"
    r"почисти(?:те)?|очисти(?:те)?|убери(?:те)?|убрать)\b|"
    r"\bdelete\b|\bremove\b|\brm\b|\bwipe\b|\berase\b", re.IGNORECASE)
# Owner 2026-10-11 ("замену case.json разрешаю" was refused): asking to replace a file approves
# overwriting it with mv, never an rm of it.
REPLACE_INTENT = re.compile(
    r"\b(?:замени(?:те)?|заменить|заменим|замену|перезапиши(?:те)?|перезаписать|перезапись)\b|"
    r"\breplace\b|\boverwrite\b", re.IGNORECASE)
REPLACE_MENTION = re.compile(r"замен|перезапис|replac|overwrit", re.IGNORECASE)
# Owner 2026-10-11 ("да, перезапускай VM" was refused; "исправляй хук, если я попросила сделать,
# надо делать"): asking to restart approves a command that is nothing but a restart verb.
RESTART_INTENT = re.compile(
    r"\b(?:перезапусти(?:те)?|перезапускай(?:те)?|перезапустить|перезапустим|перезагрузи(?:те)?|"
    r"перезагружай(?:те)?|перезагрузить|перезагрузим|ребутни(?:те)?|ребутай(?:те)?)\b|"
    r"\breboot\b|\brestart\b", re.IGNORECASE)
RESTART_MENTION = re.compile(r"перезапуск|перезапуст|перезагруз|ребут|reboot|restart", re.IGNORECASE)
NOT_A_RESTART_GO = re.compile(r"\bне\s+(?:надо\s+|нужно\s+|стоит\s+|смей\s+)?(?:перезап|перезагр|ребут)",
                              re.IGNORECASE)
# The whole segment is a restart and nothing else: no rm, no power-off, no service stop beside it.
RESTART_SEGMENT = re.compile(
    r"(?:sudo\s+(?:-\S+\s+)*)?(?:reboot|systemctl\s+reboot|shutdown\s+-r(?:\s+(?:now|\+\d+))?|"
    r"virsh\s+reboot\s+[\w.-]+|restart-computer(?:\s+-force)?)\s*;?", re.IGNORECASE)
# Anything that makes the request not a plain go-ahead: negation, "keep", "no", a question.
NOT_A_GO = re.compile(
    r"\bне\s+(?:надо\s+|нужно\s+|стоит\s+|смей\s+)?(?:удал|снос|снес|стир|сотр|трог|чист|убир|замен|перезапис)|"
    r"\bнельзя\b|\bнет\b|\bоставь|\bпогоди|\bподожди|\bdon'?t\b|\bdo\s+not\b|\bnever\b|\bkeep\b|\bno\b|\?",
    re.IGNORECASE)
# "убери X из файла" / "remove the print from train.py" edits a file; only a full path counts then.
FROM_PHRASE = re.compile(r"\s(?:из|изо|from|out\s+of)\s", re.IGNORECASE)
# My answer only has to be ABOUT deleting (a proposal "Удалю X - подтверди"); the request must ask.
DELETE_MENTION = re.compile(r"удал|снес|сотр|стер|почист|очист|delete|remov|\brm\b|wipe|erase", re.IGNORECASE)
# A bare go-ahead and nothing else: "да", "да, удаляй", "ок!", "yes".
CONFIRM_ONLY = re.compile(
    r"\s*(?:да|ага|ок|окей|ok|okay|yes|подтверждаю|удаляй|давай|можно)"
    r"(?:[\s,]+(?:да|удаляй|давай|можно|ок|ok|yes|подтверждаю|вс[её]|по\s+списку|список))*\s*[.!]*\s*",
    re.IGNORECASE)
# "да /full/path" to my proposal: a go-ahead that names exactly what it covers (owner 2026-10-11).
CONFIRM_PATHS = re.compile(
    r"\s*(?:да|ок|ok|yes|подтверждаю|удаляй|заменяй)[\s,:]+(?:[A-Za-z]:)?[\\/]\S+(?:\s+(?:[A-Za-z]:)?[\\/]\S+)*\s*",
    re.IGNORECASE)
# Owner decision 2026-10-11: a long delete list goes into a file instead of the chat. My answer
# shows `deletion-list: <path> sha256:<hex>`; a bare go-ahead to that answer approves exactly that
# file's lines, and only scripts/delete_from_list.py may act on it. The digest binds the approval
# to the content the owner was shown; every listed path still passes target_hard_limit.
DELETION_LIST_DIR = Path.home() / ".claude" / "state" / "deletion-lists"
LIST_REF = re.compile(r"deletion-list:\s*(\S+?\.txt)\s+sha256:([0-9a-fA-F]{16,64})")
LIST_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts" / "delete_from_list.py")
# review 2026-10-11 F1: no separators, substitutions or redirects anywhere in a list-delete call
LIST_CALL_FORBIDDEN = re.compile(r"[;|`$()<>\n\r{}]|&(?!\s)|\s&\s*\S.*&")
PYTHON_NAMES = {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}


# Owner decision 2026-10-11: "a general yes, without naming files, works for everything
# regenerable; explicit confirmation only for the irreplaceable, e.g. database backups or a
# database". Unnamed targets therefore pass a general go-ahead unless they look irreplaceable
# (or a folder's contents cannot be inspected from here); those still have to be named.
IRREPLACEABLE = re.compile(
    # database files, their journals and dumps, plain or compressed (review 2026-10-11 R4)
    r"\.(?:db|db3|sqlite\d?|sqlite\d?-(?:wal|shm)|db-(?:wal|shm)|mdb|accdb|dump|pgdump|sql|bak|backup|"
    r"kdbx|rdb|aof|ibd|mdf|ldf|ndf|frm|myd|myi|fdb|gdb|realm|ldb|sdf|ost|pst)"
    r"(?:\.(?:gz|bz2|xz|zst|7z|zip|tar|tgz))?$|-journal$|"
    # server data directories recognised by their marker files (review R5)
    r"(?:^|/)(?:PG_VERSION|pg_wal|pg_xlog|ibdata\d*|dump\.rdb|appendonly\.aof|WiredTiger[^/]*)(?:/|$)|"
    r"(?:^|/)[^/]*(?:backup|бэкап|бекап|snapshot|pgdata|postgres|mysql|mariadb|mongo|redis|"
    r"dataset|датасет)[^/]*(?:/|$)",
    re.IGNORECASE)
# The request itself names a file or path (then only named targets are covered).
NAMES_FILE = re.compile(r"[\w\-]+\.[A-Za-z0-9]{1,8}\b|[\w\-.]+[\\/][\w\-.]")
CONTENT_SCAN_CAP = 200_000  # simplification: bounded walk; a bigger folder must be named explicitly


INNER_NAME_CAP = 50  # simplification: more irreplaceable files inside a folder -> name them one by one
WALK = os.walk  # indirection so the self-test can simulate an unreadable subtree (review R10)
LSTAT = os.lstat  # same, for a target that cannot be stat'ed (review R11)


def _kind(p: Path) -> str:
    """'missing' | 'dir' | 'file' | 'link' | 'error'. Path.is_file/is_dir/exists swallow
    PermissionError and answer False (review R11); here only a real "not found" counts as missing."""
    try:
        st = LSTAT(p)
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except OSError:
        return "error"
    if stat.S_ISLNK(st.st_mode):
        return "link"
    return "dir" if stat.S_ISDIR(st.st_mode) else "file"


def _sqlite_header(p: Path) -> bool | None:
    """True/False for a readable file; None when it cannot be read (review R10: unknown, not clean)."""
    try:
        with p.open("rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return None


def irreplaceable_info(target: str, recursive: bool) -> tuple[str | None, list[str] | None]:
    """(why the target needs the owner's own naming, irreplaceable file names inside a folder).
    (None, []) means regenerable; inner=None means the folder could not be fully inspected and
    may not be deleted as a whole at all (review R9: fail closed, no naming escape)."""
    t = _norm(target).rstrip("/")
    if IRREPLACEABLE.search(t):
        return "database/backup/dataset path", []
    p = Path(t)
    kind = _kind(p)
    if kind == "error":
        return "cannot be checked from here (access denied)", None
    if kind == "file":
        header = _sqlite_header(p)  # review R5: a SQLite file without a telling name
        if header is None:
            return "file cannot be read to check it", None
        if header:
            return "SQLite database (file header)", []
    # Owner 2026-10-11: on a server regenerable folders go too; a folder that cannot be
    # inspected from here (remote, kind 'missing') is judged by its path alone.
    if recursive and kind == "dir":
        inner: list[str] = []
        walk_errors: list[OSError] = []
        n = 0
        # review R10: os.walk with onerror, not rglob (which silently skips unreadable subtrees)
        for root, dirs, files in WALK(p, onerror=walk_errors.append, followlinks=False):
            for name in dirs + files:
                n += 1
                if n > CONTENT_SCAN_CAP:
                    return "too many entries to inspect", None
                f = Path(root) / name
                fk = _kind(f)
                if fk == "error":
                    return f"cannot check {f.as_posix()} (access denied)", None
                header = _sqlite_header(f) if fk == "file" else False
                if header is None:
                    return f"cannot read {f.as_posix()} to check it", None
                # review R8: inside a folder judge every file by name AND by SQLite header
                if IRREPLACEABLE.search(f.as_posix()) or header:
                    inner.append(name)
                    if len(inner) > INNER_NAME_CAP:
                        return "too many databases/backups inside", None
        if walk_errors:
            return f"part of the folder cannot be read ({walk_errors[0]})", None
        if inner:
            return f"contains {', '.join(sorted(set(inner)))}", sorted(set(inner))
    return None, []


def irreplaceable_reason(target: str, recursive: bool) -> str | None:
    """Why an unnamed target needs explicit naming even after a general go-ahead, or None."""
    return irreplaceable_info(target, recursive)[0]


LIST_MENTION = re.compile(r"(?<![\w])delete_from_list|deletion-approvals", re.IGNORECASE)
# a .py path built by a glob, a variable or a substitution (review rounds 10-11)
GLOB_SCRIPT = re.compile(r"\b(?:python3?|py)(?:\.exe)?[\"']?\s+[\"']?[^\s\"']*[*?\[\]$%{}`][^\s\"']*\.py\b",
                         re.IGNORECASE)
GIT_PLAIN = {"add", "diff", "log", "status", "show", "commit", "blame", "restore", "stash"}
INLINE_PY_DELETE = re.compile(
    r"\bshutil\s*\.\s*rmtree\b|\brmtree\s*\(|\bos\s*\.\s*(?:remove|unlink|rmdir|removedirs)\s*\(|"
    r"\.\s*unlink\s*\(|\.\s*rmdir\s*\(|\bsend2trash\b|"
    # review round 10: a shell delete launched from inline Python
    r"(?:os\s*\.\s*system|os\s*\.\s*popen|subprocess)[^\n]*?\b(?:rm|del|rd|rmdir|erase|remove-item|unlink)\b",
    re.IGNORECASE)


def _benign_list_mention(cmd: str) -> bool:
    """A strict read-only `python <real script> <list>.txt --show`, or a one-line git command."""
    raw = cmd.strip()
    if LIST_CALL_FORBIDDEN.search(raw) or "&" in raw:  # review round 11: `git status & <run>`
        return False
    try:
        argv = shlex.split(raw.replace("\\", "/"), posix=True)
    except ValueError:
        return False
    # review round 10: no blanket git (a `-c alias.x='!...'` runs a shell); plain subcommands only
    if argv and argv[0] == "git":
        if len(argv) > 3 and argv[1] == "-C":  # `git -C <repo> <plain>`: -C only picks the repository
            argv = [argv[0]] + argv[3:]
        return (len(argv) > 1 and argv[1] in GIT_PLAIN and "-c" not in argv
                and not any(a.startswith("--config") or "!" in a for a in argv))
    if len(argv) != 4 or argv[0].lower() not in PYTHON_NAMES or argv[3] != "--show" \
            or not argv[2].lower().endswith(".txt"):
        return False
    try:
        return Path(argv[1]).expanduser().resolve(strict=True) == LIST_SCRIPT
    except OSError:
        return False


def _list_key(path: str) -> str:
    return Path(path.replace("\\", "/")).expanduser().as_posix().lower()


def read_deletion_list(path: str, sha: str) -> tuple[list[str] | None, str]:
    """Lines of an owner-shown deletion list, or (None, why) if it is outside the list folder or changed."""
    try:
        p = Path(path.replace("\\", "/")).expanduser().resolve(strict=True)
        p.relative_to(DELETION_LIST_DIR.resolve())
        data = p.read_bytes()
    except (OSError, ValueError):
        return None, f"{path}: the list must be an existing file in {DELETION_LIST_DIR}"
    if not hashlib.sha256(data).hexdigest().startswith(sha.lower()):
        return None, f"{path}: the list changed after it was shown (sha256 mismatch)"
    entries = [ln.strip() for ln in data.decode("utf-8-sig", errors="replace").splitlines()]
    return [e for e in entries if e and not e.startswith("#")], ""


def list_delete_request(cmd: str, prompt: str, answer: str) -> tuple[list[tuple[str, bool]] | None, str]:
    """(targets, "") for an approved delete_from_list.py call; (None, why) if refused; ([], "") if not one."""
    if "delete_from_list.py" not in cmd:
        return [], ""
    raw = cmd.strip()
    raw = raw[1:].lstrip() if raw.startswith("&") else raw  # PowerShell call operator
    if LIST_CALL_FORBIDDEN.search(raw):
        return None, "delete_from_list.py must be the whole command (no separators or substitutions)"
    try:
        argv = shlex.split(raw.replace("\\", "/"), posix=True)
    except ValueError:
        return None, "delete_from_list.py call cannot be parsed"
    # review R1: the interpreter is a bare name resolved from PATH, never a path the agent picked
    if (len(argv) != 5 or argv[0].lower() not in PYTHON_NAMES or argv[3] != "--sha"
            or not re.fullmatch(r"[0-9a-fA-F]{16,64}", argv[4]) or not argv[2].lower().endswith(".txt")):
        return None, "expected exactly: python <delete_from_list.py> <list.txt> --sha <hex>"
    try:  # review F2: only the real script, not a look-alike planted elsewhere
        same = Path(argv[1]).expanduser().resolve(strict=True) == LIST_SCRIPT
    except OSError:
        same = False
    if not same:
        return None, f"only {LIST_SCRIPT.as_posix()} may act on a deletion list"
    path, sha = argv[2], argv[4]
    if not CONFIRM_ONLY.fullmatch(prompt):
        return None, "a list delete needs a bare go-ahead to the answer that showed the list"
    shown = {(_list_key(p), s.lower()) for p, s in LIST_REF.findall(answer)}
    if (_list_key(path), sha.lower()) not in shown:
        return None, "this list and digest were not shown in my last answer"
    entries, why = read_deletion_list(path, sha)
    if entries is None:
        return None, why
    if not entries:
        return None, "the list is empty"
    if sys.platform == "win32":  # review F3: the script deletes on this host; a drive-less path is ambiguous
        driveless = [e for e in entries if not re.match(r"^[A-Za-z]:[\\/]", e)]
        if driveless:
            return None, f"{driveless[0]}: a listed path needs a drive letter on Windows"
    for e in entries:  # review R2: a list is a general go-ahead; the irreplaceable must be named in chat
        why = irreplaceable_reason(e, True)
        if why:
            return None, f"{e}: irreplaceable ({why}) - name it in the chat, not in a list"
    return [(e, True) for e in entries], ""
APPROVAL_LOG = Path.home() / ".claude" / "logs" / "deletion-approvals.jsonl"
TRANSCRIPT_SCAN_CAP = 64 * 1024 * 1024
PROTECTED = re.compile(
    # .claude is judged separately (_claude_limit): the home one is protected, a project's is not
    r"(?:^|/)\.(?:codex|ssh|secrets|gnupg|git|agents|config/gh)(?:/|$)|"
    r"^(?:/etc|/usr|/bin|/sbin|/lib\w*|/boot|/sys|/proc|/dev|/var/lib|/srv/?$)(?:/|$)|"
    r"^[a-z]:/(?:windows|program files[^/]*|programdata|\.secrets|\$recycle\.bin)(?:/|$)|"
    r"^[a-z]:/users/[^/]+/appdata/(?:roaming|locallow)(?:/|$)|^/users/[^/]+/library(?:/|$)|"
    r"^/var/(?:backups|spool|mail)(?:/|$)",
    re.IGNORECASE)


def _entry_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return ""


def _is_human_prompt(e) -> bool:
    origin = e.get("origin") if isinstance(e, dict) else None
    return (isinstance(e, dict) and e.get("type") == "user" and isinstance(origin, dict)
            and origin.get("kind") == "human" and not e.get("isMeta") and not e.get("isSidechain")
            and isinstance(e.get("message"), dict))


def _tail_entries(path: Path):
    """Transcript entries newest-first, read from the end in blocks (no full-file parse)."""
    with path.open("rb") as fh:
        fh.seek(0, 2)
        pos, buf, read = fh.tell(), b"", 0
        while pos > 0 and read < TRANSCRIPT_SCAN_CAP:
            step = min(1 << 20, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
            read += step
            lines = buf.split(b"\n")
            buf = lines[0] if pos > 0 else b""
            for raw in reversed(lines[1:] if pos > 0 else lines):
                try:
                    e = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(e, dict):
                    yield e


def _human_text(e) -> str | None:
    """Text of an owner message: a typed turn, or a message the owner sent while I was working
    (host-written `queued_command` attachment, origin.kind=human). Task notifications and
    cross-session messages carry another origin or isMeta and never count (owner 2026-10-11)."""
    if _is_human_prompt(e):
        return _entry_text(e["message"].get("content"))
    a = e.get("attachment") if e.get("type") == "attachment" and not e.get("isSidechain") else None
    origin = a.get("origin") if isinstance(a, dict) else None
    if (isinstance(a, dict) and a.get("type") == "queued_command" and a.get("commandMode") == "prompt"
            and isinstance(origin, dict) and origin.get("kind") == "human" and not a.get("isMeta")
            and isinstance(a.get("prompt"), str)):
        return a["prompt"]
    return None


HOST_MARKUP = re.compile(r"<system-reminder>.*?</system-reminder>|<!--.*?-->", re.DOTALL)


def _split_reply(text: str) -> tuple[str, str]:
    """(the owner's own words, the lines they quoted). A `> ` line quotes my earlier text, so a
    '?' or 'не' inside it is mine, not the owner's hesitation; host markup is not the owner's."""
    own, quoted = [], []
    for line in HOST_MARKUP.sub("", text).splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            quoted.append(stripped[1:].lstrip())
        else:
            own.append(line)
    return "\n".join(own).strip(), "\n".join(quoted).strip()


def owner_request(transcript_path: str) -> tuple[str, str] | None:
    """(latest owner message, my text it answers) from the host-written transcript."""
    if not transcript_path:
        return None
    p = Path(transcript_path)
    if not p.is_file():
        return None
    prompt, quoted, answer = None, "", []
    for e in _tail_entries(p):
        if prompt is None:
            text = _human_text(e)
            if text is not None:
                prompt, quoted = _split_reply(text)
                if not prompt:
                    return None
            continue
        if _human_text(e) is not None:
            break
        msg = e.get("message")
        if e.get("type") == "assistant" and not e.get("isSidechain") and isinstance(msg, dict):
            text = _entry_text(msg.get("content"))
            if text.strip():
                answer.append(text)
                break  # only my last message is what the owner answered
    if prompt is None:
        return None
    return prompt, "\n".join(x for x in (quoted, *answer) if x)


def _is_recursive(verb: str, seg: str) -> bool:
    """rm -r/-R/-rf/--recursive, Remove-Item -Recurse (any prefix >= -r), del/erase /s, rmdir/rd."""
    if verb in {"rmdir", "rd"}:
        return True
    try:
        toks = shlex.split(seg, posix=False)[1:]
    except ValueError:
        return True
    for t in toks:
        t = t.strip("'\"")
        if verb == "rm" and (t == "--recursive" or (re.fullmatch(r"-[a-zA-Z]{1,4}", t) and "r" in t.lower())):
            return True
        if verb in {"remove-item", "ri", "del", "erase"} and (
                re.fullmatch(r"-r(?:e(?:c(?:u(?:r(?:se?)?)?)?)?)?", t, re.IGNORECASE) or t.lower() == "/s"):
            return True
    return False


def plain_delete_targets(cmd: str, allow_move: bool = False,
                         allow_delete: bool = True) -> list[tuple[str, bool]] | None:
    """(target, recursive) for every delete in cmd (ssh unwrapped), or None if any destructive
    part is something other than a plain file delete (DROP, docker, git, kill...). With
    allow_move, `mv SRC DST` counts as deleting DST (the replaced file); a request that only
    asks to replace (allow_delete=False) covers no rm at all."""
    return _delete_targets_in(cmd, allow_move, allow_delete) or None


def _delete_targets_in(cmd: str, allow_move: bool, allow_delete: bool) -> list[tuple[str, bool]] | None:
    """[] = nothing destructive here (e.g. a read-only `ssh host ls`), None = not a plain delete.
    Keeping the two apart lets a delete sit next to a harmless remote command (2026-10-11)."""
    targets: list[tuple[str, bool]] = []
    if re.search(r"\.claude[\\/]projects[\\/]", cmd, re.IGNORECASE):
        return None  # never let a command that touches the approval source approve itself
    if any(delete_targets(x) is not None or any_match(x, DESTRUCTIVE_INTENT) for x in substitutions(cmd)):
        return None
    for seg in (s.strip() for s in split_segments(executable_text(cmd))):
        if not seg:
            continue
        remote = remote_command(seg)
        if remote == UNPARSED:
            return None
        if remote:
            sub = _delete_targets_in(remote, allow_move, allow_delete)
            if sub is None:
                return None
            targets += sub
            continue
        seg_targets = delete_targets(seg)
        if seg_targets is None and allow_move:
            moved = move_overwrite_targets(seg)
            if moved is not None:
                targets += [(t, False) for t in moved]
                continue
        if seg_targets is not None and not allow_delete:
            return None
        if seg_targets is None and hidden_deletes(seg):
            return None
        seg_hit = any_match(seg, DESTRUCTIVE_INTENT)
        if seg_targets is None and not seg_hit:
            continue
        if not seg_targets:
            return None
        verb = seg.split()[0].lower().rsplit("/", 1)[-1].removesuffix(".exe")
        recursive = _is_recursive(verb, seg)
        targets += [(t, recursive) for t in seg_targets]
    return targets


def restart_only(cmd: str) -> bool:
    """True when every destructive part of cmd (ssh unwrapped) is a plain restart verb and there
    is at least one. Anything else destructive next to it (rm, DROP, kill, poweroff) -> False."""
    if re.search(r"\.claude[\\/]projects[\\/]", cmd, re.IGNORECASE):
        return False
    if any(delete_targets(x) is not None or any_match(x, DESTRUCTIVE_INTENT) for x in substitutions(cmd)):
        return False
    found = False
    for seg in (s.strip() for s in split_segments(executable_text(cmd))):
        if not seg:
            continue
        remote = remote_command(seg)
        if remote == UNPARSED:
            return False
        if remote:
            if not restart_only(remote):
                if any_match(remote, DESTRUCTIVE_INTENT) or delete_targets(remote) is not None:
                    return False
                continue
            found = True
            continue
        if delete_targets(seg) is not None or hidden_deletes(seg):
            return False
        if not any_match(seg, DESTRUCTIVE_INTENT):
            continue
        if not RESTART_SEGMENT.fullmatch(seg):
            return False
        found = True
    return found


def _restart_approval(cmd: str, prompt: str, answer: str, event: dict) -> tuple[bool, str]:
    """A restart passes on the owner's own request, or on a bare yes to my proposal to restart."""
    if CONFIRM_ONLY.fullmatch(prompt):
        if not RESTART_MENTION.search(answer):
            return False, "a bare 'yes' to an answer that proposed no restart"
    elif NOT_A_GO.search(prompt) or NOT_A_RESTART_GO.search(prompt):
        return False, "the request negates, hesitates or asks a question"
    elif not RESTART_INTENT.search(prompt):
        return False, "the latest request does not ask to restart"
    try:
        APPROVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with APPROVAL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                                 "session": event.get("session_id"), "action": "restart",
                                 "request": prompt[:300], "command": cmd[:500]},
                                ensure_ascii=False) + "\n")
    except OSError:
        return False, "cannot write the approval audit record"
    return True, "restart"


def _claude_limit(path: str) -> str | None:
    """Owner decision 2026-10-07: a project's .claude (handoffs, roster, worktrees) may be
    cleaned on request. The home one (rules, hooks, transcripts, settings) stays protected,
    and so does a project's whole .claude folder -- only things inside it."""
    low = [p.lower() for p in re.sub(r"^[A-Za-z]:", "", path).split("/") if p]
    for i, p in enumerate(low):
        if p != ".claude":
            continue
        if (i == 2 and low[0] in {"users", "home"}) or (i == 1 and low[0] == "root"):
            return "protected location (home .claude)"
        if i == len(low) - 1:
            return "protected location (whole .claude folder)"
    return None


def target_hard_limit(target: str) -> str | None:
    """Why a target may never be deleted on request, or None."""
    t = _norm(target)
    if not t or re.search(r"[$%`*?\[\]{}@()]", t):
        return "glob/variable/expression"
    if t.startswith("//"):
        return "UNC/network path"
    if "/../" in f"/{t}/" or "/./" in f"/{t}/":
        return "traversal"
    if re.match(r"^[A-Za-z]{2,}:", t):
        return "provider"
    if not (t.startswith("/") or re.match(r"^[A-Za-z]:/", t)):
        return "relative path (cwd unknown to the owner)"
    if any(c not in {".", ".."} and (c.endswith((".", " ")) or re.search(r"~\d", c)) for c in t.split("/")):
        return "ambiguous Windows name (trailing dot/space or 8.3 short name)"
    wsl = re.match(r"^/mnt/([a-zA-Z])(/.*)?$", t)
    # review 2026-10-11 F3: on Windows a drive-less "/<home>/AppData/Roaming" is "<current drive>:/<home>/...";
    # judge a drive-less path as if it were on a drive too.
    on_drive = f"c:{t}" if sys.platform == "win32" and t.startswith("/") and not t.startswith("//") else None
    if (PROTECTED.search(t) or (wsl and PROTECTED.search(f"{wsl.group(1)}:{wsl.group(2) or '/'}"))
            or (on_drive and PROTECTED.search(on_drive))):
        return "protected location"
    claude = _claude_limit(t) or (wsl and _claude_limit(f"{wsl.group(1)}:{wsl.group(2) or '/'}"))
    if claude:
        return claude
    parts = [p for p in re.sub(r"^[A-Za-z]:", "", t).split("/") if p]
    low = [p.lower() for p in parts]
    if len(parts) < 3:
        return "root-level path"
    if low[0] in {"home", "users"} and len(parts) < 4:
        return "home folder or its direct child"
    return None


def _named(text: str, needle: str) -> bool:
    """needle appears in text as a whole token (not as part of a longer name or path)."""
    return re.search(r"(?<![\w.\-/~:])" + re.escape(needle) + r"(?![\w.\-/])", text) is not None


def approved_by_owner(cmd: str, event: dict) -> tuple[bool, str]:
    req = owner_request(event.get("transcript_path") or "")
    if not req:
        return False, "no human prompt in the transcript"
    prompt, answer = req
    if restart_only(cmd):
        return _restart_approval(cmd, prompt, answer, event)
    listed, why = list_delete_request(cmd, prompt, answer)
    if listed is None:
        return False, why
    if listed:
        # The audit record doubles as the script's one-shot approval: delete_from_list.py refuses
        # unless it finds a fresh record for exactly this list and digest (review round 10 - the
        # script no longer depends on the hook recognising how it was invoked).
        argv = shlex.split(cmd.strip().lstrip("&").strip().replace("\\", "/"), posix=True)
        extra = {"list": _list_key(argv[2]), "sha": argv[4].lower()}
        return _approve(listed, "\n".join(t for t, _ in listed), False, prompt, cmd, event, extra=extra)
    bare, with_paths = CONFIRM_ONLY.fullmatch(prompt), CONFIRM_PATHS.fullmatch(prompt)
    if bare or with_paths:
        allow_delete, allow_move = bool(DELETE_MENTION.search(answer)), bool(REPLACE_MENTION.search(answer))
        if not (allow_delete or allow_move):
            return False, "a bare 'yes' to an answer that proposed no deletion"
        named_in, from_phrase = (answer if bare else prompt), False
    elif NOT_A_GO.search(prompt):
        return False, "the request negates, hesitates or asks a question"
    elif DELETE_INTENT.search(prompt) or REPLACE_INTENT.search(prompt):
        named_in, from_phrase = prompt, bool(FROM_PHRASE.search(prompt))
        allow_delete, allow_move = bool(DELETE_INTENT.search(prompt)), bool(REPLACE_INTENT.search(prompt))
    else:
        return False, "the latest request does not ask to delete"
    targets = plain_delete_targets(cmd, allow_move, allow_delete)
    if not targets:
        return False, "not a plain file delete"
    # A general go-ahead is a bare yes to my proposal, or a request that names no file itself
    # ("удали временные"). When the owner names a file, unnamed others are not covered.
    general = named_in is answer or not NAMES_FILE.search(prompt)
    return _approve(targets, named_in, from_phrase, prompt, cmd, event, general=general)


def _approve(targets: list[tuple[str, bool]], named_in: str, from_phrase: bool,
             prompt: str, cmd: str, event: dict, general: bool = False,
             extra: dict | None = None) -> tuple[bool, str]:
    """Every target passes the hard limits and is named in named_in (or, with a general go-ahead,
    is regenerable); then one audit record."""
    text = named_in.replace("\\", "/")
    for t, recursive in targets:
        why = target_hard_limit(t)
        if why:
            return False, f"{t}: hard limit ({why})"
        full = _norm(t).rstrip("/")
        hay = text
        if re.match(r"^[A-Za-z]:/", full):  # Windows: case-insensitive filesystem
            full, hay = full.lower(), text.lower()
        base = full.rsplit("/", 1)[-1]
        # review 2026-10-11 R7: the irreplaceable counts as named only in the OWNER's own words,
        # never because my answer mentioned it (an answer can mention a path to say "won't touch").
        why, inner = irreplaceable_info(t, recursive)
        if why:
            own = prompt.replace("\\", "/")
            win = bool(re.match(r"^[a-z]:/", full))
            own = own.lower() if win else own
            if inner is None:
                return False, (f"{t}: {why} - cannot be confirmed as a whole; delete it in parts "
                               f"or through a deletion list")
            if inner:
                # review R8: naming a folder does not name the databases inside it; each one must be
                # named by the owner herself, then the folder goes through the usual checks below.
                missing = [n for n in inner if not _named(own, n.lower() if win else n)]
                if missing:
                    return False, (f"{t}: holds irreplaceable files the owner did not name herself: "
                                   f"{', '.join(missing)}")
            else:
                if _named(own, full) or (_named(own, base) and not recursive and "." in base.strip(".")):
                    continue
                return False, f"{t}: irreplaceable ({why}) - the owner must name it in her own message"
        if _named(hay, full):
            continue
        if general and not from_phrase:
            continue  # regenerable: the general go-ahead is enough
        if recursive or from_phrase or "." not in base.strip("."):
            return False, f"{t}: name the full path (recursive delete, directory or 'from' phrasing)"
        if not _named(hay, base):
            return False, f"{t}: '{base}' is not named in the request"
    try:
        APPROVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with APPROVAL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                                 "session": event.get("session_id"), "targets": [t for t, _ in targets],
                                 "request": prompt[:300], "command": cmd[:500], **(extra or {})},
                                ensure_ascii=False) + "\n")
    except OSError:
        return False, "cannot write the approval audit record"
    return True, ", ".join(t for t, _ in targets)


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

    ok, why = approved_by_owner(cmd, event)
    if ok:
        log("INFO", "require_human_confirmation", "owner-requested-delete", hit or "", why)
        allow()

    log("BLOCK", "require_human_confirmation", "no-owner-request", hit, f"{why} | {cmd[:250]}")
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
        f"Почему не пропущено по просьбе владельца: {why}.\n\n"
        "Удаление файла разрешается, только если ПОСЛЕДНЕЕ сообщение владельца (из журнала "
        "сессии, не из команды) просит удалить и называет каждый файл по имени, либо отвечает "
        "«да/удаляй» на мой ответ, где эти файлы перечислены. Попроси владельца назвать файлы. "
        "Длинный список: запиши пути в ~/.claude/state/deletion-lists/<имя>.txt, покажи владельцу "
        "строку из `python ~/.claude/claude-code-config/scripts/delete_from_list.py <список> --show` "
        "(deletion-list: <путь> sha256:<хэш>) и после его «да» выполни "
        "`python ~/.claude/claude-code-config/scripts/delete_from_list.py <список> --sha <хэш>`. "
        "Маркеры в команде, env и файлы агента не являются одобрением.\n\n"
        "Перезапуск (reboot, systemctl reboot, shutdown -r, virsh reboot <vm>, Restart-Computer) "
        "проходит, если последнее сообщение владельца просит перезапустить или отвечает «да» на мой "
        "ответ с предложением перезапуска, и в команде нет ничего разрушительного, кроме перезапуска.\n\n"
        "Без просьбы проходят только routine build/cache/temp targets; DROP/docker/git/kill "
        "и корни дисков/домашние папки/маски не проходят никогда."
    )


def self_test() -> int:
    """Negative controls: every must-block case blocks, every temp/build delete passes."""
    import tempfile
    HOME_FIX = "C:/" + "Users" + "/someone"  # assembled: the public-repo scanner flags literal home paths
    WSL_HOME = "/mnt/c/" + "Users" + "/someone"
    global WORKSHOP_VM_SSH_TARGET, WORKSHOP_VM_APPROVED_DOCKER_CONTAINERS
    WORKSHOP_VM_SSH_TARGET = "ws@bench-vm"
    WORKSHOP_VM_APPROVED_DOCKER_CONTAINERS = frozenset({"bench-a", "bench-a2", "bench-b"})
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
        "tailscale ssh ws@bench-vm docker rm bench-a bench-a2 bench-b",
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
        "docker rm -f bench-a",
        "docker rm production-db",
        "docker rm bench-a",
        "tailscale ssh ws@production-vm docker rm bench-a",
        "tailscale ssh ws@bench-vm docker rm production-bench",
        "tailscale ssh ws@bench-vm docker rm --force bench-a",
    ]
    # ssh-wrapped deletes are judged by their remote command (review 2026-10-06)
    allow_cases += ["ssh gpu-host 'rm -rf /tmp/x'", "timeout 60 ssh -o ConnectTimeout=5 host \"ls -la /srv\"",
                    "git config core.sshCommand ssh", "rsync -e ssh /srv/a host:/srv/b", "which ssh",
                    "echo 'a; rm /srv/data/x'", "echo \"$(date)\"", "echo don't use ssh here",
                    "git rm --cached notes.txt", "ssh host systemctl status nginx"]
    block_cases += ["ssh gpu-host 'rm /srv/comfy/models/flux1-dev.sft'",
                    "timeout 60 ssh -o ConnectTimeout=5 host 'ls; rm -f /srv/data/db.sqlite'",
                    "tailscale ssh ws@bench-vm rm -rf /opt/app",
                    "ssh -B eth0 myhost rm /srv/data/db.sqlite",          # review: missing -B
                    "ssh -Tp 2222 host rm /srv/data/db.sqlite",           # review: combined flags
                    "echo /srv/a/b/x | xargs rm",                         # review: stdin targets
                    "bash -c 'rm /srv/data/db.sqlite'",                   # review: inner shell
                    "ssh h bash -c 'rm /srv/data/db.sqlite'",
                    "powershell -Command \"Remove-Item C:/data/x.txt\"",
                    "pwsh -EncodedCommand SQBFAFgA",
                    'echo \\"a; rm /srv/data/db.sqlite; echo b\\"',   # round 2: escaped quotes
                    "echo `rm /srv/data/db.sqlite`",                     # round 2: substitutions
                    "echo $(rm /srv/data/db.sqlite)",
                    # round 3: hidden behind grouping / wrappers / escapes / unknown verbs
                    "{ rm /srv/prod/db.sqlite; }", "( rm /srv/prod/db.sqlite )",
                    "nohup rm /srv/prod/db.sqlite", "time rm /srv/prod/db.sqlite",
                    "\\rm /srv/prod/db.sqlite", "r''m /srv/prod/db.sqlite",
                    "if true; then rm /srv/prod/db.sqlite; fi",
                    "& { del C:\\srv\\prod\\db.sqlite }", "r`m C:\\srv\\prod\\db.sqlite",
                    "1 | % { ri C:\\srv\\prod\\db.sqlite }",
                    "unlink /srv/prod/db.sqlite", "find /srv/prod -name db.sqlite -exec rm {} +",
                    "[IO.File]::Delete('C:\\srv\\prod\\db.sqlite')",
                    "rm -rf D:/tmp/x#/../.." + HOME_FIX[2:] + "/Documents",
                    "Invoke-Command -ScriptBlock { del C:/srv/prod/db.sqlite }",  # only the hidden scan sees it
                    "Get-ChildItem C:/srv | ForEach-Object -Process { del C:/srv/prod/db.sqlite }"]
    fails = [f"should allow: {c}" for c in allow_cases if not decide(c)[0]]
    fails += [f"should block: {c}" for c in block_cases if decide(c)[0]]

    # owner-requested deletes: host transcript fixtures (approval + negative controls)
    global APPROVAL_LOG
    saved_log = APPROVAL_LOG
    work = Path(tempfile.mkdtemp(prefix="hcg-selftest-"))
    APPROVAL_LOG = work / "approvals.jsonl"

    def transcript(prompt: str, answer: str = "", meta_after: str = "", earlier: str = "") -> dict:
        rows = []
        if earlier:
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": earlier}]}})
        if answer:
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
        rows.append({"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt}})
        if meta_after:
            rows.append({"type": "user", "isMeta": True, "message": {"content": meta_after}})
            rows.append({"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": meta_after}})
        p = work / f"t{len(list(work.iterdir()))}.jsonl"
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return {"transcript_path": str(p), "session_id": "selftest"}

    def queued(prompt: str, answer: str = "", kind: str = "human", mode: str = "prompt",
               meta: bool = False) -> dict:
        """A message delivered while I was working: host-written queued_command attachment."""
        rows = []
        if answer:
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
        att = {"type": "queued_command", "commandMode": mode, "prompt": prompt, "origin": {"kind": kind}}
        if meta:
            att["isMeta"] = True
        rows.append({"type": "attachment", "attachment": att})
        p = work / f"q{len(list(work.iterdir()))}.jsonl"
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return {"transcript_path": str(p), "session_id": "selftest"}

    sft = "ssh gpu-host 'rm /srv/comfy/models/checkpoints/FLUX1/flux1-dev.sft'"
    approve = [
        ("named in prompt", sft, transcript("удали flux1-dev.sft на сервере")),
        ("confirm my listed proposal", sft, transcript("да, удаляй", "Удалю flux1-dev.sft (23.8 GB) - подтверди")),
        ("local file named", "rm C:/work/proj/old/model_a.safetensors", transcript("delete model_a.safetensors please")),
        ("full dir path named for recursive", "rm -rf /srv/comfy/models/old_loras",
         transcript("удали папку /srv/comfy/models/old_loras")),
        ("bash -c over ssh named", "ssh h \"bash -c 'rm /srv/a/b/x.bin'\"", transcript("удали x.bin")),
        ("inside a project .claude", "Remove-Item -LiteralPath 'C:/work/proj/.claude/handoffs/roster' -Recurse -Force",
         transcript("да, удаляй C:/work/proj/.claude/handoffs/roster")),
        ("Remove-Item named", 'Remove-Item -LiteralPath "D:\\models\\loras\\bad_lora.safetensors"', transcript("убери bad_lora.safetensors")),
    ]
    refuse = [
        ("no transcript", sft, {}),
        ("negated", sft, transcript("не удаляй flux1-dev.sft")),
        ("not a delete request", sft, transcript("посмотри flux1-dev.sft")),
        ("confirm without my proposal", sft, transcript("да", "Скачала модели.")),
        ("past tense is a report, not a request", sft,
         transcript("вроде удалила и поправь хук", "Удалить flux1-dev.sft можно командой rm ...")),
        ("meta/notification carry the words, human prompt does not",
         sft, transcript("посмотри статус", meta_after="удали flux1-dev.sft")),
        ("root-level path", "rm -rf /" + "home/someuser", transcript("удали someuser")),
        ("drive-level path", "Remove-Item -Recurse C:\\Users", transcript("удали Users")),
        ("glob", "ssh h 'rm /srv/a/b/*.sft'", transcript("удали *.sft")),
        ("variable", "ssh h 'F=/srv/a/b/x.sft; rm $F'", transcript("удали x.sft")),
        (".git", "rm -rf C:/work/repo/.git/objects", transcript("удали objects")),
        ("non-file destructive", "psql -c 'DROP TABLE users'", transcript("удали таблицу users")),
        ("docker", "docker rm production-db", transcript("удали production-db")),
        ("touches transcript", "rm " + HOME_FIX + "/.claude/projects/p/s.jsonl", transcript("удали s.jsonl")),
        # review 2026-10-06 (REJECT) probes
        ("parent dir by substring", "rm -rf /srv/a/models", transcript("удали models/old.bin")),
        ("short basename inside a word", "rm -rf /srv/app/dev", transcript("удали flux1-dev.sft")),
        ("relative after cd", "ssh h 'cd / && rm -rf srv'", transcript("удали srv_backup.tar")),
        ("relative bare", "rm -rf src", transcript("удали src_old.zip")),
        ("home child", "Remove-Item -Recurse -Force " + HOME_FIX + "/Desktop", transcript("удали ярлык с desktop")),
        ("the guard itself", "rm " + HOME_FIX + "/.claude/claude-code-config/hooks/human-confirmation-guard.py",
         transcript("убери лишнее из human-confirmation-guard.py")),
        ("UNC", "Remove-Item \\\\nas\\share\\data\\data.csv", transcript("удали data.csv")),
        ("edit phrasing", "rm C:/w/proj/src/train.py", transcript("remove the debug print from train.py")),
        ("question", "rm /srv/a/b/flux.sft", transcript("why did you delete flux.sft?")),
        ("then no", "rm /srv/a/b/flux.sft", transcript("удалить flux.sft? нет, оставь")),
        ("answer widens scope", "rm /srv/data/prod/db.sqlite",
         transcript("удали старые логи", "Удалю логи и заодно db.sqlite")),
        ("ok-but-wait", "rm /srv/data/prod/db.sqlite", transcript("ок, посмотри сначала", "Могу удалить db.sqlite")),
        ("xargs", "echo /srv/a/b/xyz.bin | xargs rm", transcript("удали xyz.bin")),
        ("bash -c over ssh unnamed", "ssh h bash -c 'rm /srv/a/b/x.bin'", transcript("удали y.bin")),
        # isolated controls: each protection must refuse on its own
        ("relative file path", "rm data/cache/run1/old.bin", transcript("удали old.bin")),
        ("bare yes covers only my last message", "rm /srv/data/prod/db.sqlite",
         transcript("да", "Удалю /srv/tmp/a/old.bin - подтверди", earlier="Кстати, /srv/data/prod/db.sqlite большой")),
        ("hash inside the path", "rm /srv/a/b/x.bin#/../../../../etc/passwd", transcript("удали /srv/a/b/x.bin")),
        ("trailing-dot alias of .claude", "Remove-Item " + HOME_FIX + "/.claude./settings.json", transcript("удали settings.json")),
        ("8.3 short name", "rm " + HOME_FIX + "/CLAUDE~1/settings.json", transcript("удали settings.json")),
        ("WSL alias of Windows", "rm /mnt/c/Windows/System32/drivers/etc/hosts.bin", transcript("удали hosts.bin")),
        ("AppData Roaming", "rm " + HOME_FIX + "/AppData/Roaming/app/state.db", transcript("удали state.db")),
        ("home .claude stays protected", "rm -rf " + HOME_FIX + "/.claude/handoffs/roster",
         transcript("удали " + HOME_FIX + "/.claude/handoffs/roster")),
        ("home .claude via WSL", "rm -rf " + WSL_HOME + "/.claude/rules/x",
         transcript("удали " + WSL_HOME + "/.claude/rules/x")),
        ("whole project .claude", "rm -rf C:/work/proj/.claude", transcript("удали C:/work/proj/.claude")),
        ("linux root home .claude", "rm -rf /root/.claude/hooks/h", transcript("удали /root/.claude/hooks/h")),
    ]
    # general go-ahead (owner 2026-10-11): regenerable needs no naming, irreplaceable does
    gdir = work / "general"
    (gdir / "proj" / "out" / "run1").mkdir(parents=True)
    (gdir / "proj" / "out" / "run1" / "img.png").write_text("x")
    (gdir / "proj" / "app" / "data").mkdir(parents=True)
    (gdir / "proj" / "app" / "data" / "state.sqlite").write_text("x")
    out_dir, app_dir = (gdir / "proj" / "out").as_posix(), (gdir / "proj" / "app").as_posix()
    approve += [
        ("general request, regenerable file unnamed", sft, transcript("удали большие файлы")),
        ("general yes to my proposal, regenerable", "rm /srv/a/b/model.bin",
         transcript("да", "Удалю временные модели из /srv/a/b - подтверди")),
        ("general yes, inspectable local folder without databases", f"rm -rf {out_dir}",
         transcript("да, удаляй", "Удалю выходы тестов")),
        ("irreplaceable but named explicitly", "rm /srv/data/prod/db.sqlite", transcript("удали db.sqlite")),
        ("general request for a regenerable server folder", "rm -rf /srv/a/models/", transcript("удали models")),
        ("general yes, regenerable remote folder judged by path", "ssh h 'rm -rf /srv/a/b/old'",
         transcript("да", "Удалю старое на сервере")),
    ]
    refuse += [
        ("general yes, database file", "rm /srv/data/prod/main.sqlite", transcript("да", "Удалю мусор на сервере")),
        ("general yes, database backup dump", "rm /srv/data/prod/nightly.dump", transcript("да", "Удалю мусор")),
        ("general yes, backup folder", "rm -rf C:/w/proj/backups/2026-10", transcript("да", "Удалю старое")),
        ("general yes, dataset", "rm -rf D:/data/jewelry-dataset/v2", transcript("да", "Удалю лишнее")),
        ("general yes, local folder that holds a database", f"rm -rf {app_dir}", transcript("да", "Удалю старый проект")),
        ("general request, sql export", "rm C:/w/proj/exports/users.sql", transcript("удали старые выгрузки")),
        ("owner named a file, another one is not covered", "rm C:/w/p/a1.bin C:/w/p/b2.bin", transcript("удали a1.bin")),
        ("owner named a file, its suffix is not covered", "rm /srv/a/b/dev.sft", transcript("удали flux1-dev.sft")),
        ("owner named a file, case differs on POSIX", "rm /srv/a/b/model.bin", transcript("удали Model.bin")),
        ("general yes, remote database folder by path", "ssh h 'rm -rf /srv/pgdata/main'", transcript("да", "Удалю старое")),
    ]
    # owner 2026-10-11: replacing a named file with mv (approve) and its negative controls
    mv_case = "ssh h 'mv -f /srv/a/b/case.json.tmp /srv/a/b/case.json && sha256sum /srv/a/b/case.json'"
    approve += [
        ("replace named in prompt", mv_case, transcript("да, замену case.json разрешаю, продолжай сборку")),
        ("yes + full path to my replace proposal", mv_case,
         transcript("да /srv/a/b/case.json", "Нужно перезаписать /srv/a/b/case.json - ответьте да")),
        ("delete next to a read-only remote command", mv_case + '; ssh h "ls /srv/a/b/"',
         transcript("замени case.json")),
    ]
    refuse += [
        ("replace request covers no rm", "ssh h 'rm /srv/a/b/case.json'", transcript("замени case.json")),
        ("replace covers only the named file", "ssh h 'mv -f /srv/a/b/x.tmp /srv/a/b/other.json'",
         transcript("замени case.json")),
        ("mv with several sources", "mv /srv/a/b/a.json /srv/a/b/case.json /srv/a/b/dir", transcript("замени case.json")),
        ("mv -t form", "mv -t /srv/a/b /srv/a/b/case.json.tmp", transcript("замени case.json")),
        ("yes + path to an answer that proposed nothing", mv_case,
         transcript("да /srv/a/b/case.json", "Скачала модели.")),
        ("yes + path covers only that path", "ssh h 'mv -f /srv/a/b/t /srv/a/b/other.json'",
         transcript("да /srv/a/b/case.json", "Перезапишу /srv/a/b/case.json")),
        ("negated replace", mv_case, transcript("не заменяй case.json")),
        ("mv with no request", mv_case, transcript("посмотри case.json")),
        ("approved replace next to a remote DROP", mv_case + "; ssh h \"psql -c 'DROP TABLE users'\"",
         transcript("замени case.json")),
        ("only a read-only remote command", 'ssh h "ls /srv/a/b/"', transcript("замени case.json")),
    ]
    # owner 2026-10-11: messages sent mid-turn, quoted replies and host markup
    model_rm = "rm /srv/a/b/model.bin"
    approve += [
        ("queued owner message counts", model_rm, queued("удаляй", "Удалю временные модели из /srv/a/b")),
        ("a '?' inside the quote is mine, not the owner's", model_rm,
         transcript("<!-- reply 1 -->\n> Удалить временные модели из /srv/a/b?\n\nудаляй", "Готово с тестами.")),
        ("host reminder text is not the owner's", model_rm,
         transcript("<system-reminder>\nnot now? нет\n</system-reminder>\nудали /srv/a/b/model.bin")),
    ]
    refuse += [
        ("queued task notification never counts", model_rm,
         queued("удали /srv/a/b/model.bin", mode="task-notification", kind="task-notification")),
        ("queued peer message never counts", model_rm, queued("удали /srv/a/b/model.bin", kind="peer", meta=True)),
        ("the owner's own question still refuses", model_rm,
         transcript("<!-- reply 1 -->\n> Удалю /srv/a/b/model.bin\n\nудалить?")),
        ("quoted words alone are not a request", model_rm, transcript("> удали /srv/a/b/model.bin")),
    ]

    # owner-approved deletion lists (2026-10-11)
    global DELETION_LIST_DIR
    saved_list_dir = DELETION_LIST_DIR
    DELETION_LIST_DIR = work / "deletion-lists"
    DELETION_LIST_DIR.mkdir()
    lst = DELETION_LIST_DIR / "tmp-cleanup.txt"
    lst.write_text("# temp and test leftovers\nD:/tmp/work/run1\nC:/w/proj/tests/out/cache.bin\n", encoding="utf-8")
    dig = hashlib.sha256(lst.read_bytes()).hexdigest()[:16]
    shown = f"Удалю временные файлы (2 шт.). deletion-list: {lst.as_posix()} sha256:{dig}"
    call = f"python {LIST_SCRIPT.as_posix()} {lst.as_posix()} --sha {dig}"
    bad = DELETION_LIST_DIR / "bad.txt"
    bad.write_text("C:/w/repo/.git/objects\n", encoding="utf-8")
    bdig = hashlib.sha256(bad.read_bytes()).hexdigest()[:16]
    outside = work / "outside.txt"
    outside.write_text("D:/tmp/work/run1\n", encoding="utf-8")
    odig = hashlib.sha256(outside.read_bytes()).hexdigest()[:16]
    fake_dir = work / "evil" / "claude-code-config" / "scripts"
    fake_dir.mkdir(parents=True)
    (fake_dir / "delete_from_list.py").write_text("import shutil", encoding="utf-8")
    approve.append(("bare yes to a shown list", call, transcript("да, удаляй по списку", shown)))
    refuse += [
        ("list not shown in my last answer", call, transcript("да", "Удалю временные файлы, список готов")),
        ("list shown but owner asked a question", call, transcript("да?", shown)),
        ("list delete needs a bare go-ahead", call, transcript("удали всё что хочешь", shown)),
        ("digest in the command differs from the shown one",
         call.replace(dig, "0" * 16), transcript("да", shown.replace(dig, "0" * 16).replace("sha256:0", "sha256:1"))),
        ("list with a protected path", call.replace(str(lst.as_posix()), bad.as_posix()).replace(dig, bdig),
         transcript("да", f"Удалю. deletion-list: {bad.as_posix()} sha256:{bdig}")),
        ("list outside the list folder", call.replace(str(lst.as_posix()), outside.as_posix()).replace(dig, odig),
         transcript("да", f"Удалю. deletion-list: {outside.as_posix()} sha256:{odig}")),
        ("list call chained with another command", call + " && rm -rf C:/w/other/dir", transcript("да", shown)),
        # review 2026-10-11 probes
        ("injected rm before the script name (F1)",
         f"python x;rm${{IFS}}-rf${{IFS}}C:/w/x;{LIST_SCRIPT.as_posix()} {lst.as_posix()} --sha {dig}", transcript("да", shown)),
        ("look-alike script in another folder (F2)",
         f"python {(fake_dir / 'delete_from_list.py').as_posix()} {lst.as_posix()} --sha {dig}", transcript("да", shown)),
        ("show and sha together", call + " --show", transcript("да", shown)),
        ("interpreter given as a path (R1)", "D:/agent/evil/python.exe " + call.split(" ", 1)[1], transcript("да", shown)),
    ]
    changed = DELETION_LIST_DIR / "changed.txt"
    changed.write_text("D:/tmp/work/run1\n", encoding="utf-8")
    cdig = hashlib.sha256(changed.read_bytes()).hexdigest()[:16]
    changed.write_text("D:/tmp/work/run1\nC:/w/prod/db.sqlite\n", encoding="utf-8")  # edited after it was shown
    refuse.append(("list edited after it was shown", call.replace(str(lst.as_posix()), changed.as_posix()).replace(dig, cdig),
                   transcript("да", f"Удалю. deletion-list: {changed.as_posix()} sha256:{cdig}")))
    if sys.platform == "win32":
        refuse.append(("drive-less AppData Roaming (F3)", "rm " + HOME_FIX[2:] + "/AppData/Roaming/app/x/state.bin",
                       transcript("удали state.bin")))
        dl = DELETION_LIST_DIR / "driveless.txt"
        dl.write_text("/tmp/work/run1\n", encoding="utf-8")
        ddig = hashlib.sha256(dl.read_bytes()).hexdigest()[:16]
        refuse.append(("drive-less list entry (F3)", f"python {LIST_SCRIPT.as_posix()} {dl.as_posix()} --sha {ddig}",
                       transcript("да", f"Удалю. deletion-list: {dl.as_posix()} sha256:{ddig}")))
    dbl = DELETION_LIST_DIR / "with-db.txt"
    dbl.write_text("D:/tmp/work/run1\nD:/srv/app/state/main.sqlite\n", encoding="utf-8")
    dbdig = hashlib.sha256(dbl.read_bytes()).hexdigest()[:16]
    refuse.append(("database inside a list (R2)", f"python {LIST_SCRIPT.as_posix()} {dbl.as_posix()} --sha {dbdig}",
                   transcript("да", f"Удалю. deletion-list: {dbl.as_posix()} sha256:{dbdig}")))
    for ext in ("vault.kdbx", "export.sql.gz", "app.db-journal", "dump.rdb", "orders.ibd", "erp.mdf"):
        refuse.append((f"general yes, database-like {ext} (R4)", f"rm /srv/a/b/{ext}", transcript("да", "Удалю мусор")))
    pg = gdir / "proj" / "pgd"
    (pg / "base").mkdir(parents=True)
    (pg / "PG_VERSION").write_text("16")
    refuse.append(("general yes, postgres data dir by marker (R5)", f"rm -rf {pg.as_posix()}",
                   transcript("да", "Удалю старое")))
    # review round 3: R7 (my answer naming a DB is not the owner naming it), R4/R5 leftovers
    refuse.append(("database named only in my answer (R7)", "rm D:/srv/data/prod/main.sqlite",
                   transcript("да", "Удалю кеш в D:/srv/data/cache, D:/srv/data/prod/main.sqlite трогать не буду")))
    refuse.append(("general yes, sqlite3 WAL (R4)", "rm /srv/a/b/app.sqlite3-wal", transcript("да", "Удалю мусор")))
    refuse.append(("general yes, pgdump (R4)", "rm /srv/a/b/nightly.pgdump", transcript("да", "Удалю мусор")))
    hdr = gdir / "proj" / "cache" / "blob"
    hdr.parent.mkdir(parents=True)
    hdr.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)
    refuse.append(("general yes, SQLite recognised by header (R5)", f"rm {hdr.as_posix()}", transcript("да", "Удалю кеш")))
    approve.append(("owner names the database herself", "rm D:/srv/data/prod/main.sqlite",
                    transcript("удали D:/srv/data/prod/main.sqlite", "Могу удалить main.sqlite")))
    # review round 4: R8 (folder contents judged by header; naming a folder does not name its DBs)
    prof = gdir / "proj" / "browser-profile"
    prof.mkdir(parents=True)
    (prof / "History").write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)
    refuse.append(("general request, folder holds a header-only SQLite (R8)", f"rm -rf {prof.as_posix()}",
                   transcript("удали старый кеш")))
    refuse.append(("owner names a folder but not the database inside (R8)", f"rm -rf {app_dir}",
                   transcript(f"удали {app_dir}")))
    approve.append(("owner names the folder and the database inside", f"rm -rf {app_dir}",
                    transcript(f"удали {app_dir} вместе с state.sqlite")))
    # review round 5: R9 (overflowing either cap fails closed even when the owner names the folder)
    many = gdir / "proj" / "many-dbs"
    many.mkdir(parents=True)
    for i in range(INNER_NAME_CAP + 1):
        (many / f"s{i}.sqlite").write_text("x")
    refuse.append(("folder with more databases than the cap, owner names only the folder (R9)",
                   f"rm -rf {many.as_posix()}", transcript(f"удали {many.as_posix()}")))
    global CONTENT_SCAN_CAP
    saved_cap = CONTENT_SCAN_CAP
    CONTENT_SCAN_CAP = 3
    big = gdir / "proj" / "big-cache"
    big.mkdir(parents=True)
    for i in range(5):
        (big / f"c{i}.bin").write_text("x")
    if approved_by_owner(f"rm -rf {big.as_posix()}", transcript(f"удали {big.as_posix()}"))[0]:
        fails.append("owner request should refuse (scan cap overflow, owner names only the folder) (R9)")
    CONTENT_SCAN_CAP = saved_cap
    # review round 6: R10 (an unreadable subtree fails closed instead of being skipped)
    global WALK
    saved_walk = WALK
    def walk_with_denied_subtree(top, onerror=None, followlinks=False):
        for entry in saved_walk(top, onerror=onerror, followlinks=followlinks):
            yield entry
        if onerror:
            onerror(PermissionError(13, "Access is denied", str(top) + "/locked"))
    WALK = walk_with_denied_subtree
    if approved_by_owner(f"rm -rf {out_dir}", transcript(f"удали {out_dir}"))[0]:
        fails.append("owner request should refuse (unreadable subtree, owner names only the folder) (R10)")
    if approved_by_owner(f"rm -rf {out_dir}", transcript("да, удаляй", "Удалю выходы тестов"))[0]:
        fails.append("owner request should refuse (unreadable subtree, general yes) (R10)")
    WALK = saved_walk
    # review round 7: R11 (a target that cannot be stat'ed is not "absent")
    global LSTAT
    saved_lstat = LSTAT
    denied_file = (gdir / "proj" / "out" / "run1" / "img.png").as_posix()
    def lstat_denied(path):
        if Path(path).as_posix() == denied_file or Path(path).as_posix().startswith(out_dir):
            raise PermissionError(13, "Access is denied", str(path))
        return saved_lstat(path)
    LSTAT = lstat_denied
    if approved_by_owner(f"rm {denied_file}", transcript("да", "Удалю выходы тестов"))[0]:
        fails.append("owner request should refuse (target cannot be stat'ed, general yes) (R11)")
    if approved_by_owner(f"rm -rf {out_dir}", transcript(f"удали {out_dir}"))[0]:
        fails.append("owner request should refuse (folder cannot be stat'ed, owner names it) (R11)")
    LSTAT = saved_lstat
    # owner 2026-10-11: a restart on her request (approve) and its negative controls
    vm_reboot = "ssh gpu-host \"ssh -o BatchMode=yes user@10.0.0.5 'sudo systemctl reboot'\""
    approve += [
        ("restart asked", vm_reboot, transcript("да, перезапускай VM.")),
        ("restart asked in english", "ssh h 'sudo reboot'", transcript("reboot the vm")),
        ("bare yes to my restart proposal", "virsh reboot build-vm",
         transcript("да", "Перезапустить VM build-vm сейчас? Очередь пустая.")),
        ("restart asked, mid-turn message", "ssh h 'shutdown -r now'", queued("перезагрузи сервер")),
    ]
    refuse += [
        ("restart not asked", vm_reboot, transcript("проверь сервер")),
        ("restart negated", vm_reboot, transcript("не перезапускай VM")),
        ("restart asked as a question", vm_reboot, transcript("перезапустить VM?")),
        ("bare yes to an answer without a restart", vm_reboot, transcript("да", "Проверила API.")),
        ("restart plus a delete", "ssh h 'rm -rf /srv/a/b/c; sudo reboot'", transcript("перезапусти сервер")),
        ("poweroff is not a restart", "ssh h 'sudo poweroff'", transcript("перезапусти сервер")),
        ("shutdown without -r", "ssh h 'sudo shutdown now'", transcript("перезапусти сервер")),
        ("delete request does not cover restart", vm_reboot, transcript("удали /srv/a/b/x.bin")),
        ("restart hidden in a substitution", "echo $(reboot)", transcript("перезапусти сервер")),
    ]

    for name, cmd, ev in approve:
        if not approved_by_owner(cmd, ev)[0]:
            fails.append(f"owner request should allow ({name}): {approved_by_owner(cmd, ev)[1]}")
    for name, cmd, ev in refuse:
        if approved_by_owner(cmd, ev)[0]:
            fails.append(f"owner request should refuse ({name})")
    if not APPROVAL_LOG.exists() or len(APPROVAL_LOG.read_text(encoding="utf-8").splitlines()) != len(approve):
        fails.append("every owner-approved delete must leave exactly one audit record")
    APPROVAL_LOG = saved_log
    DELETION_LIST_DIR = saved_list_dir
    if decide(call)[0]:
        fails.append("a delete_from_list.py call must never pass decide() without the owner check")
    show = call.rsplit(" --sha ", 1)[0] + " --show"
    if not decide(show)[0]:
        fails.append("delete_from_list.py --show only reads the list and must pass")
    if decide(show + " ; rm -rf C:/w/other/dir")[0]:
        fails.append("--show followed by another delete must not pass")
    for benign in ("git add -- scripts/delete_from_list.py", "python -m pytest hooks/tests/test_delete_from_list.py"):
        if not decide(benign)[0]:
            fails.append(f"mentioning the script is not a delete: {benign}")
    # review round 9: a list run split over lines, runpy argv tricks and inline-Python deletes
    sneaky = [
        f"python {LIST_SCRIPT.as_posix()} `\n{lst.as_posix()} --sha {dig}",
        f"{LIST_SCRIPT.as_posix()}\n{lst.as_posix()} --sha {dig}",
        "python -c \"import sys,runpy; sys.argv=['x','--sha','" + dig + "','" + lst.as_posix()
        + "']; runpy.run_path('" + LIST_SCRIPT.as_posix() + "')\"",
        "python -c \"import shutil; shutil.rmtree('C:/w/proj/data')\"",
        "python -c \"import os; os.remove('C:/w/proj/db.sqlite')\"",
        "python -c \"from pathlib import Path; Path('C:/w/proj/x.bin').unlink()\"",
    ]
    sneaky += [
        # review round 10: glob in the script name, git shell alias, shell delete from inline Python,
        # and any touch of the approval log the script trusts
        f"python {LIST_SCRIPT.parent.as_posix()}/delete_from_[l]ist.py {lst.as_posix()} --sha {dig}",
        f"git -c alias.zz='!python {LIST_SCRIPT.as_posix()} {lst.as_posix()} --sha {dig}' zz",
        "python -c \"import subprocess; subprocess.run(['rm','-rf','C:/w/proj/data'])\"",
        "python -c \"import os; os.system('del C:/w/proj/db.sqlite')\"",
        "Add-Content " + HOME_FIX + "/.claude/logs/deletion-approvals.jsonl '{}'",
    ]
    sneaky += [
        # review round 11: names split by shell quoting or built from a variable; `&` after git
        "printf x >> " + HOME_FIX + "/.claude/logs/deletion-app''rovals.jsonl",
        f"python {LIST_SCRIPT.parent.as_posix()}/delete_from_''list.py {lst.as_posix()} --sha {dig}",
        f"python {LIST_SCRIPT.parent.as_posix()}/${{N}}list.py {lst.as_posix()} --sha {dig}",
        f"git status & python {LIST_SCRIPT.as_posix()} {lst.as_posix()} --sha {dig}",
    ]
    for s in sneaky:
        if decide(s)[0]:
            fails.append(f"must be flagged as a delete: {s[:80]}")
    if decide(f"python {LIST_SCRIPT.as_posix()} {lst.as_posix()} --sha {dig}")[0]:
        fails.append("a list run must never pass decide() without the owner check")
    print(f"SCANNED owner-requests: approve={len(approve)} refuse={len(refuse)}")
    for f in fails:
        print("SELF-TEST FAIL:", f)
    print(f"SCANNED: allow={len(allow_cases)} block={len(block_cases)}")
    print("SELF-TEST", "PASS" if not fails else "FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # fail closed: a crashed guard must not let a delete run
        block(f"human-confirmation-guard internal error, failing closed: {exc!r}")
