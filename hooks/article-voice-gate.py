#!/usr/bin/env python3
"""PreToolUse: an article reaches the knowledge base only with a check behind it.

The news pipeline writes knowledge-base pages by machine. Two passes stand between
the assembled facts and the public repository: an editor that rewrites the sentences
in the house voice under mechanical guards, and an independent checker that reads the
result against the same research and names anything invented. Both leave a receipt.

This gate refuses the publishing step - pushing a `kb/` branch, opening or merging its
pull request - when that receipt is missing or says the page was refused. It is the
mechanical half of the owner's rule (2026-09-04): "из головы писать не должен, надо
человеческий стиль написания и проверять все данные".

Three states, and the middle one is not green (see rules/absence-of-signal.md):
  receipt says checked, nothing invented  -> allow
  receipt says refused / invented         -> block, naming the finding
  no receipt for this branch              -> block as UNVERIFIED, not as fine

Scope: one pipeline, not every repository with a `kb/` in it (2026-09-27). A `kb/`
token alone is not evidence of an article - `kb/docs/platform/...` is an engineering
reference filed by hand in another repository, with no renderer, no ledger and no
`ops/codex/article_voice.py` anywhere in that repository. For such a file no receipt
can ever exist, so the gate had exactly one exit there: its own bypass. A gate that is
always bypassed has stopped being a gate, and the habit travels to the pages where the
check is real. See `in_scope` for the three things that put a command inside the
pipeline - and for why the pipeline's own marker is not one of them on its own.

Bypass: `# claude-bypass: article-voice` in the command, or CLAUDE_ALLOW_ARTICLE_VOICE=1.
Self-test: python article-voice-gate.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from safety_common import block, bypass, read_event  # type: ignore
except Exception:  # a hook that cannot load its helpers must not wedge the session
    block = bypass = read_event = None  # type: ignore

REPO = "AnastasiyaW/knowledge-space"
BRANCH = re.compile(r"(?:^|[\s\"'/:])(kb/[A-Za-z0-9._-]+)")
# Git takes its own options before the verb, and `git -C <clone> push` is exactly how
# one reaches another repository - the publish verb has to survive them, or the gate
# reads that command as no publish at all (found by the scope controls, 2026-09-27).
GIT_GLOBAL = r"(?:-C\s+\S+|-c\s+\S+|--git-dir=\S+|--work-tree=\S+|--no-pager)"
PUBLISHES = re.compile(rf"(?i)\bgh\s+pr\s+(create|merge)\b|\bgit\b(?:\s+{GIT_GLOBAL})*\s+push\b")
# What identifies the pipeline's own repository from inside it. The renderer, the
# editor and the checker live in ops/codex; every receipt lands in var/kb-articles.
PIPELINE_MARKERS = ("ops/codex/article_voice.py", "var/kb-articles")
# What identifies the knowledge base itself. The writer commits and pushes with its
# working directory set to a *clone of the knowledge base*, and that clone carries no
# pipeline marker at all - measured 2026-09-27. A marker-only scope would therefore have waved the real publishing
# path straight through, which is the opposite of the point.
KB_SLUG = "knowledge-space"
# `git -C <path>` moves the repository out from under the working directory.
GIT_C = re.compile(r"-C\s+(\"[^\"]+\"|'[^']+'|\S+)")
# Where the writer files its receipts. The first that exists wins; a project may name
# its own through CLAUDE_NEWS_LEDGERS (semicolon-separated).
# Built from the home directory, never written out: this file lives in a public
# repository and a literal user path is exactly what its scan refuses.
_WORK = Path.home() / "Desktop" / "Codex+Code"
DEFAULT_LEDGERS = [
    _WORK / "worktrees" / "happyin-news-v1-4" / "diffusion-love" / "var" / "kb-articles",
    _WORK / "diffusion-love" / "var" / "kb-articles",
    Path.cwd() / "var" / "kb-articles",
]
LEDGER_FILES = ("ledger.jsonl", "revoice.jsonl")


def ledger_dirs() -> list[Path]:
    configured = os.environ.get("CLAUDE_NEWS_LEDGERS", "").strip()
    if configured:
        return [Path(p) for p in configured.split(";") if p.strip()]
    return DEFAULT_LEDGERS


def receipts_for(branch: str) -> list[dict]:
    """Every receipt that names this branch, oldest first."""
    found: list[dict] = []
    for directory in ledger_dirs():
        for name in LEDGER_FILES:
            path = directory / name
            if not path.is_file():
                continue
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if branch not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("branch") == branch:
                        found.append(record)
            except OSError:
                continue
    return found


def verdict(branch: str) -> tuple[str, str]:
    """(state, why) where state is 'checked', 'refused' or 'unverified'."""
    records = receipts_for(branch)
    if not records:
        return "unverified", f"no receipt names {branch} in {', '.join(str(d) for d in ledger_dirs())}"
    latest = records[-1]
    check = latest.get("check") or {}
    voice = latest.get("voice") or {}
    invented = check.get("invented") or []
    if invented:
        return "refused", f"the independent check found {len(invented)} invented specific(s): {str(invented[0])[:160]}"
    if not check:
        return "unverified", "the receipt carries no check: the page was written before the gate, or with --no-voice"
    if voice.get("status") == "refused":
        why = "; ".join(str(c) for c in (voice.get("complaints") or [])[:2])
        return "checked", f"the rewrite was refused ({why or 'guards'}), so the assembled text is what publishes - allowed"
    return "checked", f"check verdict {check.get('verdict', 'unknown')}, nothing invented"


def branches_in(command: str) -> list[str]:
    return sorted({m.group(1).rstrip(".,;\"'") for m in BRANCH.finditer(command)})


def repo_root(start: Path) -> Path | None:
    """The nearest ancestor holding .git - a directory, or a linked worktree's file."""
    try:
        here = Path(start).resolve()
    except (OSError, ValueError):
        return None
    for candidate in (here, *here.parents):
        try:
            if (candidate / ".git").exists():
                return candidate
        except OSError:
            continue
    return None


