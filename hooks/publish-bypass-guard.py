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
| git-config-env     | `GIT_CONFIG*` / `GIT_EXTERNAL_DIFF` / `GIT_EXEC_PATH` set for a push            |
| send-pack          | `git send-pack` (plumbing push, never runs pre-push)                           |
| local-hooks        | push from a repo whose effective hooks folder is not the global one and has no |
|                    | pre-push that chains to the scan, unless the push target is known PRIVATE      |
| unknown-repo       | push whose working directory cannot be resolved (`cd $X && git push`)          |
| repo-public        | `gh repo edit --visibility public`, `gh repo create --public`                  |
| gist-public        | `gh gist create --public|-p`, `gh gist edit --add`                             |
| api-write          | `gh api` PUT/POST/PATCH on `repos/*/*/contents|git/*`, graphql commit mutations,|
|                    | PATCH `repos/*/*` that sets visibility=public / private=false                  |
| release-public     | `gh release create|upload` on a repo that is PUBLIC or of unknown visibility    |

`git push -n` is `--dry-run` for push (it sends nothing), so it is not a hook skip and passes.

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
PUSH_ENV = re.compile(r"^(?:GIT_CONFIG\w*|GIT_EXTERNAL_DIFF|GIT_EXEC_PATH)$", re.IGNORECASE)
_ENV_NAME = r"(GIT_CONFIG\w*|GIT_EXTERNAL_DIFF|GIT_EXEC_PATH)"
# Environment set by a separate statement of the same command line, Bash or PowerShell.
TEXT_ENV = re.compile(
    r"\$env:" + _ENV_NAME + r"\s*=|\bexport\s+" + _ENV_NAME + r"=|\bset\s+" + _ENV_NAME + r"=|"
    r"Environment\]::SetEnvironmentVariable\(\s*['\"]" + _ENV_NAME + r"|"
    r"(?:Set-Item|New-Item|si|ni)\s+(?:-Path\s+)?['\"]?env:" + _ENV_NAME,
    re.IGNORECASE)
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
# Commands whose arguments are data, never a command: their quoted arguments are not re-judged.
PRINTERS = {"echo", "printf", "write-output", "write-host", "grep", "egrep", "fgrep", "rg", "ag",
            "findstr", "select-string", "sls", "cat", "type", "less", "more", "head", "tail", "wc"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
PWSH = {"powershell", "pwsh"}
CD = {"cd", "set-location", "sl", "chdir", "pushd", "push-location"}
KEYWORDS = {"(", "{", "!", "then", "do", "else", "elif", "if", "while", "until", "time", "&", ".",
            "call", "--%"}
WRAPPERS = {"sudo", "nohup", "command", "builtin", "exec", "nice", "ionice", "stdbuf", "winpty",
            "time", "caffeinate", "doas"}
VALUE_WRAPPERS = {"timeout"}  # first positional is a duration
WRAPPER_VALUED = {"-I", "-n", "-P", "-L", "-d", "-u", "-g", "-E", "-s"}
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
    r"approve|allow|go\s+ahead|do\s+it|proceed|\byes\b|\bда\b|\bок\b|\bok\b|\bokay\b",
    re.IGNORECASE)
NOT_GO = re.compile(
    r"\bне\b|\bнельзя\b|\bнет\b|\bзапрещ|\bпогоди|\bподожди|\bdon'?t\b|\bdo\s+not\b|\bnever\b|"
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


def _resolve_dir(base: str | None, target: str) -> str | None:
    if base is None or re.search(r"[$`%]", target):
        return None
    if target.startswith("~") and len(target) > 1 and target[1] not in "/\\":
        return None  # ~user
    target = os.path.expanduser(target)
    path = Path(target) if os.path.isabs(target) else Path(base) / target
    return str(path)


def iter_commands(text: str, cwd: str | None, remote: bool = False, depth: int = 0):
    """Every simple command the text would run, with its env prefix and working directory."""
    if depth > 6 or not text:
        return
    current = cwd
    for line in executable_text(text).splitlines():
        for segment in _split_segments(line)[0::2]:
            if not segment.strip():
                continue
            for inner in _substitutions(segment):
                yield from iter_commands(inner, current, remote, depth + 1)
            tokens = tokenize(segment)
            env: dict[str, str] = {}
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
                    needs_value = name in VALUE_WRAPPERS
                    while tokens:
                        word = tokens[0]
                        if word.startswith("-"):
                            tokens = tokens[1:]
                            if name in ("xargs", "sudo") and word in WRAPPER_VALUED and tokens:
                                tokens = tokens[1:]
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
            name = _command_name(tokens[0])
            argv = tokens
            if name in CD:
                args = [t for t in argv[1:] if not t.startswith("-")]
                current = _resolve_dir(current, args[0]) if args else str(Path.home())
                continue
            yield Cmd(name, argv, env, current, remote, segment)
            if name in PRINTERS:
                continue
            if name in SHELLS and "-c" in argv:
                at = argv.index("-c")
                if at + 1 < len(argv):
                    yield from iter_commands(argv[at + 1], current, remote, depth + 1)
                continue
            if name in PWSH:
                for flag_at, token in enumerate(argv):
                    if token.lower() in ("-command", "-c"):
                        yield from iter_commands(" ".join(argv[flag_at + 1:]), current, remote,
                                                 depth + 1)
                        break
                continue
            if name == "cmd":
                for flag_at, token in enumerate(argv):
                    if token.lower() in ("/c", "/k"):
                        yield from iter_commands(" ".join(argv[flag_at + 1:]), current, remote,
                                                 depth + 1)
                        break
                continue
            is_remote = remote or name in ("ssh", "plink")
            for token in argv[1:]:
                if re.search(r"\s", token):
                    yield from iter_commands(token, None if is_remote else current, is_remote,
                                             depth + 1)


# ---------------------------------------------------------------- git / gh probes

def _run(args: list[str], cwd: str | None, timeout: int = GIT_TIMEOUT) -> str | None:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, check=False)
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


