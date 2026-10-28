#!/usr/bin/env python3
"""PreToolUse (Bash, PowerShell): block publishing routes that skip the pre-push leak scan.

Owner rule: nothing private may reach a PUBLIC repo; when in doubt, block; she may approve one
named action in chat. The scan runs only as the global git pre-push hook
(`git config --global core.hooksPath` -> scripts/git-hooks/pre-push -> pre-push-public-repo-scan.py),
so every route below publishes without it:

| route id           | command shape                                                                  |
|--------------------|--------------------------------------------------------------------------------|
| push-no-verify     | `git push --no-verify` (any unique abbreviation)                               |
| hookspath-override | `git -c core.hooksPath=...`, `--config-env=core.hooksPath=...` (any subcommand) |
| git-config-env     | `GIT_CONFIG*` / `GIT_EXTERNAL_DIFF` / `GIT_EXEC_PATH` / `HOME` / `USERPROFILE` /|
|                    | `XDG_CONFIG_HOME` set for a push                                               |
| hookspath-config   | any `git config` write of core.hooksPath                                       |
| send-pack          | `git send-pack` (plumbing push, never runs pre-push)                           |
| local-hooks        | push from a repo whose effective hooks folder is not the global one and whose  |
|                    | pre-push is not byte-identical (CRLF->LF) to hooks/pre-push-chain.sh or to the |
|                    | global pre-push, unless the push target is known PRIVATE                       |
| unknown-repo       | push whose working directory, or GIT_DIR / GIT_COMMON_DIR / GIT_WORK_TREE,     |
|                    | cannot be resolved                                                             |
| dynamic-git        | subcommand, push arguments or the command name from a variable, splat or xargs |
| alias-from-env     | non-builtin git subcommand while GIT_CONFIG_COUNT/KEY/VALUE/PARAMETERS or      |
|                    | `--config-env=alias.*` is set (the alias cannot be read)                       |
| unknown-shape      | a segment that reads as `git ... push` behind a command word this guard does   |
|                    | not know (wrappers with option values are stripped first: nice -n, timeout -s,  |
|                    | env -u/-C/-S, ionice, stdbuf, sudo -u, time -o, xargs)                         |
| (local-hooks)      | the private-target exemption is void when the same command rewrites a remote   |
|                    | (git remote add/set-url, git config remote.*/url.*, -c remote.*.url/pushurl,   |
|                    | -c url.*.insteadOf); `-c remote.*.url` also replaces the push target           |
| repo-public       | `gh repo edit --visibility public`, `gh repo create --public`                  |
| gist-public        | any `gh gist create` (a secret gist is readable by URL), `gh gist edit --add`   |
| api-write          | `gh`/`hub api` PUT/POST/PATCH on `repos/*/*/contents|git|releases`, `gists`,    |
|                    | graphql commit mutations; PATCH `repos/*/*` with visibility=public/private=false|
| http-write         | curl / wget / Invoke-RestMethod / Invoke-WebRequest writing to api.github.com   |
|                    | repos|gists or uploads.github.com                                               |
| alias-set          | `gh alias set` whose expansion is itself a gated route                         |
| encoded-command    | `pwsh -EncodedCommand` that does not decode (a decodable one is judged)        |
| release-public     | `gh release create|upload` on a repo that is PUBLIC or of unknown visibility    |

`git push -n` is `--dry-run` for push (it sends nothing), so it is not a hook skip and passes.
Commands run by builtins (`git submodule foreach`, `git bisect run`, `rebase -x/--exec`,
`difftool -x/--extcmd`) and git `!` aliases are judged as commands too. Before tokenising, a
Bash command gets bash's backslash removal (`pu\\sh` is `push`) and a PowerShell command loses
its backtick escapes (`--no-ver`ify`).

Residual risk / threat model
----------------------------
This guard catches agent MISTAKES and accidental routes, not deliberate masking: text matching
cannot win against an adversary, the same stance as human-confirmation-guard. Not covered:
- interpreters and script files: `python -c` building the command from string pieces,
  `bash x.sh`, `node -e`, a script written to disk and run later;
- other publishing surfaces: issues and comments (`gh issue create`, `gh pr comment`), GitHub
  Pages, wikis, packages/registries, non-GitHub hosts;
- environment carried in from outside the command (a shell profile).
The backstop for secrets is GitHub's server-side secret-scanning push protection on the public
repos; the pre-push leak scan stays the only check for private names and PII.

Commands are read as operations: the shared `executable_text` drops comments and printed
arguments, and only a segment whose command word is `git`/`gh` (after env prefixes and
wrappers) is judged, so `echo git push --no-verify` passes. Quoted arguments of anything that is
not a printer (`bash -c '...'`, `ssh host '...'`, `Start-Process ... '...'`) are judged as
commands too.

Approval: the owner's latest chat message (host-written transcript, the same reader as
human-confirmation-guard) unblocks a finding only when it has a go-ahead word, no negation or
question, and names the action: every needle group of the finding (route word + repo name or
API path). One audit line per approved command goes to ~/.claude/logs/publish-approvals.jsonl.
No in-command marker or env bypass: the agent can write those itself.
Any exception while judging a command that mentions git/gh blocks (fail closed).
"""
from __future__ import annotations

import base64
import datetime as _dt
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    _split_segments,
    allow,
    bash_command,
    block,
    executable_text,
    log,
    read_event,
)

HOOK = "publish-bypass-guard"
APPROVAL_LOG = Path.home() / ".claude" / "logs" / "publish-approvals.jsonl"
GIT_TIMEOUT = 15
GH_TIMEOUT = 25

MENTIONS = re.compile(r"\bgit\b|\bgh\b|\bgit\.exe\b|\bgh\.exe\b|GIT_", re.IGNORECASE)
# Escapes, encoded PowerShell, variable command names, HTTP clients and hub can hide a route from
# MENTIONS, so these also send the command to a full judgement.
MAYBE = re.compile(r"\\|`|-e[nc]|\$\{?\w+\}?\s+\S|\bhub\b|github\.com|\bcurl\b|\bwget\b|"
                   r"invoke-(?:rest|web)|\birm\b|\biwr\b", re.IGNORECASE)
# HOME/USERPROFILE/XDG_CONFIG_HOME move the global config, so the global core.hooksPath disappears.
PUSH_ENV = re.compile(r"^(?:GIT_CONFIG\w*|GIT_EXTERNAL_DIFF|GIT_EXEC_PATH|HOME|USERPROFILE|"
                      r"XDG_CONFIG_HOME)$", re.IGNORECASE)
