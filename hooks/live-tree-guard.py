#!/usr/bin/env python3
"""The primary checkout receives finished work; it is not where work is done.

Principle 18 framed concurrent sessions as a coordination problem -- append-only files
for one class of state, advisory locks for the other -- and listed git worktrees only in
a table of other people's tools. That accepted the shared tree as a given. It is not:
git already offers a way to make clobbering impossible rather than merely detected.

    Each agent works in its own worktree. The primary tree only receives, through git.
    You cannot overwrite a file you do not have.

A lock says "please do not"; a separate checkout means there is nothing to overwrite. The
difference showed up in one session on 2026-08-04, three times:

  - the primary branch moved underneath an edit because a parallel session committed to it;
  - `git add <directory>` staged another session's in-flight modifications;
  - that same add aborted on a long path from a third session's subtree, so a handoff was
    silently never committed at all.

Opt-in per repository, by a `.claude/live-tree` marker file. Blocking every repo on the
machine would be the non-monotonic harm this codebase already documents -- a guard that
wedges unrelated work gets switched off rather than tuned.

What is still allowed in the primary tree, on purpose:
  * anything inside a linked worktree (that is the sanctioned place to work);
  * append-only per-session artifacts -- handoffs, chronicles, journals. Principle 18 is
    right that those are conflict-free by construction: one file per session, never edited
    by anyone else. Isolation buys nothing there and would cost the handoff workflow;
  * creating a file that is not tracked -- there is nothing of anyone else's to lose.

Bypass:    `CLAUDE_ALLOW_LIVE_TREE_EDIT=1`, or remove the marker file
Self-test: python live-tree-guard.py --self-test
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MARKER = Path(".claude") / "live-tree"

# Type 1 state in principle 18's sense: one file per session, appended, never contended.
APPEND_ONLY = (
    ".claude/handoffs/",
    ".claude/chronicles/",
    ".claude/briefs/",
    ".claude/research/",
    "ops/journal",
    "activity.jsonl",
)

EDITING = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                             text=True, timeout=15, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def in_linked_worktree(repo_dir: Path) -> bool:
    """True inside a `git worktree add` checkout, where working is expected.

    A linked worktree's git-dir sits under the primary repo's common dir, so the two
    differ; in the primary checkout they are the same path.
    """
    git_dir = _git(["rev-parse", "--absolute-git-dir"], repo_dir)
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo_dir)
    if not git_dir or not common:
        return False
    return Path(git_dir).resolve() != Path(common).resolve()


def is_tracked(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    return _git(["ls-files", "--error-unmatch", "--", rel], repo_root) is not None


def append_only(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    return any(marker in rel for marker in APPEND_ONLY)


def assess(file_path: str) -> str | None:
    """None to allow; a reason string to block."""
    try:
        target = Path(file_path)
    except (TypeError, ValueError):
        return None
    search_dir = target.parent if target.parent.exists() else Path.cwd()
    root = _git(["rev-parse", "--show-toplevel"], search_dir)
    if not root:
        return None
    repo_root = Path(root)
    if not (repo_root / MARKER).exists():
        return None
    if in_linked_worktree(repo_root):
        return None
    try:
        target.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None
    if append_only(target, repo_root):
        return None
    if not is_tracked(target, repo_root):
        return None
    rel = target.relative_to(repo_root).as_posix()
    return (
        f"`{rel}` is a tracked file in the PRIMARY checkout of {repo_root.name}, which is "
        f"declared receive-only (`.claude/live-tree`). Another session may be editing it "
        f"right now, and in a shared tree the loser of that race finds out at commit time "
        f"or never.\n\n"
        f"Work in your own worktree instead, then let the primary tree receive it:\n"
        f"    git -C \"{repo_root}\" worktree add .claude/worktrees/<name> -b <branch>\n"
        f"    # edit there, commit, push; the primary tree pulls or merges\n\n"
        f"Append-only artifacts (handoffs, chronicles, journals) are exempt and need no "
        f"worktree. Deliberate override: CLAUDE_ALLOW_LIVE_TREE_EDIT=1."
    )


def main() -> int:
    if os.environ.get("CLAUDE_ALLOW_LIVE_TREE_EDIT") == "1":
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0  # fail open: a guard bug must not be the reason work stops
    if event.get("tool_name") not in EDITING:
        return 0
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not path:
        return 0
    reason = assess(str(path))
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def self_test() -> int:
    import tempfile

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    def run(args, cwd):
        subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                       timeout=30)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "repo"
        root.mkdir()
        run(["init", "-b", "main"], root)
        run(["config", "user.email", "t@example.invalid"], root)
        run(["config", "user.name", "t"], root)
        tracked = root / "src.py"
        tracked.write_text("x = 1\n", encoding="utf-8")
        handoff = root / ".claude" / "handoffs" / "proj"
        handoff.mkdir(parents=True)
        (handoff / "note.md").write_text("hi\n", encoding="utf-8")
        run(["add", "-A"], root)
        run(["commit", "-m", "init"], root)

        check("no marker -> silent", assess(str(tracked)) is None, True)

        (root / ".claude" / "live-tree").write_text("", encoding="utf-8")
        check("tracked file in the primary tree is blocked",
              assess(str(tracked)) is not None, True)
        check("the block names the file",
              "src.py" in (assess(str(tracked)) or ""), True)
        check("a handoff is exempt", assess(str(handoff / "note.md")) is None, True)
        check("an untracked new file is allowed",
              assess(str(root / "brand-new.py")) is None, True)

        wt = Path(td) / "wt"
        run(["worktree", "add", str(wt), "-b", "side"], root)
        if (wt / "src.py").exists():
            check("the same file inside a linked worktree is allowed",
                  assess(str(wt / "src.py")) is None, True)
            check("linked worktree is detected as linked", in_linked_worktree(wt), True)
            check("primary tree is not detected as linked", in_linked_worktree(root), False)
        else:
            failures.append("worktree add did not produce a checkout")

        outside = Path(td) / "loose.txt"
        outside.write_text("x", encoding="utf-8")
        check("a file outside any repo is silent", assess(str(outside)) is None, True)

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