def git_config_text(root: Path) -> str:
    """The repository's config, reached through a worktree pointer when there is one."""
    dot = root / ".git"
    candidates: list[Path] = []
    try:
        if dot.is_dir():
            candidates.append(dot / "config")
        elif dot.is_file():
            pointer = dot.read_text(encoding="utf-8", errors="replace").partition("gitdir:")[2].strip()
            if pointer:
                gitdir = Path(pointer)
                # A linked worktree keeps its remotes in the main repository's config,
                # two levels above .git/worktrees/<name>.
                candidates += [gitdir / "config", gitdir.parent.parent / "config"]
    except OSError:
        return ""
    for path in candidates:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def roots_in(command: str, cwd: Path) -> list[Path]:
    """Repository roots this command can act on: its working directory, plus any `git -C`.

    simplification: the union, not the override. `git -C X` does replace the working
    directory for git, so a `-C` into an unrelated repository from inside the knowledge
    base is read as in scope and refused. That costs a bypass line in a case nobody has
    hit; reading only the `-C` target would instead let a crafted command out of a gate.
    """
    starts = [cwd]
    for match in GIT_C.finditer(command):
        named = Path(match.group(1).strip("\"'"))
        # A relative -C is relative to the command's working directory, not to this hook's.
        starts.append(named if named.is_absolute() else cwd / named)
    roots: list[Path] = []
    for start in starts:
        root = repo_root(start)
        if root is not None and root not in roots:
            roots.append(root)
    return roots


def in_scope(command: str, cwd: Path) -> tuple[bool, str]:
    """(guarded, why) - does this command publish into the knowledge base this gate guards?

    Three things put a command inside the pipeline, and nothing else does:
      the command names the knowledge base repository (`gh pr ... --repo`, an explicit URL);
      it runs in the repository that owns the pipeline (a marker in that root);
      it runs in a clone of the knowledge base (its git config names that remote).
    Both repository tests are needed: the pipeline repository holds the renderer and the
    receipts but is not where the push happens, and the clone is where the push happens
    but holds neither. Anything else - a `kb/` path in some unrelated tree - is not an
    article, and refusing it would leave only the bypass as a way through.
    """
    if REPO in command or KB_SLUG in command:
        return True, "the command names the knowledge base"
    for root in roots_in(command, cwd):
        for marker in PIPELINE_MARKERS:
            if (root / marker).exists():
                return True, f"{root.name} owns the pipeline ({marker})"
        if KB_SLUG in git_config_text(root):
            return True, f"{root.name} is a clone of the knowledge base"
    return False, ""


def decide(command: str, cwd: Path | None = None) -> tuple[bool, str]:
    """(allowed, reason). A command that does not publish an article is allowed."""
    if not PUBLISHES.search(command):
        return True, ""
    names = branches_in(command)
    if not names:
        return True, ""
    guarded, _ = in_scope(command, Path(cwd) if cwd else Path.cwd())
    if not guarded:
        return True, ""  # another repository's kb/ paths are not this pipeline's articles
    problems = []
    for branch in names:
        state, why = verdict(branch)
        if state == "checked":
            continue
        problems.append(f"{branch}: {state} - {why}")
    if not problems:
        return True, ""
    return False, "\n".join(problems)