_ENV_NAME = r"(GIT_CONFIG\w*|GIT_EXTERNAL_DIFF|GIT_EXEC_PATH|HOME|USERPROFILE|XDG_CONFIG_HOME)\b"
# Environment set by a separate statement of the same command line, Bash or PowerShell.
TEXT_ENV = re.compile(
    r"\$env:" + _ENV_NAME + r"\s*=|\bexport\s+" + _ENV_NAME + r"=|\bset\s+" + _ENV_NAME + r"=|"
    r"Environment\]::SetEnvironmentVariable\(\s*['\"]" + _ENV_NAME + r"|"
    r"(?:Set-Item|New-Item|si|ni)\s+(?:-Path\s+)?['\"]?env:" + _ENV_NAME,
    re.IGNORECASE)
REPO_VARS = ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")
REMOTE_WRITE = "<remote-write>"  # text_env marker: a segment rewrites a remote URL
# An env statement earlier in the same command line: name and literal value.
ENV_STATEMENT = re.compile(
    r"(?:\$env:|\bexport\s+|\bset\s+)(\w+)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s;&|]*))",
    re.IGNORECASE)
ENV_CONFIG_ALIAS = re.compile(r"^GIT_CONFIG_(?:COUNT|KEY_\d+|VALUE_\d+|PARAMETERS)$", re.IGNORECASE)
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
# Commands whose arguments are data, never a command: their quoted arguments are not re-judged.
PRINTERS = {"echo", "printf", "write-output", "write-host", "grep", "egrep", "fgrep", "rg", "ag",
            "findstr", "select-string", "sls", "cat", "type", "less", "more", "head", "tail", "wc"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
PWSH = {"powershell", "pwsh"}
CD = {"cd", "set-location", "sl", "chdir", "pushd", "push-location"}
KEYWORDS = {"(", "{", "!", "then", "do", "else", "elif", "if", "while", "until", "&", ".",
            "call", "--%"}
WRAPPERS = {"sudo", "nohup", "command", "builtin", "exec", "nice", "ionice", "stdbuf", "winpty",
            "time", "caffeinate", "doas"}
VALUE_WRAPPERS = {"timeout"}  # first positional is a duration
# Options of each wrapper that take a separate value (`nice -n 5 git push`).
WRAPPER_OPTIONS = {
    "nice": {"-n", "--adjustment"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "ionice": {"-c", "--class", "-n", "--classdata", "-p", "--pid", "-P", "--pgid", "-u", "--uid"},
    "stdbuf": {"-i", "--input", "-o", "--output", "-e", "--error"},
    "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C",
             "--close-from", "-D", "--chdir", "-r", "--role", "-t", "--type", "-U", "--other-user",
             "-T", "--command-timeout"},
    "doas": {"-u", "-C"},
    "time": {"-f", "--format", "-o", "--output"},
    "exec": {"-a"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "--arg-file", "--delimiter",
              "--max-args", "--max-procs", "--max-lines", "--max-chars", "-i", "--replace"},
}
# Command words this guard understands; anything else that still reads as `git ... push` is
# an unknown shape and blocks (fail closed).
KNOWN_SHAPES = {"git", "gh", "hub", "ssh", "plink", "cmd", "start-process", "saps", "start"}
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list",
                "--show-origin", "--show-scope", "get", "list"}
GIT_BUILTINS = set("""
status log diff add commit fetch pull checkout switch branch show rev-parse config remote worktree
stash merge rebase reset restore tag clone init ls-files grep blame cherry-pick describe rm mv
submodule gc reflog ls-remote apply am format-patch clean bisect notes archive for-each-ref cat-file
hash-object update-ref symbolic-ref show-ref rev-list merge-base name-rev shortlog version help lfs
mergetool difftool range-diff sparse-checkout maintenance var check-ignore count-objects fsck prune
repack verify-commit credential cherry revert whatchanged bundle mktree commit-tree read-tree
write-tree update-index diff-tree diff-index diff-files ls-tree check-attr check-ref-format
""".split())
GO = re.compile(
    r"разреш|можно|давай|делай|сделай|выполн|запуш|пушь|пушни|опубликуй|публикуй|выкладывай|выложи|"
    r"\bapprove\b|\ballow\b|\bgo\s+ahead\b|\bdo\s+it\b|\bproceed\b|\byes\b|\bда\b|\bок\b|\bok\b|"
    r"\bokay\b",
    re.IGNORECASE)
NOT_GO = re.compile(
    r"\bне\b|\bнельзя\b|\bнет\b|\bзапрещ|\bпогоди|\bподожди|\bdon'?t\b|\bdo\s+not\b|\bnever\b|"
    r"disapprov|disallow|\bden(?:y|ied)\b|\breject|\bforbid|\bstop\b|\bwait\b|"
    r"\bno\b|\bnot\b|\?",
    re.IGNORECASE)
FLAG_TOKEN = re.compile(r"(?<!\S)-{1,2}[\w.=-]+")
GITHUB_SLUG =re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.IGNORECASE)
PUBLIC = ("public", "публич")


@dataclass
class Finding:
    route: str
    detail: str
    fix: str
    needles: list[tuple[str, ...]] = field(default_factory=list)


@dataclass
class Cmd:
    name: str
    argv: list[str]
    env: dict[str, str]
    cwd: str | None          # None: unknown local directory
    remote: bool             # runs on another machine (ssh)
    raw: str
    fed: bool = False        # arguments also arrive on stdin (xargs)
    shell: str = "bash"


# ---------------------------------------------------------------- command reading

def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    return token


