#!/usr/bin/env python3
"""SessionStart hook: flag when a repo's agent-facing docs have gone STALE vs code.

Adopts the useful, mechanical half of OpenWiki (langchain-ai/openwiki, MIT) into
our own harness. OpenWiki auto-GENERATES a repo wiki and refreshes it on a
schedule so coding agents read current context. Generation needs LLM calls
(token cost -> opt-in, see rules/safety-billing.md) and is the tool's job. The
FREE, deterministic, testable half -- "are those docs still fresh, and does
AGENTS.md point to them?" -- is what we own here, as an advisory detector.

Why a hook, not a reminder: acting on STALE repo docs = acting on wrong context
(agent-legible-environment). "Docs exist" != "docs current". A mechanical
invariant beats prompt advice. Detection is automatic; refreshing the docs stays
a human/tool decision (mirrors long-run-detector.py: detect auto, act human).

Anchors whose freshness we track (current project = cwd):
  - openwiki/      (OpenWiki output)
  - docs/layers/   (our feature-layer curated docs, principle 28)
Freshness signal (git = source of truth, git-source-of-truth.md):
  base = last commit that touched the anchor. Every commit in base..HEAD by
  construction did NOT touch the anchor, so its count = how far the docs have
  fallen behind. >= STALE_COMMITS -> STALE.
Pointer signal:
  openwiki/ present but neither AGENTS.md nor CLAUDE.md references it -> the docs
  exist but agents are not told to read them (OpenWiki's core thesis).

Silent (opt-in) when: no anchor present; cwd is HOME / ~/.claude; docs are fresh;
nagged < COOLDOWN_DAYS ago; or .claude/.skip-docs-staleness present.
Informational only: prints to stdout (SessionStart context), never blocks, exit 0
always (fail-open). Mirrors long-run-detector.py conventions.

Tunables: CLAUDE_DOCS_STALE_COMMITS (default 20).
Opt-out per project: touch .claude/.skip-docs-staleness
Register in ~/.claude/settings.json SessionStart[].hooks[].
Self-test (no-silent-validators invariant): python docs-staleness-guard.py --self-test
Reference: ~/.claude/rules/agent-docs-freshness.md
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

COOLDOWN_DAYS = 7
DEFAULT_STALE_COMMITS = 20
ANCHORS = ("openwiki", "docs/layers")
ANCHORS_FILE = ".docs-anchors"  # .claude/.docs-anchors: extra per-project anchors, one rel path per line
STAMP_NAME = ".docs-staleness-nudged"
SKIP_NAME = ".skip-docs-staleness"


def _project_anchors(cwd: Path) -> tuple[str, ...]:
    """Default anchors + optional per-project extras from .claude/.docs-anchors.

    Lets a repo whose agent-KB lives elsewhere (e.g. a kb/docs
    MkDocs tree) opt its real docs root into freshness tracking. Lines starting
    with '#' are comments; paths are repo-relative.
    """
    extra: list[str] = []
    f = cwd / ".claude" / ANCHORS_FILE
    if f.exists():
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip().replace("\\", "/").strip("/")
                if line and not line.startswith("#"):
                    extra.append(line)
        except Exception:
            pass
    return ANCHORS + tuple(x for x in extra if x not in ANCHORS)


def _git_out(cwd: Path, *args: str) -> str | None:
    """Run a git command; return stripped stdout, or None on any failure."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=4
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip()
    except Exception:
        return None


def _git_count(cwd: Path, *args: str) -> int:
    """Run a git command expected to print a number; return it, or -1 on failure."""
    s = _git_out(cwd, *args)
    if s is None:
        return -1
    try:
        return int(s.strip() or 0)
    except ValueError:
        return -1


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def detect(cwd: Path, stale_commits: int) -> list[str] | None:
    """Return list of finding strings if a nudge should fire, else None."""
    home = Path.home().resolve()
    if cwd.resolve() in (home, (home / ".claude").resolve()):
        return None
    if (cwd / ".claude" / SKIP_NAME).exists():
        return None

    anchor_present = False
    findings: list[str] = []

    for anchor in _project_anchors(cwd):
        if not (cwd / anchor).exists():
            continue
        anchor_present = True
        base = _git_out(cwd, "rev-list", "-1", "HEAD", "--", anchor)
        if not base:
            continue  # anchor not committed yet -> cannot measure staleness
        n = _git_count(cwd, "rev-list", "--count", f"{base}..HEAD")
        if n >= stale_commits:
            findings.append(
                f"{anchor}/ is {n} commits behind HEAD "
                f"(>= {stale_commits}) -- refresh the agent docs"
            )

    # Pointer check: generated docs are useless if agents are not told to read them.
    if (cwd / "openwiki").exists():
        referenced = any(
            "openwiki" in _read_text(cwd / f).lower()
            for f in ("AGENTS.md", "CLAUDE.md")
        )
        if not referenced:
            findings.append(
                "openwiki/ present but not referenced from AGENTS.md/CLAUDE.md "
                "-- add a one-line pointer so agents read it"
            )

    if not anchor_present:
        return None
    return findings or None