def main() -> None:
    if read_event is None or block is None:
        sys.exit(0)  # fail open: a broken gate must not stop the work
    try:
        event = read_event()
        command = (event.get("tool_input") or {}).get("command") or ""
        # The event carries the session's working directory; the hook process is started
        # in it too, so the fallback is the same place by another road.
        cwd = event.get("cwd") or ""
    except Exception:
        sys.exit(0)
    if not command:
        sys.exit(0)
    if bypass("article-voice", command, env_name="CLAUDE_ALLOW_ARTICLE_VOICE"):
        sys.exit(0)
    allowed, reason = decide(command, Path(cwd) if cwd else Path.cwd())
    if allowed:
        sys.exit(0)
    block(
        "An article may not reach the knowledge base without its check.\n\n"
        f"{reason}\n\n"
        "The page is written by the renderer, rewritten by the editor in the house voice under\n"
        "mechanical guards, then read by an independent checker against the same research\n"
        "(ops/codex/article_voice.py). The receipt of that pass is what this gate reads.\n\n"
        "Ways forward: run the page through ops/codex/article_revoice.py (it re-assembles and\n"
        "re-checks from the filed research), or, for a page that is deliberately unchecked,\n"
        "add '# claude-bypass: article-voice' with a reason."
    )


# (command, where, label, expected_allowed). `where` names one of the three fixture
# repositories: the pipeline's own repository, a clone of the knowledge base, and an
# unrelated repository that keeps engineering references under kb/docs.
SELF_TEST = [
    ("git push origin kb/vidu-20260903-2010", "clone", "unverified", False),
    ("gh pr create --repo AnastasiyaW/knowledge-space --head kb/checked-1 --title x", "other",
     "checked, named repo from anywhere", True),
    ("gh pr merge 48 --repo AnastasiyaW/knowledge-space --merge", "clone", "no branch named", True),
    ("git push origin kb/invented-1", "clone", "invented", False),
    ("git push origin kb/refused-rewrite-1", "clone", "rewrite refused, text is the assembled one", True),
    ("git status", "clone", "not a publish", True),
    ("git push origin main", "clone", "not an article branch", True),
    ("git push origin kb/unverified-1 # claude-bypass: article-voice", "clone", "bypass", True),
    # Scope, both ways.
    ("git add kb/docs/platform/service-notes.md && git commit -m x && git push", "other",
     "another repository's kb/docs reference", True),
    ("git push origin kb/never-seen-1", "pipeline", "unverified, inside the pipeline repository", False),
    ("gh pr create --repo AnastasiyaW/knowledge-space --head kb/never-seen-2 --title x", "other",
     "unverified, named repo from anywhere", False),
    ("git -C ../clone push origin kb/never-seen-3", "other", "unverified, reached by git -C", False),
]


def _fixture(tmp: Path) -> dict[str, Path]:
    """Three repositories, differing only in what the gate is supposed to read."""
    pipeline = tmp / "pipeline"
    (pipeline / ".git").mkdir(parents=True)
    (pipeline / "var" / "kb-articles").mkdir(parents=True)  # the marker

    clone = tmp / "clone"
    (clone / ".git").mkdir(parents=True)
    (clone / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/AnastasiyaW/knowledge-space.git\n', encoding="utf-8")

    other = tmp / "other"
    (other / ".git").mkdir(parents=True)
    (other / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://example.invalid/other-project.git\n', encoding="utf-8")
    (other / "kb" / "docs" / "platform").mkdir(parents=True)
    (other / "kb" / "docs" / "platform" / "service-notes.md").write_text("# reference\n", encoding="utf-8")
    return {"pipeline": pipeline, "clone": clone, "other": other}


def self_test() -> int:
    import tempfile

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        where = _fixture(directory)
        rows = [
            {"branch": "kb/checked-1", "voice": {"status": "edited"}, "check": {"verdict": "pass", "invented": []}},
            {"branch": "kb/invented-1", "voice": {"status": "edited"}, "check": {"verdict": "needs_work", "invented": ["a price nobody published"]}},
            {"branch": "kb/refused-rewrite-1", "voice": {"status": "refused", "complaints": ["dropped 2 dates"]},
             "check": {"verdict": "pass", "invented": []}},
            {"branch": "kb/no-check-1", "voice": {"status": "edited"}},
        ]
        (directory / "ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        os.environ["CLAUDE_NEWS_LEDGERS"] = str(directory)
        for command, place, label, expected in SELF_TEST:
            if "claude-bypass" in command:
                allowed = True  # the real path exits before decide(); the marker is the contract
            else:
                allowed, _ = decide(command, where[place])
            if allowed != expected:
                failures.append(f"{label}: expected allowed={expected}, got {allowed} for {command!r}")
        # The negative control: a gate that cannot go red is broken, and one that cannot
        # go green on another repository's files is a bypass generator. Same unknown
        # branch, three working directories, and the answer must differ by repository.
        unknown = "git push origin kb/never-seen-branch"
        for place, expected in (("pipeline", False), ("clone", False), ("other", True)):
            allowed, _ = decide(unknown, where[place])
            if allowed != expected:
                failures.append(f"negative control in {place}: expected allowed={expected}, got {allowed}")
    for line in failures:
        print("FAIL", line)
    total = len(SELF_TEST) + 3
    print(f"{total - len(failures)} of {total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    main()