def tokenize(segment: str) -> list[str]:
    """Split one segment, keeping backslashes (Windows paths) and quoted runs together."""
    try:
        lexer = shlex.shlex(segment, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        lexer.escape = ""  # keep C:\path intact; quotes still group `alias.x="push --no-verify"`
        return list(lexer)
    except ValueError:
        return [_unquote(t) for t in segment.split()]


def _substitutions(text: str) -> list[str]:
    """Bodies of `$( ... )` and backtick substitutions; they run before the outer command."""
    found: list[str] = []
    index = 0
    while True:
        start = text.find("$(", index)
        if start < 0:
            break
        depth, cursor = 1, start + 2
        while cursor < len(text) and depth:
            if text[cursor] == "(":
                depth += 1
            elif text[cursor] == ")":
                depth -= 1
            cursor += 1
        found.append(text[start + 2:cursor - 1])
        index = cursor
    found.extend(re.findall(r"`([^`]+)`", text))
    return found


def _command_name(token: str) -> str:
    name = re.split(r"[\\/]", token)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def local_path(target: str) -> str:
    """Git Bash spells C:/x as /c/x; the probes run Windows git, which needs the drive form."""
    match = re.match(r"^/([A-Za-z])(?:/(.*))?$", target)
    if os.name == "nt" and match:
        return f"{match.group(1).upper()}:/{match.group(2) or ''}"
    return target


def _resolve_dir(base: str | None, target: str) -> str | None:
    target = local_path(target)
    if base is None or re.search(r"[$`%]", target):
        return None
    if target.startswith("~") and len(target) > 1 and target[1] not in "/\\":
        return None  # ~user
    target = os.path.expanduser(target)
    path = Path(target) if os.path.isabs(target) else Path(base) / target
    return str(path)


def normalise_bash(text: str) -> str:
    """Apply bash quote removal for backslashes: `--no-ve\\rify` and `pu\\sh` are what bash runs.

    Outside quotes `\\X` is X; inside double quotes only `\\$ \\` \\" \\\\` and newline escape.
    An escaped quote or `$` is re-emitted quoted so the tokenizer still reads it as a literal.
    """
    out: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote == "'":
            out.append(char)
            if char == "'":
                quote = None
        elif char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            if nxt == "\n":
                index += 2
                continue
            if quote == '"' and nxt not in '$`"\\':
                out.append(char)
            elif quote == '"':
                out.append(nxt)
                index += 2
                continue
            else:
                out.append({"'": '"\'"', '"': "'\"'", "$": "'$'", "`": "'`'"}.get(nxt, nxt))
                index += 2
                continue
        else:
            out.append(char)
            if char in "'\"" and quote is None:
                quote = char
            elif char == quote:
                quote = None
        index += 1
    return "".join(out)


def normalise_powershell(text: str) -> str:
    """Remove PowerShell backtick escapes outside single quotes: `--no-ver`ify` is `--no-verify`."""
    out: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote == "'":
            out.append(char)
            if char == "'":
                quote = None
        elif char == "`" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append(" " if nxt == "\n" else nxt)
            index += 2
            continue
        else:
            out.append(char)
            if char in "'\"" and quote is None:
                quote = char
            elif char == quote:
                quote = None
        index += 1
    return "".join(out)


def normalise(text: str, shell: str) -> str:
    if shell == "powershell":
        return normalise_powershell(text)
    if shell == "cmd":
        return text.replace("^", "")
    return normalise_bash(text)


def decode_encoded_command(argv: list[str]) -> str | None:
    """Body of `pwsh -EncodedCommand <base64 UTF-16LE>`; '' when the flag is absent, None if undecodable."""
    for at, token in enumerate(argv[1:], start=1):
        flag = token.lower().split(":", 1)[0]
        if len(flag) >= 2 and flag.startswith("-e") and ("-encodedcommand".startswith(flag)
                                                         or flag == "-ec"):
            value = token.split(":", 1)[1] if ":" in token else (argv[at + 1] if at + 1 < len(argv)
                                                                 else "")
            try:
                return base64.b64decode(value, validate=True).decode("utf-16-le")
            except (ValueError, UnicodeDecodeError):
                return None
    return ""


def _start_process(argv: list[str], cwd: str | None) -> tuple[list[str], str | None] | None:
    """`Start-Process git -ArgumentList 'push origin main' -WorkingDirectory ../r` as the git call."""
    lowered = [a.lower() for a in argv]
    file_path, arguments, workdir = None, [], cwd
    index = 1
    while index < len(argv):
        token = lowered[index]
        value = argv[index + 1] if index + 1 < len(argv) else ""
        if token in ("-filepath", "-file"):
            file_path, index = value, index + 2
        elif token in ("-argumentlist", "-args", "-arguments"):
            arguments += [part for chunk in value.split(",") for part in tokenize(chunk)]
            index += 2
        elif token in ("-workingdirectory", "-wd"):
            workdir, index = _resolve_dir(cwd, value), index + 2
        elif token.startswith("-"):
            index += 1
        elif file_path is None:
            file_path, index = argv[index], index + 1
        else:
            arguments += [part for chunk in argv[index].split(",") for part in tokenize(chunk)]
            index += 1
    if not file_path:
        return None
    return [file_path, *arguments], workdir


PS_ASSIGNMENT = re.compile(r"^\$[\w:{}]+\s*(?:[+\-*/]?=|$)")


def iter_commands(text: str, cwd: str | None, remote: bool = False, depth: int = 0,
                  shell: str = "bash"):
    """Every simple command the text would run, with its env prefix and working directory."""
    if depth > 6 or not text:
        return
    current = cwd
    for line in executable_text(normalise(text, shell)).splitlines():
        for segment in _split_segments(line)[0::2]:
            if not segment.strip():
                continue
            for inner in _substitutions(segment):
                yield from iter_commands(inner, current, remote, depth + 1, shell)
            tokens = tokenize(segment)
            env: dict[str, str] = {}
            fed = False
            cmd_cwd = current
            while tokens:
                head = tokens[0]
                if head in KEYWORDS or head in {"(", "{"}:
                    tokens = tokens[1:]
                    continue
                if head.startswith(("(", "{")) and len(head) > 1:
                    tokens = [head[1:]] + tokens[1:]
                    continue
                match = ASSIGN.match(head)
                if match:
                    env[match.group(1)] = match.group(2)
                    tokens = tokens[1:]
                    continue
                name = _command_name(head)
                if name in WRAPPERS or name in VALUE_WRAPPERS or name in ("env", "xargs"):
                    tokens = tokens[1:]
                    fed = fed or name == "xargs"
                    needs_value = name in VALUE_WRAPPERS
                    valued = WRAPPER_OPTIONS.get(name, set())
                    while tokens:
                        word = tokens[0]
                        if word == "--":
                            tokens = tokens[1:]
                            break
                        if word.startswith("-"):
                            tokens = tokens[1:]
                            option, _, attached = word.partition("=")
                            value = attached
                            if word in valued and tokens:
                                value = tokens[0]
                                tokens = tokens[1:]
                            if name == "env" and option in ("-C", "--chdir") and value:
                                cmd_cwd = _resolve_dir(cmd_cwd, value)
                            elif name == "env" and option in ("-S", "--split-string") and value:
                                tokens = tokenize(value) + tokens
                        elif name == "env" and ASSIGN.match(word):
                            assigned = ASSIGN.match(word)
                            env[assigned.group(1)] = assigned.group(2)
                            tokens = tokens[1:]
                        elif needs_value:
                            needs_value = False
                            tokens = tokens[1:]
                        else:
                            break
                    continue
                break
            if not tokens:
                continue
            if PS_ASSIGNMENT.match(tokens[0]) and (len(tokens) == 1 or "=" in tokens[0]
                                                   or tokens[1].startswith("=")):
                continue  # PowerShell `$x = ...` assigns; the value is data
            name = _command_name(tokens[0])
            argv = tokens
            if name in CD:
                args = [t for t in argv[1:] if not t.startswith("-")]
                current = _resolve_dir(current, args[0]) if args else str(Path.home())
                continue
            if name in ("start-process", "saps", "start") and shell == "powershell":
                launched = _start_process(argv, cmd_cwd)
                if launched:
                    yield Cmd(_command_name(launched[0][0]), launched[0], env, launched[1], remote,
                              segment, fed, shell)
                    continue
            yield Cmd(name, argv, env, cmd_cwd, remote, segment, fed, shell)
            if name in PRINTERS or name in ("git", "gh", "hub"):
                continue  # their quoted arguments are values (--grep, -m); git/gh run-command
                # options are judged in judge_git / judge_gh
            if name in SHELLS and "-c" in argv:
                at = argv.index("-c")
                if at + 1 < len(argv):
                    yield from iter_commands(argv[at + 1], current, remote, depth + 1, "bash")
                continue
            if name in PWSH:
                decoded = decode_encoded_command(argv)
                if decoded is None:
                    yield Cmd("<undecodable-encodedcommand>", argv, env, current, remote, segment,
                              fed, "powershell")
                elif decoded:
                    yield from iter_commands(decoded, current, remote, depth + 1, "powershell")
                for flag_at, token in enumerate(argv):
                    if token.lower() in ("-command", "-c"):
                        yield from iter_commands(" ".join(argv[flag_at + 1:]), current, remote,
                                                 depth + 1, "powershell")
                        break
                continue
            if name == "cmd":
                for flag_at, token in enumerate(argv):
                    if token.lower() in ("/c", "/k"):
                        yield from iter_commands(" ".join(argv[flag_at + 1:]), current, remote,
                                                 depth + 1, "cmd")
                        break
                continue
            is_remote = remote or name in ("ssh", "plink")
            for token in argv[1:]:
                if re.search(r"\s", token):
                    yield from iter_commands(token, None if is_remote else current, is_remote,
                                             depth + 1, "bash" if is_remote else shell)


# ---------------------------------------------------------------- git / gh probes

def _run(args: list[str], cwd: str | None, timeout: int = GIT_TIMEOUT,
         env: dict[str, str] | None = None) -> str | None:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, check=False,
                                env={**os.environ, **env} if env else None)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def repo_visibility(slug: str) -> str | None:
    """PUBLIC / PRIVATE / INTERNAL from GitHub, or None when it cannot be established."""
    out = _run(["gh", "repo", "view", slug, "--json", "visibility", "-q", ".visibility"], None,
               GH_TIMEOUT)
    return out.upper() if out else None


def slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = GITHUB_SLUG.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def _norm(path: str | None) -> str:
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.expanduser(path))).rstrip("\\/")


CHAIN_FILE = Path(__file__).with_name("pre-push-chain.sh")


def _global_hooks_dir() -> str | None:
    return _run(["git", "config", "--global", "--get", "core.hooksPath"], None)


def _global_hook_has_scan(path: Path) -> bool:
    """The global pre-push is the canonical file in this repo; it must still name the scanner."""
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    return "pre-push-public-repo-scan" in code


def _bytes_lf(path: Path) -> bytes | None:
    try:
        return path.read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return None


def _hook_chains_to_scan(path: Path, global_hooks: str | None) -> bool:
    """A repo-local pre-push passes only when it is, byte for byte after CRLF->LF, the canonical
    chain hook (hooks/pre-push-chain.sh) or a copy of the global pre-push itself.

    Parsing the shell to decide "does it call the scan" lost to an `exit 0` line or an echo naming
    the scan; exact bytes cannot be argued with. Any other content blocks.
    """
    local = _bytes_lf(path) if path.is_file() else None
    if local is None:
        return False
    if local == _bytes_lf(CHAIN_FILE):
        return True
    if global_hooks:
        canonical_global = _bytes_lf(Path(os.path.expanduser(global_hooks)) / "pre-push")
        return canonical_global is not None and local == canonical_global
    return False


@dataclass
class Repo:
    top: str | None
    hooks: str | None
    git: list[str]
    env: dict[str, str] | None = None

    def label(self) -> tuple[str, ...]:
        names = []
        if self.top:
            names.append(Path(self.top).name)
        return tuple(names)


def open_repo(cwd: str, location: list[str], env: dict[str, str] | None = None) -> Repo:
    git = ["git", "-C", cwd, *location]
    top = _run([*git, "rev-parse", "--show-toplevel"], None, env=env) or _run(
        [*git, "rev-parse", "--absolute-git-dir"], None, env=env)
    hooks = _run([*git, "rev-parse", "--path-format=absolute", "--git-path", "hooks"], None, env=env)
    return Repo(top, hooks, git, env)


def push_target_slug(repo: Repo, args: list[str]) -> str | None:
    positional = []
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        if token in ("-o", "--push-option", "--receive-pack", "--exec", "--repo"):
            skip = True
            continue
        if token.startswith("--repo="):
            positional.insert(0, token.split("=", 1)[1])
            continue
        if not token.startswith("-"):
            positional.append(token)
    remote = positional[0] if positional else None
    if remote and re.search(r"://|@|^[A-Za-z]:[\\/]|^/", remote):
        return slug_from_url(remote)
    if not remote:
        upstream = _run([*repo.git, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}"],
                        None, env=repo.env)
        remote = upstream.split("/", 1)[0] if upstream else "origin"
    return slug_from_url(_run([*repo.git, "remote", "get-url", "--push", remote], None,
                              env=repo.env))


def current_slug(cwd: str | None, repo_flag: str | None) -> str | None:
    if repo_flag:
        return slug_from_url("github.com/" + repo_flag) if "/" in repo_flag else None
    if cwd is None:
        return None
    return slug_from_url(_run(["git", "-C", cwd, "remote", "get-url", "--push", "origin"], None))


# ---------------------------------------------------------------- judging

def _repo_needle(slug: str | None, repo: Repo | None) -> tuple[str, ...]:
    names: list[str] = []
    if slug:
        names += [slug, slug.split("/", 1)[1]]
    if repo:
        names += list(repo.label())
    return tuple(dict.fromkeys(names)) or ("<repository unresolved>",)


def _judge_text(text: str, cwd: str | None, cmd: Cmd, text_env: dict[str, str],
                findings: list[Finding], depth: int) -> None:
    for inner in iter_commands(text, cwd, cmd.remote, 1, "bash"):
        judge(inner, text_env, findings, depth + 1)


def _option_values(args: list[str], short: str, long: str) -> list[str]:
    values = []
    for at, token in enumerate(args):
        if token in (short, long) and at + 1 < len(args):
            values.append(args[at + 1])
        elif token.startswith(long + "="):
            values.append(token.split("=", 1)[1])
        elif token.startswith(short) and len(token) > len(short) and not token.startswith("--"):
            values.append(token[len(short):])
    return values


