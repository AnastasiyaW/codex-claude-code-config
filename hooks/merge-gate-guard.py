#!/usr/bin/env python3
"""PreToolUse (Bash|PowerShell): nothing lands on the default branch except through safe_merge.

The rule: a pull request reaches master/main only when its required checks are green on
the exact head commit AND that head already contains the current base tip, so the merged
tree is the tree CI tested. On a private repository of a free GitHub plan a ruleset or a
merge queue cannot enforce this (the rulesets API answers 403 "Upgrade to GitHub Pro"),
so the enforcement lives here, in the agent harness, for every repository an agent
touches.

  blocked : gh pr merge (any flags, --auto included); gh repo sync <repo>
            gh api / curl / Invoke-RestMethod WRITES that merge or move the default branch:
              pulls/N/merge, /merges, git/refs(/heads/master|main), contents/ without a
              feature branch, default_branch changes, and the GraphQL mutations
              mergePullRequest, enablePullRequestAutoMerge, enqueuePullRequest,
              createCommitOnBranch, mergeBranch, updateRef(s)
            git push / git send-pack whose destination is master, main or the remote's
              default branch: explicit refspecs (master, HEAD:master, +master, heads/main,
              :main), --all / --branches / --mirror, --delete of a protected name, glob
              refspecs, a destination that cannot be resolved (unknown variable,
              substitution), and a refspec-less push whose target is protected (current
              branch, its upstream, push.default=matching, remote.<name>.push; inline -c
              values included)
  allowed : python <...>/safe_merge.py <owner/repo> <pr>  (the sanctioned path),
            feature-branch pushes, reads (GET) of the same endpoints, gh pr update-branch,
            --help, text that only mentions these commands (commit messages, PR bodies,
            heredoc bodies fed to cat, echo not piped into a shell, grep patterns)

Why the sanctioned path needs no token: a PreToolUse hook sees only the commands the agent
asks the harness to run. safe_merge.py starts `gh pr merge` as its own child process, which
never passes through this hook. So the hook does not have to recognise safe_merge; it only
has to recognise a merge or a protected push typed anywhere in an agent command. There is
deliberately no bypass marker and no env override: an emergency merge is done by the owner
in her own terminal or in the GitHub UI, where agent hooks do not apply.

Residual risk, stated plainly: a script FILE written first and run later (bash merge.sh,
python merge.py) is not opened; a GraphQL query read from a file (-F query=@q.graphql) is
not read; programs that merge without gh/git/curl (a custom HTTP client, hub, git town) are
not recognised; pushes made by a process the agent started earlier in the background are
invisible. The hook catches accidents and the habitual one-liner, not deliberate evasion.
An analysis error on a command that mentions merge or push blocks (fail-closed); any other
error allows, so a parser bug cannot freeze all shell work.

Self-test: python merge-gate-guard.py --self-test
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import safety_common as sc  # noqa: E402

HOOK = "merge-gate-guard"
ALWAYS_PROTECTED = {"master", "main"}
MAX_DEPTH = 4
SAFE_MERGE_HINT = "python ~/.claude/claude-code-config/scripts/safe_merge.py <owner/repo> <pr>"

# A command mentioning none of these cannot merge or push; skip it cheaply.
PREFILTER = re.compile(r"merge|push|refs|updateref|enqueue|createcommit|graphql|contents|"
                       r"default_branch|sync|\bgh\b|\bgit\b|gh\.exe|git\.exe|@", re.I)
FAILCLOSED = re.compile(r"merge|push|refs/heads|updateref|enqueue|createcommit", re.I)
GRAPHQL_MUTATIONS = re.compile(r"\b(?:mergePullRequest|enablePullRequestAutoMerge|enqueuePullRequest"
                               r"|createCommitOnBranch|mergeBranch|updateRefs?)\b", re.I)
REST_MERGE = re.compile(r"(?:pulls/[^/\s]+/merge\b|/merges\b|git/refs/heads/(?:master|main)\b"
                        r"|/branches/(?:master|main)/rename\b)", re.I)
CURRENT_BRANCH = re.compile(r"(?:\$\(|`)\s*git\s+(?:branch\s+--show-current|rev-parse\s+--abbrev-ref\s+HEAD"
                            r"|symbolic-ref\s+(?:-q\s+)?--short\s+(?:-q\s+)?HEAD)\s*(?:\)|`)", re.I)
UNRESOLVED = re.compile(r"\$\{[^}]*\}?|\$\((?:[^()]|\([^()]*\))*\)?|`[^`]*`?|\$\w*")
REST_WRITE_ONLY = re.compile(r"/merge-upstream\b", re.I)
REST_RENAME = re.compile(r"/branches/[^/\s]+/rename\b", re.I)
REST_REFS = re.compile(r"git/refs/?(?:$|\?)", re.I)
REST_CONTENTS = re.compile(r"/contents/", re.I)
REST_REPO = re.compile(r"repos/[^/\s]+/[^/\s?]+/?(?:$|\?)", re.I)
WRITE_METHODS = {"put", "post", "patch", "delete"}

_STRIP = "`$(){}[]&@'\"; "
WRAPPERS = {"sudo", "env", "nohup", "time", "command", "builtin", "exec", "nice", "ionice",
            "stdbuf", "doas", "&", ".", "call", "start-process", "saps", "start", "xargs",
            "watch", "strace", "chronic"}
READERS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "findstr", "select-string", "sls"}
ECHOES = {"echo", "printf", "write-host", "write-output", "write", "print"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd", "iex",
          "invoke-expression", "python", "python3", "py", "node", "perl", "ruby", "source",
          ".", "eval", "ssh", "xargs"}
CD_COMMANDS = {"cd", "pushd", "set-location", "sl", "chdir", "push-location"}
CURL_LIKE = {"curl", "wget", "http", "https", "xh", "invoke-restmethod", "irm",
             "invoke-webrequest", "iwr"}
CODE_FLAGS = {"-c", "-e", "--eval", "-command", "/c", "/k", "-p", "--print", "-encodedcommand"}
MESSAGE_FLAGS = {"-m", "--message", "--body", "-b", "--title", "-t", "--subject", "--notes"}
GH_FLAGS_WITH_VALUE = {"-R", "--repo", "--hostname", "--branch", "-b", "--source"}
GH_KNOWN = {"auth", "browse", "codespace", "cs", "gist", "issue", "org", "pr", "project",
            "release", "repo", "cache", "run", "workflow", "alias", "api", "attestation",
            "completion", "config", "extension", "ext", "gpg-key", "label", "ruleset",
            "search", "secret", "ssh-key", "status", "variable", "copilot", "agent-task",
            "preview", "help", "version", "accessibility"}
GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                         "--exec-path", "--config-env", "--super-prefix"}
GIT_KNOWN = {"add", "commit", "status", "log", "diff", "fetch", "pull", "merge", "rebase",
             "checkout", "switch", "branch", "tag", "show", "reset", "restore", "stash",
             "remote", "config", "worktree", "rev-parse", "rev-list", "cherry-pick",
             "revert", "clone", "init", "grep", "blame", "ls-files", "ls-remote",
             "symbolic-ref", "for-each-ref", "cat-file", "describe", "notes", "submodule",
             "clean", "mv", "rm", "apply", "am", "format-patch", "bisect", "gc", "reflog",
             "shortlog", "update-index", "merge-base", "hash-object", "count-objects", "help"}
PUSH_FLAGS_WITH_VALUE = {"--repo", "-o", "--push-option", "--receive-pack", "--exec",
                         "--signed", "--recurse-submodules"}
VAR_REF = re.compile(r"\$\{(\w+)\}|\$env:(\w+)|\$(\w+)|@(\w+)", re.I)


# ---------------------------------------------------------------------------
# Tokenizer: quote-aware; one record per simple command:
#   {"tokens": [...], "sep": separator that follows, "heredocs": [body, ...]}
# ---------------------------------------------------------------------------

def _capture(text: str, start: int) -> int:
    """Index just past the bracket that closes the one after the sigil at text[start]
    ($( @( ${ ), quotes inside respected; len(text) when it never closes."""
    i = start + 1
    open_ch = text[i]
    close_ch = ")" if open_ch == "(" else "}"
    depth = 0
    quote = ""
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def split_commands(text: str, powershell: bool = False) -> list[dict]:
    """Split shell text into simple commands at unquoted ; & | newline and subshell parens.

    Bash: backslash escapes outside single quotes; $(...), `...` and ${...} stay inside
    their word (scanned later as their own commands); <<DELIM heredoc bodies are kept apart.
    PowerShell: the backtick is the escape character; $(...) and @(...) stay inside the word.
    `#` at the start of a word starts a comment that runs to the end of the line.
    """
    segments: list[dict] = []
    seg: dict = {"tokens": [], "sep": None, "heredocs": []}
    word: list[str] = []
    in_word = False
    quote = ""
    escape = "`" if powershell else "\\"
    pending: list[tuple[str, bool, dict]] = []
    i = 0
    n = len(text)

    def end_word() -> None:
        nonlocal word, in_word
        tok = "".join(word) if in_word else None
        word = []
        in_word = False
        if tok in ("{", "}"):
            end_segment(None)
        elif tok is not None:
            seg["tokens"].append(tok)

    def end_segment(sep: str | None) -> None:
        nonlocal seg
        if in_word:
            end_word()
        if seg["tokens"] or seg["heredocs"]:
            seg["sep"] = sep
            segments.append(seg)
        elif sep and segments:
            segments[-1]["sep"] = segments[-1]["sep"] or sep
        seg = {"tokens": [], "sep": None, "heredocs": []}

    while i < n:
        ch = text[i]
        if quote == "'":
            if ch == "'":
                if powershell and i + 1 < n and text[i + 1] == "'":
                    word.append("'")
                    i += 2
                    continue
                quote = ""
            else:
                word.append(ch)
            i += 1
            continue
        if quote == '"':
            if ch == escape and i + 1 < n:
                word.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                quote = ""
            else:
                word.append(ch)
            i += 1
            continue
        if ch == escape and i + 1 < n:
            if text[i + 1] == "\n":
                i += 2
                continue
            word.append(text[i + 1])
            in_word = True
            i += 2
            continue
        if ch in "'\"":
            quote = ch
            in_word = True
            i += 1
            continue
        if ch in "$@" and i + 1 < n and text[i + 1] in "({" and (ch == "$" or powershell):
            end = _capture(text, i)
            word.append(text[i:end])
            in_word = True
            i = end
            continue
        if ch == "`" and not powershell:
            end = text.find("`", i + 1) + 1 or n
            word.append(text[i:end])
            in_word = True
            i = end
            continue
        if text.startswith("<<<", i):
            word.append("<<<")
            in_word = True
            i += 3
            continue
        if ch == "<" and not powershell and text.startswith("<<", i):
            j = i + 2
            strip_tabs = j < n and text[j] == "-"
            j += 1 if strip_tabs else 0
            while j < n and text[j] in " \t":
                j += 1
            m = re.match(r"(['\"]?)([A-Za-z0-9_.-]+)\1", text[j:])
            if m:
                end_word()
                pending.append((m.group(2), strip_tabs, seg))
                i = j + m.end()
                continue
        if ch in " \t\r":
            end_word()
            i += 1
            continue
        if ch == "#" and not in_word:
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "\n":
            end_segment("\n")
            i += 1
            for delim, strip_tabs, owner in pending:
                body: list[str] = []
                consumed = 0
                for line in text[i:].split("\n"):
                    consumed += len(line) + 1
                    if (line.lstrip("\t") if strip_tabs else line).rstrip("\r") == delim:
                        break
                    body.append(line)
                i = min(n, i + consumed)
                owner["heredocs"].append("\n".join(body))
            pending = []
            continue
        if ch in ";&|":
            op = text[i:i + 2] if text[i:i + 2] in ("&&", "||") else ch
            end_segment(op)
            i += len(op)
            continue
        if ch == ")" or (ch == "(" and not in_word):
            end_segment(ch)
            i += 1
            continue
        word.append(ch)
        in_word = True
        i += 1
    end_segment(None)
    for delim, _strip, owner in pending:
        owner["heredocs"].append("")
    return segments


def _base(token: str) -> str:
    name = token.strip(_STRIP).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _variable_like(token: str) -> bool:
    return token.startswith(("$", "%", "@")) or token.endswith("%")


def _primary_index(tokens: list[str]) -> int:
    """Index of the program a simple command runs, after assignments and wrappers."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        base = _base(tok)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            i += 1
            continue
        if base == "timeout":
            # timeout [-k DURATION] [-s SIGNAL] [--flag] DURATION COMMAND
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 2 if tokens[i] in ("-k", "-s") else 1
            i += 1
            continue
        if base in WRAPPERS or (tok.startswith("-") and i > 0):
            i += 1
            continue
        return i
    return len(tokens)


# ---------------------------------------------------------------------------
# Context: repository directory, remote host, variables set earlier in the command.
# ---------------------------------------------------------------------------

class Ctx:
    def __init__(self, cwd: Path | None, remote: bool = False, depth: int = 0,
                 powershell: bool = False, variables: dict | None = None) -> None:
        self.cwd = cwd
        self.remote = remote
        self.depth = depth
        self.powershell = powershell
        self.vars: dict[str, str] = dict(variables or {})
        self.head_moved = False  # a checkout/switch earlier in the command: HEAD on disk is stale
        self.branch: str | None = None  # ... unless it named the branch it switched to

    def child(self, **kw) -> "Ctx":
        c = Ctx(self.cwd, self.remote, self.depth + 1, self.powershell, self.vars)
        c.head_moved, c.branch = self.head_moved, self.branch
        for k, v in kw.items():
            setattr(c, k, v)
        return c


def expand(token: str, ctx: Ctx) -> tuple[str, bool]:
    """Substitute variables known from this command or the environment.

    Returns (text, resolved); resolved is False when a reference or substitution remains."""
    if "$(" in token or "`" in token or "@(" in token:
        return token, False

    def sub(m: re.Match) -> str:
        name = next(g for g in m.groups() if g)
        if name in ctx.vars:
            return ctx.vars[name]
        if name in os.environ and not ctx.remote:
            return os.environ[name]
        return m.group(0)

    text = VAR_REF.sub(sub, token)
    # an unknown name, ${x:-y}, $1, $$ and friends: still a reference after substitution
    return text, "$" not in text


def _assignment(tokens: list[str], ctx: Ctx) -> bool:
    """Record NAME=value (bash) or $name = value (PowerShell); True if the segment was one."""
    if tokens and tokens[0].startswith("$"):
        name, eq, value = " ".join(tokens).partition("=")
        m = re.fullmatch(r"\$(?:env:)?(\w+)\s*", name, re.I)
        if eq and m:
            value = " ".join(re.sub(r"[@()'\",]", " ", value).split())
            # $b = git branch --show-current: the value is the current branch, as $(...) is
            ctx.vars[m.group(1)] = f"$({value})" if CURRENT_BRANCH.fullmatch(f"$({value})") else value
            return True
    if tokens and all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t) for t in tokens):
        for t in tokens:
            name, _, value = t.partition("=")
            ctx.vars[name] = expand(value, ctx)[0]
        return True
    return False


def _git(cwd: Path | None, *args: str) -> str | None:
    if cwd is None or not cwd.is_dir():
        return None
    try:
        out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _short(ref: str) -> str:
    ref = ref.strip().lstrip("+").lower()
    for prefix in ("refs/heads/", "heads/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


# ---------------------------------------------------------------------------
# Detectors. Each returns a finding string or None.
# ---------------------------------------------------------------------------

def _split_args(args: list[str]) -> list[str]:
    out: list[str] = []
    for a in args:
        for part in re.split(r"[\s,]+", a):
            part = part.strip("@()'\"")
            if part:
                out.append(part)
    return out


def _gh_aliases() -> dict[str, str]:
    """gh aliases from the gh config file (GH_CONFIG_DIR, XDG, APPDATA)."""
    candidates = []
    if os.environ.get("GH_CONFIG_DIR"):
        candidates.append(Path(os.environ["GH_CONFIG_DIR"]) / "config.yml")
    if os.environ.get("XDG_CONFIG_HOME"):
        candidates.append(Path(os.environ["XDG_CONFIG_HOME"]) / "gh" / "config.yml")
    if os.environ.get("APPDATA"):
        candidates.append(Path(os.environ["APPDATA"]) / "GitHub CLI" / "config.yml")
    candidates.append(Path.home() / ".config" / "gh" / "config.yml")
    aliases: dict[str, str] = {}
    for path in candidates:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        inside = False
        for line in lines:
            if re.match(r"^aliases:\s*$", line):
                inside = True
                continue
            if inside:
                if line and not line[0].isspace():
                    inside = False
                    continue
                m = re.match(r"^\s+([^:#\s]+):\s*(.+?)\s*$", line)
                if m:
                    aliases[m.group(1).lower()] = m.group(2).strip("'\"")
    return aliases


def _is_write(args: list[str]) -> bool:
    """True when an HTTP call (gh api / curl / Invoke-RestMethod) writes."""
    low = [a.lower() for a in args]
    for idx, a in enumerate(low):
        m = re.match(r"^(?:-x|--method|--request|-method)(?:=|:)?(\w*)$", a)
        if m:
            method = m.group(1) or (low[idx + 1] if idx + 1 < len(low) else "")
            if method.strip("'\"") in WRITE_METHODS:
                return True
            if method == "get":
                return False
    data_flags = {"-f", "-F", "--field", "--raw-field", "--input", "-d", "--data",
                  "--data-raw", "--data-binary", "--data-urlencode", "--json", "--form",
                  "-T", "--upload-file", "-body", "-infile"}
    return any(a in data_flags or a.lower() in data_flags for a in args)


def _http_finding(args: list[str]) -> str | None:
    joined = " ".join(args)
    if GRAPHQL_MUTATIONS.search(joined):
        return "GitHub GraphQL mutation that merges or moves a branch"
    fields = {}
    for idx, a in enumerate(args):
        if a in ("-f", "-F", "--field", "--raw-field") and idx + 1 < len(args):
            k, _, v = args[idx + 1].partition("=")
            fields[k.lower()] = v.lower()
    if "graphql" in [a.lower() for a in args] and (
            "--input" in args or any(s in a for a in args for s in ("$(", "`", "${"))
            or any(v.startswith("@")
                                     # $owner inside a query is a GraphQL variable; a bare
                                     # $QUERY with no braces is a shell variable
                                     or (v.startswith("$") and "{" not in v) for v in fields.values())):
        return "GitHub GraphQL query read from a file or substitution (cannot be checked)"
    if not _is_write(args):
        return None

    def protected(value: str) -> bool:
        # an unresolved variable could name the default branch
        return _short(value) in ALWAYS_PROTECTED or "$" in value or "`" in value

    for a in args:
        if REST_MERGE.search(a) or REST_WRITE_ONLY.search(a):
            return "HTTP write to a GitHub merge/ref endpoint"
        if REST_RENAME.search(a) and protected(fields.get("new_name", "")):
            return "HTTP write renaming a branch to the default branch"
        if REST_REFS.search(a) and protected(fields.get("ref", "")):
            return "HTTP write creating a protected ref"
        if REST_CONTENTS.search(a) and (protected(fields.get("branch", "")) or "branch" not in fields):
            return "HTTP contents write onto the default branch"
        if REST_REPO.search(a) and "default_branch" in fields:
            return "HTTP write changing the default branch"
    return None


def gh_finding(args: list[str], ctx: Ctx) -> str | None:
    args = _split_args([expand(a, ctx)[0] for a in args])
    if any(a in ("--help", "-h") for a in args):
        return None
    pos: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in GH_FLAGS_WITH_VALUE:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        pos.append(a.lower())
        i += 1
    if not pos:
        return None
    if pos[0] == "pr" and len(pos) > 1 and pos[1] == "merge":
        return "gh pr merge"
    if pos[0] == "repo" and len(pos) > 2 and pos[1] == "sync":
        return "gh repo sync of a remote repository"
    if pos[0] == "api":
        return _http_finding(args)
    if pos[0] == "alias":
        joined = " ".join(args)
        if re.search(r"\bpr\s+merge\b", joined, re.I) or GRAPHQL_MUTATIONS.search(joined) \
                or REST_MERGE.search(joined):
            return "gh alias that merges"
    if pos[0] not in GH_KNOWN and ctx.depth < MAX_DEPTH:
        expansion = _gh_aliases().get(pos[0])
        if expansion:
            if expansion.startswith("!"):
                found = scan_text(expansion[1:], ctx.child())
            else:
                rest = args[[a.lower() for a in args].index(pos[0]) + 1:]
                found = gh_finding(_split_args([expansion]) + rest, ctx.child())
            if found:
                return f"gh alias {pos[0]} -> {found}"
    return None


def _protected_names(ctx: Ctx, remote: str | None) -> set[str]:
    names = set(ALWAYS_PROTECTED)
    if not ctx.remote:
        head = _git(ctx.cwd, "symbolic-ref", "-q", "--short", f"refs/remotes/{remote or 'origin'}/HEAD")
        if head and "/" in head:
            names.add(head.split("/", 1)[1].lower())
    return names


def _refspec_destinations(spec: str, ctx: Ctx) -> list[str] | str:
    """Destination branch names of one refspec, or an unresolved-reason string."""
    # "$(git branch --show-current)" and friends name the current branch: resolve as HEAD
    spec = CURRENT_BRANCH.sub("HEAD", spec)
    spec = CURRENT_BRANCH.sub("HEAD", expand(spec, ctx)[0]).lstrip("+")
    # an unresolved reference becomes one opaque mark, so a ':' inside ${x:-y} does not split
    spec = UNRESOLVED.sub("\0", spec)
    if ":" in spec:
        src, dst = spec.split(":", 1)
        dst = dst or src
    else:
        dst = spec
    if "\0" in dst:
        prefix = _short(dst.split("\0")[0])
        suffix = dst.split("\0")[-1].lower().rsplit("/", 1)[-1]  # ${X}/main can be refs/heads/main
        # feature-$b and $USER/feature can never be master; ma$x, $x and $x-ter could be
        if (prefix and not any(p.startswith(prefix) for p in ALWAYS_PROTECTED)) or (
                suffix and not any(p.endswith(suffix) for p in ALWAYS_PROTECTED)):
            return [dst.replace("\0", "$").lower()]
        return ("the destination is a variable or substitution this hook cannot resolve "
                "(write the branch name literally)")
    if dst.upper() in ("HEAD", "@"):
        current = _current_branch(ctx)
        return current if isinstance(current, str) else [current[0].lower()]
    return [_short(dst)]


def _current_branch(ctx: Ctx) -> list[str] | str:
    if ctx.remote:
        return "HEAD on a remote host cannot be resolved"
    if ctx.head_moved:
        return "the branch is switched earlier in this command; name the destination branch explicitly"
    if ctx.branch:
        return [ctx.branch]
    branch = _git(ctx.cwd, "symbolic-ref", "-q", "--short", "HEAD")
    if not branch:
        return "HEAD is not a resolvable branch here"
    return [branch]


def _config(ctx: Ctx, inline: dict[str, str], key: str, all_values: bool = False) -> str | None:
    if key in inline:
        return inline[key]
    return _git(ctx.cwd, "config", "--get-all" if all_values else "--get", key)


def _refspecless_destinations(remote: str | None, ctx: Ctx, inline: dict[str, str]) -> list[str] | str:
    if ctx.remote:
        return "a push without a refspec on a remote host cannot be resolved"
    if _git(ctx.cwd, "rev-parse", "--git-dir") is None:
        return "the repository of this push cannot be resolved"
    configured = _config(ctx, inline, f"remote.{remote or 'origin'}.push", all_values=True)
    if configured:
        out: list[str] = []
        for spec in configured.splitlines():
            got = _refspec_destinations(spec.strip(), ctx)
            if isinstance(got, str):
                return got
            out.extend(got)
        return out
    mode = (_config(ctx, inline, "push.default") or "simple").lower()
    if mode == "matching":
        local = _git(ctx.cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads") or ""
        return [b.lower() for b in local.splitlines() if b.strip()]
    current = _current_branch(ctx)
    if isinstance(current, str):
        return current
    branch = current[0]
    out = [branch.lower()]
    upstream = _config(ctx, inline, f"branch.{branch}.merge")
    if upstream:
        out.append(_short(upstream))
    return out


def push_finding(args: list[str], ctx: Ctx, inline: dict[str, str] | None = None) -> str | None:
    """args: everything after `push` (or `send-pack`)."""
    inline = inline or {}
    remote: str | None = None
    specs: list[str] = []
    deleting = False
    tags_only = False
    i = 0
    while i < len(args):
        a = args[i]
        low = a.lower()
        if a == "--":
            i += 1
            continue
        if low in ("-n", "--dry-run", "--help", "-h"):
            return None
        if low in ("--all", "--branches", "--mirror"):
            return f"git push {a} (includes the default branch)"
        if low in ("-d", "--delete"):
            deleting = True
        elif low == "--tags":
            tags_only = True
        elif low.startswith("--repo="):
            remote = a.split("=", 1)[1]
        elif a in PUSH_FLAGS_WITH_VALUE:
            if a == "--repo" and i + 1 < len(args):
                remote = args[i + 1]
            i += 1
        elif a.startswith("-"):
            pass
        elif remote is None:
            remote = a
        else:
            specs.append(a)
        i += 1

    def protected_hit(names: list[str]) -> str | None:
        # master/main need no lookup; the remote's own default branch costs one git call
        hit = sorted(set(names) & ALWAYS_PROTECTED) or sorted(set(names) & _protected_names(ctx, remote))
        return hit[0] if hit else None

    if not specs:
        if tags_only or deleting:
            return None
        dests = _refspecless_destinations(remote, ctx, inline)
        if isinstance(dests, str):
            return f"git push without a refspec: {dests} (push `git push <remote> <feature-branch>`)"
        if any("*" in d and not d.startswith("refs/tags/") for d in dests):
            return "git push with a configured glob refspec (can reach the default branch)"
        hit = protected_hit(dests) if dests else None
        return f"git push to {hit} (from the current branch)" if hit else None
    collected: list[str] = []
    for spec in specs:
        if deleting:
            dests: list[str] | str = _refspec_destinations(":" + spec, ctx)
        else:
            dests = _refspec_destinations(spec, ctx)
        if isinstance(dests, str):
            return f"git push {spec}: {dests}"
        for d in dests:
            if "*" in d and not d.startswith("refs/tags/"):
                return f"git push glob refspec {spec} (can reach the default branch)"
            collected.append(d)
    hit = protected_hit(collected) if collected else None
    return f"git push to {hit}" if hit else None


def _note_branch_switch(rest: list[str], ctx: Ctx, cwd: Path | None) -> None:
    """After `git checkout|switch ...` in this command the branch on disk is stale: remember
    the new name when it is a plain literal, otherwise mark HEAD as unknown."""
    if cwd != ctx.cwd or "-p" in rest or "--patch" in rest:
        return  # another repository's branch, or patch mode: this HEAD does not move
    if any(a in ("-t", "--track") or a.startswith("--track=") for a in rest):
        ctx.head_moved = True  # the new branch's upstream may be the default branch
        return
    for i, a in enumerate(rest):
        if a in ("-b", "-B", "-c", "-C", "--orphan"):
            new, resolved = expand(rest[i + 1] if i + 1 < len(rest) else "$", ctx)
            if resolved:
                ctx.branch, ctx.head_moved = new, False
                return
            break
    else:
        names = [a for a in rest if not a.startswith("-")]
        if len(names) == 1 and "--" not in rest and not ctx.remote:
            name, resolved = expand(names[0], ctx)
            # an existing local branch is a switch; a file or a commit is not a branch name
            if resolved and _git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}") is not None:
                ctx.branch, ctx.head_moved = name, False
                return
    ctx.head_moved = True


def git_finding(args: list[str], ctx: Ctx) -> str | None:
    """args: everything after the git program token."""
    flat: list[str] = []
    for a in args:
        # PowerShell splat (@a) and an argument list passed as one string (Start-Process)
        if a.startswith("@") and a[1:] in ctx.vars:
            flat.extend(ctx.vars[a[1:]].split())
        else:
            flat.append(a)
    args = flat
    inline: dict[str, str] = {}
    i = 0
    cwd = ctx.cwd
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a in GIT_GLOBAL_WITH_VALUE and i + 1 < len(args):
            value, resolved = expand(args[i + 1], ctx)
            if a == "-C":
                # a remote push never reads cwd; Path join keeps an absolute target as is
                cwd = None if not resolved else (Path(value) if cwd is None else cwd / value)
            elif a == "-c":
                k, _, v = value.partition("=")
                inline[k.lower()] = v
            i += 2
            continue
        i += 1
    if i >= len(args):
        return None
    if re.search(r"\s", args[i]):
        parts = args[i].split()
        if not parts:
            return None
        args = args[:i] + parts + args[i + 1:]
    sub, rest = args[i].lower(), args[i + 1:]
    if sub in ("checkout", "switch"):
        _note_branch_switch(rest, ctx, cwd)
    sub_ctx = ctx.child(cwd=cwd)
    sub_ctx.depth = ctx.depth
    if sub in ("push", "send-pack"):
        return push_finding(rest, sub_ctx, inline)
    if sub == "subtree" and "push" in [r.lower() for r in rest]:
        if any(_short(r) in ALWAYS_PROTECTED for r in rest):
            return "git subtree push to the default branch"
        return None
    if sub in GIT_KNOWN or ctx.depth >= MAX_DEPTH:
        return None
    expansion = inline.get(f"alias.{sub}")
    if expansion is None and not ctx.remote:
        expansion = _git(cwd, "config", "--get", f"alias.{sub}")
    if not expansion:
        return None
    if expansion.startswith("!"):
        found = scan_text(expansion[1:] + " " + " ".join(rest), ctx.child(cwd=cwd))
    else:
        expanded = [t for s in split_commands(expansion) for t in s["tokens"]]
        found = git_finding(expanded + rest, ctx.child(cwd=cwd))
    return f"git alias {sub} -> {found}" if found else None


def _substitution_finding(tokens: list[str], ctx: Ctx) -> str | None:
    """A command substitution runs whatever the outer program is."""
    if ctx.depth >= MAX_DEPTH:
        return None
    for tok in tokens:
        if "$(" in tok or "`" in tok:
            inner = re.sub(r"^.*?(?:\$\(|`)", "", tok)
            found = scan_text(inner.rstrip(")`"), ctx.child())
            if found:
                return found
    return None


def _feeds_a_shell(segments: list[dict], idx: int) -> bool:
    """Does the output of segments[idx] reach a shell or interpreter later in its pipeline?"""
    j = idx
    while j + 1 < len(segments) and segments[j]["sep"] == "|":
        tokens = segments[j + 1]["tokens"]
        p = _primary_index(tokens)
        if p < len(tokens) and _base(tokens[p]) in SHELLS:
            return True
        j += 1
    return False


def _segment_finding(seg: dict, ctx: Ctx, piped_into_shell: bool) -> str | None:
    tokens = seg["tokens"]
    found = _substitution_finding(tokens, ctx)
    if found:
        return found
    p = _primary_index(tokens)
    prog = _base(expand(tokens[p], ctx)[0]) if p < len(tokens) else ""
    if seg["heredocs"] and (prog in SHELLS or piped_into_shell) and ctx.depth < MAX_DEPTH:
        for body in seg["heredocs"]:
            inner = ctx.child(remote=ctx.remote or prog == "ssh")
            found = scan_text(body, inner) or _loose(body, inner)
            if found:
                return f"heredoc fed to {prog}: {found}"
    if p >= len(tokens) or prog in READERS:
        return None
    if prog in ECHOES and not piped_into_shell:
        return None
    if prog in CD_COMMANDS:
        dirs = [t for t in tokens[p + 1:] if not t.startswith("-")]
        if not ctx.remote and dirs and ctx.cwd is not None:
            value, resolved = expand(dirs[0], ctx)
            if ctx.powershell:
                value = value.replace("\\", "/")  # PowerShell paths on any OS
            ctx.cwd = None if not resolved else ctx.cwd / os.path.expanduser(value)
        return None
    rest = tokens[p + 1:]
    if prog == "ssh":
        found = _scan_tokens(rest, ctx.child(remote=True))
        return f"over ssh: {found}" if found else None
    if prog == "gh":
        return gh_finding(rest, ctx)
    if prog == "git":
        return git_finding(rest, ctx)
    if prog == "pr" and rest[:1] == ["merge"]:
        return "pr merge after a computed program name (gh)"
    if prog == "push":
        found = push_finding(rest, ctx)
        return f"push after a computed program name (git): {found}" if found else None
    return _scan_tokens(tokens[p:], ctx)


def _scan_tokens(tokens: list[str], ctx: Ctx) -> str | None:
    """Any-position scan: a gh/git program anywhere in the command, HTTP clients, carried
    strings, interpreter code, variables standing for the program name."""
    expanded = [expand(t, ctx)[0] for t in tokens]
    if any(_base(t) in CURL_LIKE for t in expanded):
        found = _http_finding(expanded)
        if found:
            return found
    for idx, tok in enumerate(expanded):
        base = _base(tok)
        if base == "gh":
            found = gh_finding(tokens[idx + 1:], ctx)
            if found:
                return found
        elif base == "git":
            found = git_finding(tokens[idx + 1:], ctx)
            if found:
                return found
        elif _variable_like(tokens[idx]):
            nxt = [t.lower() for t in expanded[idx + 1: idx + 3]]
            if nxt == ["pr", "merge"]:
                return "a variable standing for gh, then pr merge"
            if nxt[:1] == ["push"]:
                found = push_finding(tokens[idx + 2:], ctx)
                if found:
                    return f"a variable standing for git: {found}"
    if ctx.depth >= MAX_DEPTH:
        return None
    prev = ""
    for tok in tokens:
        before, prev = prev, tok
        if before in MESSAGE_FLAGS:
            continue
        # code after -c/-e/-Command is a program even without a space in it
        if not re.search(r"\s", tok) and before.lower() not in CODE_FLAGS:
            continue
        # printf 'cmd\n' | sh: the escape is a line break by the time a shell reads it
        tok = tok.replace("\\n", "\n")
        found = scan_text(tok, ctx.child()) or _loose(tok, ctx.child())
        if found:
            return found
    return None


def _loose(text: str, ctx: Ctx) -> str | None:
    """Code strings (python -c, node -e, PowerShell arrays, alias values): punctuation is
    noise, so drop it and look for the program followed by its dangerous words."""
    flat = re.sub(r"[\[\]{}()'\"`,;=+]", " ", text)
    words = flat.split()
    for idx, w in enumerate(words):
        b = _base(w)
        if b == "gh":
            found = gh_finding(words[idx + 1:], ctx)
            if found:
                return found
        if b == "git" and words[idx + 1: idx + 2] == ["push"]:
            found = push_finding(words[idx + 2:], ctx.child(remote=True))
            if found and not found.startswith("git push without a refspec"):
                return found
    return None


def scan_text(text: str, ctx: Ctx) -> str | None:
    if ctx.depth > MAX_DEPTH:
        return None
    segments = split_commands(text, ctx.powershell)
    for idx, seg in enumerate(segments):
        if _assignment(seg["tokens"], ctx):
            found = _substitution_finding(seg["tokens"], ctx)
            if found:
                return found
            continue
        before = (ctx.branch, ctx.head_moved)
        found = _segment_finding(seg, ctx, _feeds_a_shell(segments, idx))
        if found:
            return found
        if (ctx.branch, ctx.head_moved) != before and seg["sep"] in ("||", "&", "|"):
            # a checkout that may have failed (||), runs in the background (&) or in a pipe
            ctx.head_moved = True
    return None


def verdict(command: str, cwd: Path | None, powershell: bool = False) -> str | None:
    """A finding string when the command must be blocked, else None."""
    if not PREFILTER.search(command or ""):
        return None
    return scan_text(command, Ctx(cwd, powershell=powershell))


def _reason(finding: str, command: str) -> str:
    return (
        "merge-gate: прямое слияние или push в основную ветку запрещён.\n\n"
        f"Найдено: {finding}\n"
        f"Команда: {command[:300]}\n\n"
        "PR попадает в master/main только через проверенный путь, который сам требует\n"
        "зелёные проверки на точном head и head, содержащий текущий master:\n"
        f"  {SAFE_MERGE_HINT}\n"
        "Код 1 с «waiting for fresh CI» — ветка обновлена, дождаться CI и повторить.\n"
        "Свою работу пушить в ветку фичи: git push origin <feature-branch>.\n"
        "Обхода нет: экстренное слияние делает владелица сама (свой терминал / GitHub UI)."
    )


def decide(event: dict) -> str | None:
    """The block reason for a PreToolUse event, or None to allow."""
    tool = str(event.get("tool_name") or "")
    command = sc.bash_command(event.get("tool_input") or {})
    if not command:
        return None
    cwd = event.get("cwd")  # absent: a refspec-less push cannot be resolved and blocks
    try:
        found = verdict(command, Path(cwd) if cwd else None, powershell=tool.lower() == "powershell")
    except Exception as exc:  # noqa: BLE001
        if FAILCLOSED.search(command):
            sc.log("WARN", HOOK, "block", "analysis-error", command)
            return (f"merge-gate: команда упоминает merge/push, а разбор упал "
                    f"({exc.__class__.__name__}: {exc}). Разбейте её на простые команды.")
        return None
    if found is None:
        return None
    sc.log("BLOCK", HOOK, "block", found, command)
    return _reason(found, command)


def main() -> None:
    reason = decide(sc.read_event())
    if reason is None:
        sc.allow()
    sc.block(reason)


# ---------------------------------------------------------------------------
# Self-test: planted cases, including a must-pass control set.
# ---------------------------------------------------------------------------

def _self_test() -> int:
    import tempfile

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()

        def g(*a: str) -> None:
            subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

        g("init", "-q", "-b", "master")
        g("config", "user.email", "t@example.invalid")
        g("config", "user.name", "t")
        (repo / "f").write_text("x", encoding="utf-8")
        g("add", "f")
        g("commit", "-q", "-m", "init")
        g("branch", "feature")
        feature = Path(tmp) / "feat"
        g("worktree", "add", "-q", str(feature), "feature")

        blocked = [
            ("gh pr merge 5 --merge", repo, False),
            ("g'h' pr merge 5", repo, False),
            ("git push origin HEAD:main --force", feature, False),
            ("git push", repo, False),
            ("ssh host 'gh pr merge 7'", repo, False),
            ("echo 'gh pr merge 5' | bash", repo, False),
            ("gh api -X PUT repos/{owner}/{repo}/pulls/5/merge", repo, False),
            ("& \"C:\\Program Files\\GitHub CLI\\gh.exe\" pr merge 5", repo, True),
        ]
        allowed = [
            ("git push origin feature", feature, False),
            ("git push", feature, False),
            ("gh api repos/o/r/pulls/5/merge", repo, False),
            ("git commit -m 'gh pr merge is now gated'", repo, False),
            ("python ~/.claude/claude-code-config/scripts/safe_merge.py o/r 5", repo, False),
            ("echo 'git push origin master'", repo, False),
        ]
        for cmd, where, ps in blocked:
            if verdict(cmd, where, ps) is None:
                failures.append(f"must block: {cmd}")
        for cmd, where, ps in allowed:
            got = verdict(cmd, where, ps)
            if got is not None:
                failures.append(f"must allow: {cmd} (got {got})")
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(feature)],
                       capture_output=True)

    for line in failures:
        print("FAIL", line)
    print(f"SCANNED: cases={len(blocked) + len(allowed)} failures={len(failures)}")
    print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    main()