def _recently_nudged(claude_dir: Path, now: float) -> bool:
    stamp = claude_dir / STAMP_NAME
    if not stamp.exists():
        return False
    try:
        return (now - stamp.stat().st_mtime) / 86400 < COOLDOWN_DAYS
    except Exception:
        return False


def _stamp(claude_dir: Path) -> None:
    try:
        if claude_dir.exists():
            (claude_dir / STAMP_NAME).write_text(
                time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8"
            )
    except Exception:
        pass


def main() -> int:
    cwd = Path.cwd()
    claude_dir = cwd / ".claude"
    now = time.time()
    if _recently_nudged(claude_dir, now):
        return 0
    try:
        stale_commits = int(os.environ.get("CLAUDE_DOCS_STALE_COMMITS", "") or DEFAULT_STALE_COMMITS)
    except ValueError:
        stale_commits = DEFAULT_STALE_COMMITS

    findings = detect(cwd, stale_commits)
    if not findings:
        return 0

    lines = [
        "=" * 60,
        "AGENT DOCS FRESHNESS: repo docs the agent relies on look stale.",
        *[f"  - {f}" for f in findings],
        "=" * 60,
        "INSTRUCTION: treat these agent-facing docs as possibly out-of-date.",
        "Refresh them (OpenWiki `openwiki --update`, or update docs/layers/) and",
        "ensure AGENTS.md points to them. Generation costs tokens (opt-in, see",
        "rules/safety-billing.md); this detection is free. Surface to the user.",
        "See rules/agent-docs-freshness.md. Opt out: touch .claude/.skip-docs-staleness",
        "=" * 60,
        "",
    ]
    print("\n".join(lines))
    _stamp(claude_dir)
    return 0


def _self_test() -> int:
    import tempfile

    def run(cwd: Path, *a: str) -> None:
        subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True)

    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "repo"
        root.mkdir()
        run(root, "init", "-q")
        run(root, "config", "user.email", "t@t")
        run(root, "config", "user.name", "t")
        run(root, "config", "commit.gpgsign", "false")

        # commit an openwiki doc as the anchor
        (root / "openwiki").mkdir()
        (root / "openwiki" / "index.md").write_text("doc", encoding="utf-8")
        run(root, "add", "-A")
        run(root, "commit", "-q", "-m", "docs")

        # fresh docs, pointer missing -> exactly the pointer finding, no staleness
        f = detect(root, 20)
        if not f or not any("not referenced" in x for x in f):
            print("SELF-TEST FAIL: missing pointer not detected")
            ok = False
        if f and any("behind HEAD" in x for x in f):
            print("SELF-TEST FAIL: fresh docs wrongly flagged stale")
            ok = False

        # add the pointer -> pointer finding disappears
        (root / "AGENTS.md").write_text("Map lives in openwiki/", encoding="utf-8")
        run(root, "add", "-A")
        run(root, "commit", "-q", "-m", "pointer")
        f = detect(root, 20)
        if f and any("not referenced" in x for x in f):
            print("SELF-TEST FAIL: present pointer still flagged")
            ok = False

        # advance source past a small threshold -> staleness fires
        for i in range(4):
            (root / f"src{i}.py").write_text(f"x = {i}", encoding="utf-8")
            run(root, "add", "-A")
            run(root, "commit", "-q", "-m", f"c{i}")
        f = detect(root, 3)  # 5 commits since anchor (pointer + 4 src) >= 3
        if not f or not any("behind HEAD" in x for x in f):
            print("SELF-TEST FAIL: stale docs not detected")
            ok = False

        # opt-out file silences everything
        (root / ".claude").mkdir(exist_ok=True)
        (root / ".claude" / SKIP_NAME).write_text("x", encoding="utf-8")
        if detect(root, 3) is not None:
            print("SELF-TEST FAIL: opt-out file did not silence")
            ok = False

        # repo with no anchor -> silent
        bare = Path(td) / "bare"
        bare.mkdir()
        run(bare, "init", "-q")
        if detect(bare, 20) is not None:
            print("SELF-TEST FAIL: repo without anchor should be silent")
            ok = False

        # custom anchor via .claude/.docs-anchors -> staleness tracked for kb/docs
        cust = Path(td) / "custom"
        cust.mkdir()
        run(cust, "init", "-q")
        run(cust, "config", "user.email", "t@t")
        run(cust, "config", "user.name", "t")
        run(cust, "config", "commit.gpgsign", "false")
        (cust / "kb" / "docs").mkdir(parents=True)
        (cust / "kb" / "docs" / "index.md").write_text("kb", encoding="utf-8")
        (cust / ".claude").mkdir()
        (cust / ".claude" / ANCHORS_FILE).write_text("# agent-KB\nkb/docs\n", encoding="utf-8")
        run(cust, "add", "-A")
        run(cust, "commit", "-q", "-m", "kb")
        for i in range(4):
            (cust / f"s{i}.py").write_text(str(i), encoding="utf-8")
            run(cust, "add", "-A")
            run(cust, "commit", "-q", "-m", f"c{i}")
        f = detect(cust, 3)
        if not f or not any("kb/docs" in x for x in f):
            print("SELF-TEST FAIL: custom anchor kb/docs staleness not detected")
            ok = False

    print("SELF-TEST: PASS" if ok else "SELF-TEST: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