def judge_git(cmd: Cmd, text_env: dict[str, str], findings: list[Finding], depth: int = 0) -> None:
    argv = cmd.argv
    location: list[str] = []
    config: list[str] = []
    config_env: list[str] = []
    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        token = argv[index]
        nxt = argv[index + 1] if index + 1 < len(argv) else ""
        if token == "-C":
            location += ["-C", local_path(nxt)]
            index += 2
        elif token == "-c":
            config.append(nxt)
            index += 2
        elif token.startswith("--config-env"):
            if "=" in token:
                config.append(token.split("=", 1)[1])
                index += 1
            else:
                config.append(nxt)
                index += 2
            config_env.append(config[-1])
        elif token in ("--git-dir", "--work-tree", "--namespace"):
            location += [token, nxt]
            index += 2
        elif token.startswith(("--git-dir=", "--work-tree=", "--namespace=")):
            location.append(token)
            index += 1
        else:
            index += 1
    sub = argv[index] if index < len(argv) else ""
    args = argv[index + 1:]

    for item in config:
        if item.split("=", 1)[0].strip().lower() == "core.hookspath":
            findings.append(Finding(
                "hookspath-override",
                f"`{cmd.raw.strip()}` overrides core.hooksPath for this git call, so the global "
                "pre-push scan does not run",
                "drop the -c/--config-env core.hooksPath override",
                [("core.hookspath",)]))
    if sub == "config" and any("core.hookspath" in a.lower() for a in args) \
            and not any(a.lower() in CONFIG_READS for a in args):
        findings.append(Finding(
            "hookspath-config",
            f"`{cmd.raw.strip()}` rewrites core.hooksPath; a push after it (in this command or "
            "later) can run without the global pre-push scan",
            "leave core.hooksPath alone; chain a local pre-push to the global one instead",
            [("core.hookspath",)]))
    if sub.startswith(("$", "@")) or "$(" in sub or (cmd.fed and sub in ("", "push", "send-pack")):
        findings.append(Finding(
            "dynamic-git", f"`{cmd.raw.strip()}` takes its git subcommand or arguments from a "
            "variable, splat or stdin, so a hook skip cannot be ruled out",
            "write the push literally", [(cmd.raw.strip().lower(),)]))
        return

    # Builtins that run a command of their own: judge that command too.
    if depth < 3:
        if sub == "submodule" and args[:1] == ["foreach"]:
            rest = [a for a in args[1:] if a not in ("--recursive", "-q", "--quiet")]
            _judge_text(" ".join(rest), None, cmd, text_env, findings, depth)
        elif sub == "bisect" and args[:1] == ["run"]:
            _judge_text(" ".join(args[1:]), cmd.cwd, cmd, text_env, findings, depth)
        elif sub == "rebase":
            for value in _option_values(args, "-x", "--exec"):
                _judge_text(value, cmd.cwd, cmd, text_env, findings, depth)
        elif sub == "difftool":
            for value in _option_values(args, "-x", "--extcmd"):
                _judge_text(value, cmd.cwd, cmd, text_env, findings, depth)

    if sub and sub not in GIT_BUILTINS and sub not in ("push", "send-pack"):
        env_cfg = sorted({n for n in (*cmd.env, *text_env) if ENV_CONFIG_ALIAS.match(n)}
                         | {n for n in os.environ if ENV_CONFIG_ALIAS.match(n)})
        alias_env = [c for c in config_env if c.split("=", 1)[0].strip().lower().startswith("alias.")]
        if env_cfg or alias_env:
            findings.append(Finding(
                "alias-from-env", f"`{cmd.raw.strip()}` runs `git {sub}`, not a builtin, while git "
                f"config comes from {', '.join(env_cfg + alias_env)}; the alias it resolves to "
                "cannot be checked", "write the git subcommand literally",
                [(cmd.raw.strip().lower(),)]))
            return

    if sub and sub not in GIT_BUILTINS and sub not in ("push", "send-pack") and depth < 3:
        expansion = None
        for item in config:
            key, _, value = item.partition("=")
            if key.strip().lower() == f"alias.{sub.lower()}":
                expansion = value
        if expansion is None:
            where = cmd.cwd if cmd.cwd and Path(cmd.cwd).is_dir() else None
            expansion = _run(["git", *(["-C", where] if where else []), *location, "config",
                              "--get", f"alias.{sub}"], None)
        if expansion:
            if expansion.startswith("!"):
                _judge_text(expansion[1:] + " " + " ".join(args), cmd.cwd, cmd, text_env,
                            findings, depth)
                return
            expanded = Cmd(cmd.name, ["git", *argv[1:index], *tokenize(expansion), *args],
                           cmd.env, cmd.cwd, cmd.remote, cmd.raw)
            judge_git(expanded, text_env, findings, depth + 1)
            return

    if sub not in ("push", "send-pack"):
        return

    env_names = {name for name in (*cmd.env, *text_env) if PUSH_ENV.match(name)}
    for name in ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"):
        inherited = os.environ.get(name, "")
        if inherited and ("hookspath" in inherited.lower() or any(
                "hookspath" in v.lower() for k, v in os.environ.items()
                if k.upper().startswith("GIT_CONFIG_VALUE") or k.upper().startswith("GIT_CONFIG_KEY"))):
            env_names.add(name + " (inherited)")

    if any((a.startswith(("$", "@")) and not a.startswith("@{")) or "$(" in a for a in args):
        findings.append(Finding(
            "dynamic-git", f"`{cmd.raw.strip()}` passes push arguments through a variable or "
            "splat, which can carry --no-verify", "write the push arguments literally",
            [(cmd.raw.strip().lower(),)]))
    repo: Repo | None = None
    slug: str | None = None
    override_urls = [c.split("=", 1)[1] for c in config if "=" in c and re.fullmatch(
        r"remote\.[^=]+\.(?:push)?url", c.split("=", 1)[0].strip(), re.IGNORECASE)]
    rewrites = [c for c in config if re.match(r"url\..*\.(?:push)?insteadof", c.split("=", 1)[0],
                                               re.IGNORECASE)]
    target_changed = bool(override_urls or rewrites or text_env.get(REMOTE_WRITE))
    repo_env = {k: v for k, v in {**text_env, **cmd.env}.items() if k.upper() in REPO_VARS}
    unresolvable_env = [k for k, v in repo_env.items() if not v or re.search(r"[$`%]", v)]
    if cmd.cwd and repo_env:
        repo_env = {k: str(Path(cmd.cwd) / local_path(v)) if not os.path.isabs(local_path(v))
                    else local_path(v) for k, v in repo_env.items()}
    if cmd.cwd and not cmd.remote and Path(cmd.cwd).is_dir() and not unresolvable_env:
        repo = open_repo(cmd.cwd, location, repo_env or None)
        if repo.top:
            slug = push_target_slug(repo, args)
    if override_urls:
        slug = slug_from_url(override_urls[-1])
    if repo_env and not cmd.remote and (unresolvable_env or repo is None or not repo.top):
        findings.append(Finding(
            "unknown-repo", f"`{cmd.raw.strip()}` pushes from the repository named by "
            f"{', '.join(sorted(repo_env))}, which cannot be resolved here",
            "push from the repository directory without GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR",
            [(cmd.raw.strip().lower(),)]))
        return
    needle = _repo_needle(slug, repo)
    where = (repo.top if repo and repo.top else cmd.cwd) or "an unresolved directory"

    if sub == "send-pack":
        findings.append(Finding("send-pack", f"`git send-pack` in {where} pushes without any "
                                "pre-push hook", "use `git push` so the scan runs",
                                [("send-pack",), needle]))
        return
    for name in sorted(env_names):
        findings.append(Finding(
            "git-config-env",
            f"push in {where} runs with {name} set; it can replace core.hooksPath or the "
            "global config and skip the scan",
            f"remove {name} from the push command", [(name.split()[0].lower(),), needle]))
    if any(a == "--no-verify" or a.startswith("--no-veri") for a in args):
        findings.append(Finding("push-no-verify", f"`git push --no-verify` in {where} skips the "
                                "pre-push leak scan", "push without --no-verify",
                                [("--no-verify",), needle]))
    if cmd.remote:
        return
    if cmd.cwd is None or not Path(cmd.cwd).is_dir():
        findings.append(Finding(
            "unknown-repo", f"cannot resolve which repository `{cmd.raw.strip()}` pushes from "
            f"(working directory {cmd.cwd or 'from a variable or substitution'} is not found here)",
            "cd to a literal path before the push", [(cmd.raw.strip().lower(),)]))
        return
    if repo is None or not repo.top or not repo.hooks:
        return  # not a repository: git itself refuses the push
    global_hooks = _global_hooks_dir()
    if global_hooks and _norm(repo.hooks) == _norm(global_hooks):
        if _global_hook_has_scan(Path(os.path.expanduser(global_hooks)) / "pre-push"):
            return
    elif _hook_chains_to_scan(Path(repo.hooks) / "pre-push", global_hooks):
        return
    visibility = repo_visibility(slug) if slug else None
    if visibility in ("PRIVATE", "INTERNAL") and not (rewrites or text_env.get(REMOTE_WRITE)):
        return
    hooks_dir = repo.hooks
    findings.append(Finding(
        "local-hooks",
        f"repo {repo.top} uses hooks folder {hooks_dir} (global: {global_hooks or 'unset'}) and "
        f"its pre-push does not run the public leak scan; push target "
        f"{slug or 'unresolved'} is {visibility or 'of unknown visibility'}"
        + ("; the push target is rewritten in this same command" if target_changed else ""),
        f"copy {CHAIN_FILE} to {Path(hooks_dir) / 'pre-push'} unchanged (it runs the global "
        f"pre-push and refuses the push without it), or `git -C \"{repo.top}\" config --unset "
        "core.hooksPath`",
        [needle, ("push", "пуш")]))


