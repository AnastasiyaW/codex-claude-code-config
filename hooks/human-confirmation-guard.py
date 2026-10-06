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

import json
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
# Anything that makes the request not a plain go-ahead: negation, "keep", "no", a question.
NOT_A_GO = re.compile(
    r"\bне\s+(?:надо\s+|нужно\s+|стоит\s+|смей\s+)?(?:удал|снос|снес|стир|сотр|трог|чист|убир)|"
    r"\bнельзя\b|\bнет\b|\bоставь|\bпогоди|\bподожди|\bdon'?t\b|\bdo\s+not\b|\bnever\b|\bkeep\b|\bno\b|\?",
    re.IGNORECASE)
# "убери X из файла" / "remove the print from train.py" edits a file; only a full path counts then.
FROM_PHRASE = re.compile(r"\s(?:из|изо|from|out\s+of)\s", re.IGNORECASE)
# My answer only has to be ABOUT deleting (a proposal "Удалю X - подтверди"); the request must ask.
DELETE_MENTION = re.compile(r"удал|снес|сотр|стер|почист|очист|delete|remov|\brm\b|wipe|erase", re.IGNORECASE)
# A bare go-ahead and nothing else: "да", "да, удаляй", "ок!", "yes".
CONFIRM_ONLY = re.compile(
    r"\s*(?:да|ага|ок|окей|ok|okay|yes|подтверждаю|удаляй|давай|можно)"
    r"(?:[\s,]+(?:да|удаляй|давай|можно|ок|ok|yes|подтверждаю))*\s*[.!]*\s*", re.IGNORECASE)
APPROVAL_LOG = Path.home() / ".claude" / "logs" / "deletion-approvals.jsonl"
TRANSCRIPT_SCAN_CAP = 64 * 1024 * 1024
PROTECTED = re.compile(
    r"(?:^|/)\.(?:claude|codex|ssh|secrets|gnupg|git|agents|config/gh)(?:/|$)|"
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


def owner_request(transcript_path: str) -> tuple[str, str] | None:
    """(latest human prompt, my answer right before it) from the host-written transcript."""
    if not transcript_path:
        return None
    p = Path(transcript_path)
    if not p.is_file():
        return None
    prompt, answer = None, []
    for e in _tail_entries(p):
        if prompt is None:
            if _is_human_prompt(e):
                prompt = _entry_text(e["message"].get("content"))
                if not prompt.strip():
                    return None
            continue
        if _is_human_prompt(e):
            break
        msg = e.get("message")
        if e.get("type") == "assistant" and not e.get("isSidechain") and isinstance(msg, dict):
            text = _entry_text(msg.get("content"))
            if text.strip():
                answer.append(text)
                break  # only my last message is what the owner answered
    return (prompt, "\n".join(answer)) if prompt is not None else None


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


def plain_delete_targets(cmd: str) -> list[tuple[str, bool]] | None:
    """(target, recursive) for every delete in cmd (ssh unwrapped), or None if any destructive
    part is something other than a plain file delete (DROP, docker, git, kill, mv...)."""
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
            sub = plain_delete_targets(remote)
            if sub is None:
                return None
            targets += sub
            continue
        seg_targets = delete_targets(seg)
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
    return targets or None


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
    if PROTECTED.search(t) or (wsl and PROTECTED.search(f"{wsl.group(1)}:{wsl.group(2) or '/'}")):
        return "protected location"
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
    if CONFIRM_ONLY.fullmatch(prompt):
        if not DELETE_MENTION.search(answer):
            return False, "a bare 'yes' to an answer that proposed no deletion"
        named_in, from_phrase = answer, False
    elif NOT_A_GO.search(prompt):
        return False, "the request negates, hesitates or asks a question"
    elif DELETE_INTENT.search(prompt):
        named_in, from_phrase = prompt, bool(FROM_PHRASE.search(prompt))
    else:
        return False, "the latest request does not ask to delete"
    targets = plain_delete_targets(cmd)
    if not targets:
        return False, "not a plain file delete"
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
        if _named(hay, full):
            continue
        if recursive or from_phrase or "." not in base.strip("."):
            return False, f"{t}: name the full path (recursive delete, directory or 'from' phrasing)"
        if not _named(hay, base):
            return False, f"{t}: '{base}' is not named in the request"
    try:
        APPROVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with APPROVAL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                                 "session": event.get("session_id"), "targets": [t for t, _ in targets],
                                 "request": prompt[:300], "command": cmd[:500]}, ensure_ascii=False) + "\n")
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
        "Маркеры в команде, env и файлы агента не являются одобрением.\n\n"
        "Без просьбы проходят только routine build/cache/temp targets; DROP/docker/git/kill "
        "и корни дисков/домашние папки/маски не проходят никогда."
    )


