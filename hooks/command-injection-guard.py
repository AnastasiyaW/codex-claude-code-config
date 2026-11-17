#!/usr/bin/env python3
"""PreToolUse: detect suspicious shell substitution in Bash commands.

Targets the class of bugs where text meant as data becomes command:
  gh issue create --body "$(dropdb prod)"
  echo "result: $(rm -rf /tmp)" > log.txt

Here the outer command is safe (gh, echo), but $(...) executes before
arg gets to the outer command. This class is distinct from block_destructive
which catches naked 'dropdb'; here we catch 'dropdb' smuggled inside a string.

Strategy:
  - Trivial substitutions are allowed: $(pwd), $(date), $(whoami), $(hostname),
    $(basename ...), $(dirname ...), $(echo ...), $(uname ...)
  - Substitution containing destructive verbs → hard block
  - Other substitutions → advisory block (pass with confirmation)

Bypass: CLAUDE_ALLOW_INJECTION=1.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    allow,
    bash_command,
    block,
    bypass,
    log,
    read_event,
)

# Well-known side-effect-free utilities safe inside $(...)
TRIVIAL_CMDS = {
    "pwd", "date", "whoami", "hostname", "id", "uname", "echo", "printf",
    "basename", "dirname", "realpath", "readlink",
    "cat", "head", "tail",  # reads; add only if they take trivial args
    "which", "command", "type",
    "tr", "cut", "wc", "sort", "uniq",
    "git",  # git rev-parse etc is common and safe
    "node", "python", "python3",  # when running --version
}

SUBST_REGEX = re.compile(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
BACKTICK_REGEX = re.compile(r"`([^`]+)`")

DESTRUCTIVE_VERBS = re.compile(
    r"\b("
    r"dropdb|dropuser|drop\s+(table|database|schema)"
    r"|truncate\s+table"
    r"|delete\s+from\s+\w+(\s*;|\s*$|\s+where\s+(1\s*=\s*1|true))"  # DELETE no real WHERE
    r"|rm\s+-[rf]+"
    r"|mkfs\.|dd\s+if=|dd\s+of=/dev/"
    r"|kubectl\s+delete"
    r"|docker\s+(rm\s+-f|system\s+prune)"
    r"|killall|pkill"
    r"|shutdown|reboot|halt|poweroff"
    r"|:\s*\(\s*\)\s*\{"  # fork bomb
    r"|curl\s+.*\|\s*(sh|bash)"  # pipe to shell
    r"|wget\s+.*\|\s*(sh|bash)"
    r")",
    re.IGNORECASE,
)


# Read-only filters allowed as stages of a pipeline inside $(...), e.g.
# $(grep -h KEY file | cut -d= -f2). Owner 2026-11-17: such reads were refused.
# sed/awk stay out: both can run shell commands (sed `e`, awk system()).
READONLY_PIPE_CMDS = {
    "cat", "head", "tail", "tr", "cut", "wc", "sort", "uniq", "echo", "printf",
    "grep", "egrep", "fgrep", "rg", "jq", "ls", "stat", "basename", "dirname",
    "realpath", "readlink", "sha256sum", "sha1sum", "md5sum", "base64", "find",
}
FIND_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
SEPARATORS = {"|", "&&", "||", ";"}


def _readonly_pipeline(body: str) -> bool:
    """True if body is only read-only filters joined by | && || ; with no output redirect."""
    lex = shlex.shlex(body, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        return False
    stages: list[list[str]] = [[]]
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in SEPARATORS:
            stages.append([])
        elif t == ">&" and stages[-1][-1:] == ["2"] and tokens[i + 1:i + 2] == ["1"]:
            stages[-1].pop()
            i += 1
        elif t == ">" and stages[-1][-1:] == ["2"] and tokens[i + 1:i + 2] == ["/dev/null"]:
            stages[-1].pop()
            i += 1
        elif t == "<" and i + 1 < len(tokens) and tokens[i + 1] not in SEPARATORS:
            i += 1
        elif t and set(t) <= set("|&;<>()"):
            return False
        else:
            stages[-1].append(t)
        i += 1
    for words in stages:
        if not words or words[0].lstrip("\\") not in READONLY_PIPE_CMDS:
            return False
        if words[0] == "find" and FIND_ACTIONS & set(words):
            return False
    return True


def is_trivial(subst_body: str) -> bool:
    """Check if the substitution body is a safe utility with safe args."""
    body = subst_body.strip()
    if not body:
        return True
    # Heredoc forms: $(cat <<EOF ... EOF) or $(cat <<'EOF' ... EOF) -
    # safely reads multiline literal text into a string. No execution.
    if re.match(r"^(cat|printf|echo)\s+<<", body) or re.match(r"^<<", body):
        return True
    # First word determines the utility
    first = body.split(maxsplit=1)[0]
    first = first.lstrip("\\")  # strip leading escape
    if first in TRIVIAL_CMDS and not re.search(r"[;&|](?!\|)", body) and not re.search(r"[<>](?!<)", body):
        return True
    return _readonly_pipeline(body)


def find_substitutions(cmd: str) -> list[tuple[str, str]]:
    """Return list of (form, body) for each substitution in cmd.

    form: '$()' or '``'
    body: inner text
    """
    found: list[tuple[str, str]] = []
    # Skip single-quoted regions since $(...) is literal inside '...'
    # Approximate: remove content between unescaped single quotes
    sanitized = re.sub(r"'[^']*'", "''", cmd)
    for m in SUBST_REGEX.finditer(sanitized):
        found.append(("$()", m.group(1)))
    for m in BACKTICK_REGEX.finditer(sanitized):
        found.append(("``", m.group(1)))
    return found


def main() -> None:
    event = read_event()
    if event.get("tool_name") != "Bash":
        allow()

    cmd = bash_command(event.get("tool_input", {}))
    if not cmd:
        allow()

    substitutions = find_substitutions(cmd)
    if not substitutions:
        allow()

    # Check each substitution
    destructive_hits: list[str] = []
    nontrivial_hits: list[str] = []
    for form, body in substitutions:
        if DESTRUCTIVE_VERBS.search(body):
            destructive_hits.append(f"{form} -> {body[:80]}")
        elif not is_trivial(body):
            nontrivial_hits.append(f"{form} -> {body[:80]}")

    if not destructive_hits and not nontrivial_hits:
        allow()

    if bypass("injection", cmd):
        pattern = destructive_hits[0] if destructive_hits else nontrivial_hits[0]
        log("WARN", "block_command_injection", "bypass", pattern, cmd)
        allow()

    # Destructive substitution = always block
    if destructive_hits:
        log("BLOCK", "block_command_injection", "deny_destructive",
            destructive_hits[0], cmd)
        block(
            "Destructive shell substitution detected inside command:\n"
            f"  {destructive_hits[0]}\n"
            "Это класс багов когда текст который должен быть данными исполняется\n"
            "как команда из-за неверно escaped кавычек. Пример из практики:\n"
            "  gh issue create --body \"...$(dropdb prod)...\"\n"
            "Подстановка $() выполняется ДО того как аргумент попадает в gh.\n"
            "Что делать:\n"
            "  - использовать одинарные кавычки чтобы сделать $() literal\n"
            "  - передать текст через stdin: printf '...' | gh ...\n"
            "  - использовать --body-file вместо inline --body\n"
            "  - если точно нужна подстановка: CLAUDE_ALLOW_INJECTION=1"
        )

    # Non-trivial but non-destructive = advisory block
    log("BLOCK", "block_command_injection", "deny_nontrivial",
        nontrivial_hits[0], cmd)
    block(
        f"Non-trivial shell substitution: {nontrivial_hits[0]}\n"
        "Подстановка с side effects. Подтверди что она намеренная.\n"
        "Trivial substitutions (pwd, date, whoami, basename, dirname, echo) проходят.\n"
        "Если ок - CLAUDE_ALLOW_INJECTION=1."
    )


if __name__ == "__main__":
    main()