def _opt_value(args: list[str], names: tuple[str, ...]) -> str | None:
    for at, token in enumerate(args):
        for name in names:
            if token == name and at + 1 < len(args):
                return args[at + 1]
            if name.startswith("--") and token.startswith(name + "="):
                return token.split("=", 1)[1]
            if not name.startswith("--") and token.startswith(name) and len(token) > len(name):
                return token[len(name):]
    return None


def _positionals(args: list[str], valued: set[str]) -> list[str]:
    out, skip = [], False
    for token in args:
        if skip:
            skip = False
            continue
        if token in valued:
            skip = True
            continue
        if token.startswith("-"):
            continue
        out.append(token)
    return out


def _flag_on(lowered: list[str], flag: str) -> bool:
    """`--public` and `--public=true` count; `--public=false` does not."""
    return any(a == flag or (a.startswith(flag + "=") and a.split("=", 1)[1] not in ("false", "0"))
               for a in lowered)


FIELD_FLAGS = ("-f", "-F", "--field", "--raw-field")


def _api_fields(api_args: list[str]) -> list[str]:
    """`key=value` of every -f/-F/--field/--raw-field, already unquoted by the tokenizer."""
    values = []
    for at, token in enumerate(api_args):
        if token in FIELD_FLAGS and at + 1 < len(api_args):
            values.append(api_args[at + 1])
        elif token.startswith(("--field=", "--raw-field=")):
            values.append(token.split("=", 1)[1])
        elif token[:2] in ("-f", "-F") and not token.startswith("--") and len(token) > 2:
            values.append(token[2:])
    return [v.lower().replace(" ", "") for v in values]