def self_test() -> int:
    """Negative controls: every must-block case blocks, every temp/build delete passes."""
    import tempfile
    HOME_FIX = "C:/" + "Users" + "/someone"  # assembled: the public-repo scanner flags literal home paths
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
    # ssh-wrapped deletes are judged by their remote command (review 2026-10-06)
    allow_cases += ["ssh gpu-host 'rm -rf /tmp/x'", "timeout 60 ssh -o ConnectTimeout=5 host \"ls -la /srv\"",
                    "git config core.sshCommand ssh", "rsync -e ssh /srv/a host:/srv/b", "which ssh",
                    "echo 'a; rm /srv/data/x'", "echo \"$(date)\"", "echo don't use ssh here",
                    "git rm --cached notes.txt", "ssh host systemctl status nginx"]
    block_cases += ["ssh gpu-host 'rm /srv/comfy/models/flux1-dev.sft'",
                    "timeout 60 ssh -o ConnectTimeout=5 host 'ls; rm -f /srv/data/db.sqlite'",
                    "tailscale ssh ws@workshop-vm rm -rf /opt/app",
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

    sft = "ssh gpu-host 'rm /srv/comfy/models/checkpoints/FLUX1/flux1-dev.sft'"
    approve = [
        ("named in prompt", sft, transcript("удали flux1-dev.sft на сервере")),
        ("confirm my listed proposal", sft, transcript("да, удаляй", "Удалю flux1-dev.sft (23.8 GB) - подтверди")),
        ("local file named", "rm C:/work/proj/old/model_a.safetensors", transcript("delete model_a.safetensors please")),
        ("full dir path named for recursive", "rm -rf /srv/comfy/models/old_loras",
         transcript("удали папку /srv/comfy/models/old_loras")),
        ("bash -c over ssh named", "ssh h \"bash -c 'rm /srv/a/b/x.bin'\"", transcript("удали x.bin")),
        ("Remove-Item named", 'Remove-Item -LiteralPath "D:\\models\\loras\\bad_lora.safetensors"', transcript("убери bad_lora.safetensors")),
    ]
    refuse = [
        ("no transcript", sft, {}),
        ("negated", sft, transcript("не удаляй flux1-dev.sft")),
        ("not a delete request", sft, transcript("посмотри flux1-dev.sft")),
        ("target not named", sft, transcript("удали большие файлы")),
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
        ("one of two unnamed", "rm C:/w/p/a1.bin C:/w/p/b2.bin", transcript("удали a1.bin")),
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
        ("dir without full path", "rm -rf /srv/a/models/", transcript("удали models")),
        ("xargs", "echo /srv/a/b/xyz.bin | xargs rm", transcript("удали xyz.bin")),
        ("bash -c over ssh unnamed", "ssh h bash -c 'rm /srv/a/b/x.bin'", transcript("удали y.bin")),
        # isolated controls: each protection must refuse on its own
        ("basename is only a suffix of the named file", "rm /srv/a/b/dev.sft", transcript("удали flux1-dev.sft")),
        ("relative file path", "rm data/cache/run1/old.bin", transcript("удали old.bin")),
        ("bare yes covers only my last message", "rm /srv/data/prod/db.sqlite",
         transcript("да", "Удалю /srv/tmp/a/old.bin - подтверди", earlier="Кстати, /srv/data/prod/db.sqlite большой")),
        ("POSIX name case differs", "rm /srv/a/b/model.bin", transcript("удали Model.bin")),
        ("hash inside the path", "rm /srv/a/b/x.bin#/../../../../etc/passwd", transcript("удали /srv/a/b/x.bin")),
        ("trailing-dot alias of .claude", "Remove-Item " + HOME_FIX + "/.claude./settings.json", transcript("удали settings.json")),
        ("8.3 short name", "rm " + HOME_FIX + "/CLAUDE~1/settings.json", transcript("удали settings.json")),
        ("WSL alias of Windows", "rm /mnt/c/Windows/System32/drivers/etc/hosts.bin", transcript("удали hosts.bin")),
        ("AppData Roaming", "rm " + HOME_FIX + "/AppData/Roaming/app/state.db", transcript("удали state.db")),
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