def _hook_chains_to_scan(path: Path) -> bool:
    """The pre-push file exists, is a script, and (outside comments) calls the scan or the global hook."""
    try:
        if not path.is_file():
            return False
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    code = code.replace("\\", "/").lower()
    return bool(re.search(
        r"pre-push-public-repo-scan|scripts/git-hooks/pre-push|"
        r"config\s+--global\s+(?:--get\s+)?core\.hookspath", code))


@dataclass
class Repo:
    top: str | None
    hooks: str | None
    git: list[str]

    def label(self) -> tuple[str, ...]:
        names = []
        if self.top:
            names.append(Path(self.top).name)
        return tuple(names)


def open_repo(cwd: str, location: list[str]) -> Repo:
    git = ["git", "-C", cwd, *location]
    top = _run([*git, "rev-parse", "--show-toplevel"], None) or _run([*git, "rev-parse",
                                                                      "--absolute-git-dir"], None)
    hooks = _run([*git, "rev-parse", "--path-format=absolute", "--git-path", "hooks"], None)
    return Repo(top, hooks, git)


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
                        None)
        remote = upstream.split("/", 1)[0] if upstream else "origin"
    return slug_from_url(_run([*repo.git, "remote", "get-url", "--push", remote], None))


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


def judge_git(cmd: Cmd, text_env: set[str], findings: list[Finding], depth: int = 0) -> None:
    argv = cmd.argv
    location: list[str] = []
    config: list[str] = []
    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        token = argv[index]
        nxt = argv[index + 1] if index + 1 < len(argv) else ""
        if token == "-C":
            location += ["-C", nxt]
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
                for inner in iter_commands(expansion[1:] + " " + " ".join(args), cmd.cwd,
                                           cmd.remote, 1):
                    judge(inner, text_env, findings, depth + 1)
                return
            expanded = Cmd(cmd.name, ["git", *argv[1:index], *tokenize(expansion), *args],
                           cmd.env, cmd.cwd, cmd.remote, cmd.raw)
            judge_git(expanded, text_env, findings, depth + 1)
            return

    if sub not in ("push", "send-pack"):
        return

    env_names = {name for name in cmd.env if PUSH_ENV.match(name)} | text_env
    for name in ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"):
        inherited = os.environ.get(name, "")
        if inherited and ("hookspath" in inherited.lower() or any(
                "hookspath" in v.lower() for k, v in os.environ.items()
                if k.upper().startswith("GIT_CONFIG_VALUE") or k.upper().startswith("GIT_CONFIG_KEY"))):
            env_names.add(name + " (inherited)")

    repo: Repo | None = None
    slug: str | None = None
    if cmd.cwd and not cmd.remote and Path(cmd.cwd).is_dir():
        repo = open_repo(cmd.cwd, location)
        if repo.top:
            slug = push_target_slug(repo, args)
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
    if cmd.cwd is None:
        findings.append(Finding(
            "unknown-repo", f"cannot resolve which repository `{cmd.raw.strip()}` pushes from "
            "(the working directory comes from a variable or substitution)",
            "cd to a literal path before the push", [(cmd.raw.strip().lower(),)]))
        return
    if repo is None or not repo.top or not repo.hooks:
        return  # not a repository: git itself refuses the push
    global_hooks = _run(["git", "config", "--global", "--get", "core.hooksPath"], None)
    if global_hooks and _norm(repo.hooks) == _norm(global_hooks):
        if _hook_chains_to_scan(Path(os.path.expanduser(global_hooks)) / "pre-push"):
            return
    elif _hook_chains_to_scan(Path(repo.hooks) / "pre-push"):
        return
    visibility = repo_visibility(slug) if slug else None
    if visibility in ("PRIVATE", "INTERNAL"):
        return
    hooks_dir = repo.hooks
    findings.append(Finding(
        "local-hooks",
        f"repo {repo.top} uses hooks folder {hooks_dir} (global: {global_hooks or 'unset'}) and "
        f"its pre-push does not run the public leak scan; push target "
        f"{slug or 'unresolved'} is {visibility or 'of unknown visibility'}",
        f"either `git -C \"{repo.top}\" config --unset core.hooksPath`, or add "
        f"{Path(hooks_dir) / 'pre-push'} that ends with "
        f"`exec \"{global_hooks or '<global hooksPath>'}/pre-push\" \"$@\"`",
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


def judge_gh(cmd: Cmd, findings: list[Finding]) -> None:
    argv = cmd.argv
    sub = argv[1].lower() if len(argv) > 1 else ""
    verb = argv[2].lower() if len(argv) > 2 else ""
    args = argv[3:]
    lowered = [a.lower() for a in args]
    repo_flag = _opt_value(args, ("-R", "--repo"))
    local_cwd = None if cmd.remote else cmd.cwd

    if sub == "repo" and verb == "edit":
        value = _opt_value(lowered, ("--visibility",))
        if value == "public":
            pos = _positionals(args, {"--visibility", "--description", "-d", "--homepage", "-h",
                                      "--default-branch", "--add-topic", "--remove-topic"})
            slug = pos[0] if pos and "/" in pos[0] else current_slug(local_cwd, None)
            findings.append(Finding("repo-public", f"`gh repo edit` makes {slug or 'the current repo'}"
                                    " PUBLIC; everything already pushed becomes readable without "
                                    "any scan", "keep the repo private",
                                    [PUBLIC, _repo_needle(slug, None) if slug else
                                     (Path(local_cwd).name if local_cwd else "<repo>",)]))
    elif sub == "repo" and verb == "create" and "--public" in lowered:
        pos = _positionals(args, {"--description", "-d", "--homepage", "-h", "--source", "-s",
                                  "--remote", "-r", "--team", "-t", "--template", "-p",
                                  "--gitignore", "-g", "--license", "-l"})
        name = pos[0] if pos else (Path(local_cwd).name if local_cwd else "<new repo>")
        findings.append(Finding("repo-public", f"`gh repo create --public` creates {name} as a "
                                "PUBLIC repo (with --push its content is published unscanned)",
                                "create it with --private", [PUBLIC, (name, name.split("/")[-1])]))
    elif sub == "gist" and verb == "create" and ("--public" in lowered or "-p" in lowered):
        findings.append(Finding("gist-public", "`gh gist create --public` publishes files with no "
                                "scan", "create a secret gist or a private repo",
                                [("gist", "гист"), PUBLIC]))
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
        path = re.sub(r"^https?://[^/]+/(?:api/v3/)?", "", path).lstrip("/").split("?", 1)[0]
        text = cmd.raw.lower()
        if path.lower() == "graphql":
            if "createcommitonbranch" in text or any(a.startswith("--input") for a in api_args):
                findings.append(Finding("api-write", "`gh api graphql` commit mutation (or a "
                                        "query read from --input) writes repo content with no scan",
                                        "commit and `git push` instead",
                                        [("graphql",), ("createcommitonbranch", "--input")]))
        elif method in ("PUT", "POST", "PATCH"):
            if re.match(r"repos/[^/]+/[^/]+/(?:contents|git)(?:/|$)", path, re.IGNORECASE):
                findings.append(Finding("api-write", f"`gh api -X {method} {path}` writes repo "
                                        "content directly, past the pre-push scan",
                                        "commit and `git push` instead", [(path.lower(),)]))
            elif method == "PATCH" and re.fullmatch(r"repos/[^/]+/[^/]+/?", path, re.IGNORECASE) \
                    and (re.search(r"visibility\s*=\s*public|private\s*=\s*false", text)
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


def judge(cmd: Cmd, text_env: set[str], findings: list[Finding], depth: int = 0) -> None:
    if cmd.name == "git":
        judge_git(cmd, text_env, findings, depth)
    elif cmd.name == "gh":
        judge_gh(cmd, findings)
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


def evaluate(command: str, cwd: str | None) -> list[Finding]:
    text_env = {m.group(next(i for i in range(1, 6) if m.group(i))).upper()
                for m in TEXT_ENV.finditer(executable_text(command))}
    findings: list[Finding] = []
    for cmd in iter_commands(command, cwd):
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
    if not command or not MENTIONS.search(command):
        allow()
    try:
        findings = evaluate(command, str(event.get("cwd") or os.getcwd()))
        if not findings:
            allow()
        prompt = _owner_prompt(event, command)
        blocked = unapproved(findings, prompt)
    except Exception as exc:  # fail closed: the command mentions git/gh and was not judged
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