def judge_gh(cmd: Cmd, findings: list[Finding], text_env: dict[str, str] | None = None,
             depth: int = 0) -> None:
    argv = cmd.argv
    sub = argv[1].lower() if len(argv) > 1 else ""
    verb = argv[2].lower() if len(argv) > 2 else ""
    args = argv[3:]
    lowered = [a.lower() for a in args]
    env_all = {**(text_env or {}), **cmd.env}
    repo_flag = (_opt_value(args, ("-R", "--repo")) or env_all.get("GH_REPO")
                 or os.environ.get("GH_REPO"))
    local_cwd = None if cmd.remote else cmd.cwd

    if sub == "repo" and verb == "edit":
        value = _opt_value(lowered, ("--visibility",))
        if value == "public":
            pos = _positionals(args, {"--visibility", "--description", "-d", "--homepage", "-h",
                                      "--default-branch", "--add-topic", "--remove-topic"})
            slug = pos[0] if pos and "/" in pos[0] else current_slug(local_cwd, repo_flag)
            findings.append(Finding("repo-public", f"`gh repo edit` makes {slug or 'the current repo'}"
                                    " PUBLIC; everything already pushed becomes readable without "
                                    "any scan", "keep the repo private",
                                    [PUBLIC, _repo_needle(slug, None) if slug else
                                     (Path(local_cwd).name if local_cwd else "<repo>",)]))
    elif sub == "repo" and verb == "create" and _flag_on(lowered, "--public"):
        pos = _positionals(args, {"--description", "-d", "--homepage", "-h", "--source", "-s",
                                  "--remote", "-r", "--team", "-t", "--template", "-p",
                                  "--gitignore", "-g", "--license", "-l"})
        name = pos[0] if pos else (Path(local_cwd).name if local_cwd else "<new repo>")
        findings.append(Finding("repo-public", f"`gh repo create --public` creates {name} as a "
                                "PUBLIC repo (with --push its content is published unscanned)",
                                "create it with --private", [PUBLIC, (name, name.split("/")[-1])]))
    elif sub == "gist" and verb == "create":
        findings.append(Finding("gist-public", "`gh gist create` publishes files with no scan "
                                "(a secret gist is still readable by anyone with its URL)",
                                "keep the files in a private repo", [("gist", "гист")]))
    elif sub == "alias" and verb == "set" and depth < 3:
        pos = _positionals(args, {"--clobber"})
        expansion = pos[1] if len(pos) > 1 else ""
        nested: list[Finding] = []
        if expansion.startswith("!") or "--shell" in lowered or "-s" in lowered:
            for inner in iter_commands(expansion.lstrip("!"), cmd.cwd, cmd.remote, 1, "bash"):
                judge(inner, text_env or {}, nested, depth + 1)
        else:
            judge_gh(Cmd("gh", ["gh", *tokenize(expansion)], cmd.env, cmd.cwd, cmd.remote, expansion),
                     nested, text_env, depth + 1)
        if nested:
            findings.append(Finding("alias-set", f"`gh alias set {pos[0] if pos else ''}` defines a "
                                    f"gated route ({', '.join(sorted({f.route for f in nested}))})",
                                    "run the command itself so the guard can judge it",
                                    [("alias",), (pos[0].lower() if pos else "alias",)]))
    elif sub == "gist" and verb == "edit" and ("--add" in lowered or "-a" in lowered
                                               or any(a.startswith("--add=") for a in lowered)):
        findings.append(Finding("gist-public", "`gh gist edit --add` adds files to a gist whose "
                                "visibility is not checked here", "do not add files to gists",
                                [("gist", "гист"), ("--add", "-a")]))
    elif sub == "api":
        api_args = argv[2:]
        method = _opt_value(api_args, ("-X", "--method"))
        # gh api: "The default HTTP request method is GET normally and POST if any parameters were added".
        fields = any(a in ("-f", "-F", "--field", "--raw-field", "--input")
                     or a.startswith(("--field=", "--raw-field=", "--input="))
                     or (a[:2] in ("-f", "-F") and not a.startswith("--")) for a in api_args)
        method = (method or ("POST" if fields else "GET")).upper()
        pos = _positionals(api_args, {"-X", "--method", "-H", "--header", "-f", "-F", "--field",
                                      "--raw-field", "--input", "-q", "--jq", "-t", "--template",
                                      "--hostname", "--cache", "-p", "--preview"})
        path = pos[0] if pos else ""
        path = re.sub(r"^https?://[^/]+/(?:api/v3/)?", "", path).split("?", 1)[0]
        path = re.sub(r"/{2,}", "/", path).strip("/")
        if method in ("PUT", "POST", "PATCH", "DELETE") and (path.startswith(("$", "@"))
                                                             or "$(" in path or "${" in path):
            findings.append(Finding("dynamic-git", f"`gh api -X {method}` takes its path from "
                                    f"{path}, which cannot be judged", "write the API path literally",
                                    [(cmd.raw.strip().lower(),)]))
            return
        field_values = _api_fields(api_args)
        text = " ".join(argv).lower()
        if path.lower() == "graphql":
            if "createcommitonbranch" in text or any(a.startswith("--input") for a in api_args):
                findings.append(Finding("api-write", "`gh api graphql` commit mutation (or a "
                                        "query read from --input) writes repo content with no scan",
                                        "commit and `git push` instead",
                                        [("graphql",), ("createcommitonbranch", "--input")]))
        elif method in ("PUT", "POST", "PATCH"):
            if re.match(r"(?:repos/[^/]+/[^/]+/(?:contents|git|releases)|gists)(?:/|$)", path,
                        re.IGNORECASE):
                findings.append(Finding("api-write", f"`gh api -X {method} {path}` writes repo "
                                        "content directly, past the pre-push scan",
                                        "commit and `git push` instead", [(path.lower(),)]))
            elif method == "PATCH" and re.fullmatch(r"repos/[^/]+/[^/]+/?", path, re.IGNORECASE) \
                    and (any(v in ("visibility=public", "private=false") for v in field_values)
                         or any(a.startswith("--input") for a in api_args)):
                findings.append(Finding("repo-public", f"`gh api -X PATCH {path}` can make the repo "
                                        "PUBLIC", "keep the repo private", [(path.lower(),), PUBLIC]))
    elif sub == "release" and verb in ("create", "upload"):
        slug = current_slug(local_cwd, repo_flag)
        visibility = repo_visibility(slug) if slug else None
        if visibility not in ("PRIVATE", "INTERNAL"):
            findings.append(Finding("release-public", f"`gh release {verb}` uploads assets/notes to "
                                    f"{slug or 'an unresolved repo'} "
                                    f"({visibility or 'visibility unknown'}) with no scan",
                                    "publish releases only from private repos, or get approval",
                                    [("release", "релиз"), _repo_needle(slug, None) if slug else
                                     (cmd.raw.strip().lower(),)]))


HTTP_CLIENTS = {"curl", "wget", "invoke-restmethod", "invoke-webrequest", "irm", "iwr"}
GITHUB_WRITE_URL = re.compile(r"(?:api\.github\.com/+(?:repos|gists)|uploads\.github\.com)/*",
                              re.IGNORECASE)
WRITE_METHODS = {"PUT", "POST", "PATCH", "DELETE"}


def judge_http(cmd: Cmd, findings: list[Finding]) -> None:
    """curl/wget/Invoke-RestMethod writing to the GitHub API publish with no scan."""
    argv = cmd.argv
    urls = [a for a in argv[1:] if GITHUB_WRITE_URL.search(a)]
    if not urls:
        return
    lowered = [a.lower() for a in argv[1:]]
    method = (_opt_value(argv[1:], ("-X", "--request", "--method")) or "")
    for at, token in enumerate(lowered):
        if token in ("-method", "-m") and at + 1 < len(lowered):
            method = argv[at + 2]
    method = method.upper()
    implied = any(a.startswith(("-d", "--data", "-f", "--form", "-t", "--upload-file", "--json",
                                "--post-data", "--post-file", "--body-data", "--body-file",
                                "-body", "-infile"))
                  for a in lowered)
    if method in WRITE_METHODS or (not method and implied):
        findings.append(Finding("http-write", f"`{cmd.name}` sends {method or 'a body'} to "
                                f"{urls[0]}, writing to GitHub past the pre-push scan",
                                "commit and `git push` instead", [(urls[0].lower(),)]))


def judge(cmd: Cmd, text_env: dict[str, str], findings: list[Finding], depth: int = 0) -> None:
    raw_low = cmd.raw.lower()
    if cmd.name == "<undecodable-encodedcommand>":
        findings.append(Finding("encoded-command", "`-EncodedCommand` payload does not decode as "
                                "base64 UTF-16LE, so it cannot be judged",
                                "run the command as plain text", [(cmd.raw.strip().lower(),)]))
    elif cmd.name.startswith("$") and re.search(r"\bpush\b|--no-veri|send-pack|hookspath", raw_low):
        findings.append(Finding("dynamic-git", f"`{cmd.raw.strip()}` runs a command named by a "
                                "variable with push arguments; it cannot be judged",
                                "call git by name", [(cmd.raw.strip().lower(),)]))
    elif cmd.name == "git":
        judge_git(cmd, text_env, findings, depth)
    elif cmd.name in ("gh", "hub"):
        judge_gh(cmd, findings, text_env, depth)
    elif cmd.name in HTTP_CLIENTS:
        judge_http(cmd, findings)
    elif cmd.name not in PRINTERS and cmd.name not in KNOWN_SHAPES \
            and re.search(r"\bgit\b", raw_low) and re.search(r"\bpush\b", raw_low):
        findings.append(Finding("unknown-shape", f"`{cmd.raw.strip()}` reads as a git push behind "
                                f"`{cmd.name}`, which this guard does not understand",
                                "run git push directly", [(cmd.raw.strip().lower(),)]))
    elif cmd.name not in PRINTERS:
        # Belt for launchers whose command is a quoted string (Start-Process git -ArgumentList '...').
        raw = cmd.raw.lower()
        if re.search(r"\bgit\b", raw) and re.search(r"\bpush\b", raw) and "--no-veri" in raw:
            findings.append(Finding("push-no-verify", f"`{cmd.raw.strip()}` launches a git push "
                                    "with --no-verify", "push without --no-verify",
                                    [("--no-verify",)]))
        if re.search(r"\bgit\b", raw) and re.search(r"(?:-c\s*['\"]?|--config-env[= ])core\.hookspath",
                                                     raw):
            findings.append(Finding("hookspath-override", f"`{cmd.raw.strip()}` launches git with "
                                    "a core.hooksPath override", "drop the override",
                                    [("core.hookspath",)]))


def _writes_remote(cmd: Cmd) -> bool:
    """git remote add/set-url/rename, or a git config write of remote.* / url.*."""
    if cmd.name != "git":
        return False
    words = [w for w in cmd.argv[1:]]
    index = 0
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    sub, args = (words[index], words[index + 1:]) if index < len(words) else ("", [])
    if sub == "remote":
        return bool(args) and args[0] in ("add", "set-url", "rename")
    if sub == "config":
        if any(a.lower() in CONFIG_READS for a in args):
            return False
        keys = [a.lower() for a in args if not a.startswith("-")]
        explicit = keys[:1] in (["set"], ["unset"])
        keys = keys[1:] if explicit else keys
        if not keys or not keys[0].startswith(("remote.", "url.")):
            return False
        unsets = any(a in ("--unset", "--unset-all", "--add", "--replace-all", "--remove-section",
                           "--rename-section") for a in args)
        return explicit or unsets or len(keys) > 1
    return False


def evaluate(command: str, cwd: str | None, shell: str = "bash") -> list[Finding]:
    plain = executable_text(normalise(command, shell))
    text_env: dict[str, str] = {
        m.group(next(i for i in range(1, 6) if m.group(i))).upper(): ""
        for m in TEXT_ENV.finditer(plain)}
    for m in ENV_STATEMENT.finditer(plain):
        text_env[m.group(1).upper()] = next((g for g in m.groups()[1:] if g is not None), "")
    findings: list[Finding] = []
    commands = list(iter_commands(command, cwd, shell=shell))
    if any(_writes_remote(c) for c in commands):
        text_env[REMOTE_WRITE] = "1"
    for cmd in commands:
        judge(cmd, text_env, findings)
    unique: dict[tuple[str, str], Finding] = {}
    for item in findings:
        unique.setdefault((item.route, item.detail), item)
    return list(unique.values())


# ---------------------------------------------------------------- approval

def _owner_prompt(event: dict, command: str) -> str | None:
    transcript = str(event.get("transcript_path") or "")
    if not transcript or Path(transcript).name.lower() in command.lower():
        return None
    spec = importlib.util.spec_from_file_location(
        "_hcg_for_publish", Path(__file__).with_name("human-confirmation-guard.py"))
    hcg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hcg)
    request = hcg.owner_request(transcript)
    return request[0] if request else None


def approves(prompt: str | None, finding: Finding) -> bool:
    if not prompt:
        return False
    words = FLAG_TOKEN.sub(" ", prompt)  # `--no-verify` is the action's name, not a "no"
    if NOT_GO.search(words) or not GO.search(words):
        return False
    low = prompt.lower()
    return all(any(alt.lower() in low for alt in group) for group in finding.needles)


def unapproved(findings: list[Finding], prompt: str | None) -> list[Finding]:
    return [f for f in findings if not approves(prompt, f)]


def _audit(event: dict, prompt: str, command: str, findings: list[Finding]) -> bool:
    try:
        APPROVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with APPROVAL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": _dt.datetime.now().isoformat(timespec="seconds"),
                "session": event.get("session_id"), "routes": [f.route for f in findings],
                "request": prompt[:300], "command": command[:500]}, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def _message(blocked: list[Finding]) -> str:
    lines = ["Publishing route that skips the pre-push leak scan (owner rule: nothing private may "
             "reach a PUBLIC repo; when in doubt, block)."]
    for item in blocked:
        lines.append(f"- [{item.route}] {item.detail}.\n  Fix: {item.fix}.")
        names = " + ".join("/".join(group) for group in item.needles)
        lines.append(f"  Owner approval: her latest chat message says to go ahead and names: {names}.")
    lines.append("Command markers and env flags are not approval.")
    return "\n".join(lines)


def main() -> None:
    event = read_event()
    if event.get("tool_name") not in ("Bash", "PowerShell"):
        allow()
    command = bash_command(event.get("tool_input", {}) or {})
    if not command or not (MENTIONS.search(command) or MAYBE.search(command)):
        allow()
    try:
        shell = "powershell" if event.get("tool_name") == "PowerShell" else "bash"
        findings = evaluate(command, str(event.get("cwd") or os.getcwd()), shell)
        if not findings:
            allow()
        prompt = _owner_prompt(event, command)
        blocked = unapproved(findings, prompt)
    except Exception as exc:  # fail closed when the command names git/gh; else note and pass
        if not MENTIONS.search(command):
            log("WARN", HOOK, "error-pass", type(exc).__name__, command)
            allow()
        log("BLOCK", HOOK, "error", type(exc).__name__, command)
        block(f"publish-bypass-guard could not judge this git/gh command ({type(exc).__name__}: "
              f"{exc}); blocked rather than passed unchecked.")
        return
    if blocked:
        log("BLOCK", HOOK, "deny", ",".join(f.route for f in blocked), command)
        block(_message(blocked))
    if not _audit(event, prompt or "", command, findings):
        block("publish-bypass-guard: owner approval found but the audit record could not be "
              f"written to {APPROVAL_LOG}; blocked.")
    log("WARN", HOOK, "owner-approved", ",".join(f.route for f in findings), command)
    allow()


if __name__ == "__main__":
    main()
