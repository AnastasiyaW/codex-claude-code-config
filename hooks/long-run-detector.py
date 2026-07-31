#!/usr/bin/env python3
"""SessionStart hook: auto-DETECT a long-running project and nudge to adopt the harness.

Why: the [LONG-RUN] mark + feature_list.json/init.sh harness (see
~/.claude/rules/long-run-harness.md) is assigned MANUALLY after a 15-point
checklist -- by design, to avoid premature "declared victory" marks. But a
manual gate rots: a project quietly grows across many sessions and nobody runs
the checklist. This hook makes the DETECTION mechanical while keeping the human
decision: it surfaces "this looks long-running -> run the checklist + mark it"
when signals appear, and stays silent otherwise.

It does NOT auto-write the [LONG-RUN] mark (that stays a human call, per the
rule's anti-pattern about premature marks). Detection auto, decision human.

Signals (current project = cwd):
  - strong : >=3 dated session handoffs in .claude/handoffs/<slug>/ (multi-session)
  - medium : >=40 git commits ; >=200 tracked files ; PROBLEMS.md present
  Fire when strong OR (>=2 medium).

Suppressed (silent) when:
  - already adopted   : feature_list.json or init.sh present in cwd
  - aggregation hub   : >5 distinct project subdirs under .claude/handoffs/
                        (a multi-project hub, not a single project to mark)
  - not a real project: cwd is HOME / ~/.claude / has no .git and no .claude
  - nagged recently   : .claude/.longrun-nudged stamped < NUDGE_COOLDOWN_DAYS ago

Informational only: prints to stdout (becomes SessionStart context), never blocks,
exit 0 always (fail-open). Mirrors session-handoff-check.py conventions.

Register in ~/.claude/settings.json SessionStart[].hooks[].
Self-test (no-silent-validators.md invariant): python long-run-detector.py --self-test

Reference: ~/.claude/rules/long-run-harness.md, activity-journal-and-state-registry.md
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

NUDGE_COOLDOWN_DAYS = 14
HUB_SUBDIR_LIMIT = 5      # > this many project subdirs => aggregation hub, skip
MIN_HANDOFFS = 3          # strong signal
MIN_COMMITS = 40          # medium signal
MIN_TRACKED = 200         # medium signal


def _git(cwd: Path, *args: str, count_lines: bool = False) -> int:
    """Run a git command; return its int value (or line count), -1 on any failure."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=3
        )
        if out.returncode != 0:
            return -1
        if count_lines:
            return sum(1 for ln in out.stdout.splitlines() if ln.strip())
        return int(out.stdout.strip() or 0)
    except Exception:
        return -1


def has_agent_docs(cwd: Path) -> bool:
    """Any curated agent-facing docs tree present (kb-skeleton or equivalents)."""
    return any(
        (cwd / p).exists()
        for p in ("docs/kb", "docs/layers", "kb/docs", "openwiki", "scripts/validate_kb.py")
    )


def detect(cwd: Path) -> list[str] | None:
    """Return list of signal strings if a nudge should fire, else None."""
    home = Path.home().resolve()
    if cwd.resolve() in (home, (home / ".claude").resolve()):
        return None
    claude_dir = cwd / ".claude"
    if not (cwd / ".git").exists() and not claude_dir.exists():
        return None
    # already adopted the long-run harness -> nothing to nudge
    if (cwd / "feature_list.json").exists() or (cwd / "init.sh").exists():
        return None

    signals: list[str] = []
    strong = False

    hdir = claude_dir / "handoffs"
    if hdir.exists():
        subdir_count = sum(
            1 for d in hdir.iterdir() if d.is_dir() and d.name != "archive"
        )
        if subdir_count > HUB_SUBDIR_LIMIT:
            return None  # multi-project aggregation hub, not one project
        handoffs = 0
        for p in hdir.rglob("*.md"):
            rel = p.relative_to(hdir)
            if p.name.startswith("INDEX") or "archive" in rel.parts:
                continue
            handoffs += 1
        if handoffs >= MIN_HANDOFFS:
            strong = True
            signals.append(f"{handoffs} session handoffs (multi-session work)")

    commits = _git(cwd, "rev-list", "--count", "HEAD")
    if commits >= MIN_COMMITS:
        signals.append(f"{commits} git commits")
    tracked = _git(cwd, "ls-files", count_lines=True)
    if tracked >= MIN_TRACKED:
        signals.append(f"{tracked} tracked files (large codebase)")
    if (cwd / "PROBLEMS.md").exists():
        signals.append("PROBLEMS.md present (ongoing incident log)")

    if strong or len(signals) >= 2:
        return signals
    return None


def hub_context_gap(cwd: Path) -> list[str] | None:
    """An aggregation hub is exempt from the [LONG-RUN] mark, not from context.

    detect() returns None for a hub because "mark this one project [LONG-RUN]"
    is wrong advice for a directory holding dozens. Silence is wrong too: a hub
    with no AGENTS.md and no plan leaves every agent that opens it with no
    project context at all, and by construction nothing else is watching it.
    Observed cost: a hub ran for weeks on a branch whose snapshot had dropped
    AGENTS.md, feature_list.json, README.md and the health check, and the only
    symptom was that the agent seemed to know nothing about the project.
    """
    hdir = cwd / ".claude" / "handoffs"
    if not hdir.is_dir():
        return None
    try:
        subdirs = sum(1 for d in hdir.iterdir() if d.is_dir() and d.name != "archive")
    except OSError:
        return None
    if subdirs <= HUB_SUBDIR_LIMIT:
        return None
    missing = [
        name for name in ("AGENTS.md", "CLAUDE.md", "feature_list.json")
        if not (cwd / name).exists()
    ]
    if not missing:
        return None
    return [f"aggregation hub with {subdirs} project subdirs", "missing: " + ", ".join(missing)]


def _recently_nudged(claude_dir: Path, now: float) -> bool:
    stamp = claude_dir / ".longrun-nudged"
    if not stamp.exists():
        return False
    try:
        age_days = (now - stamp.stat().st_mtime) / 86400
        return age_days < NUDGE_COOLDOWN_DAYS
    except Exception:
        return False


def _stamp(claude_dir: Path) -> None:
    try:
        if claude_dir.exists():
            (claude_dir / ".longrun-nudged").write_text(
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
    signals = detect(cwd)
    if not signals:
        gap = hub_context_gap(cwd)
        if gap:
            print("=" * 60)
            print("AGENT CONTEXT MISSING in this aggregation hub.")
            print("  " + "; ".join(gap))
            print("=" * 60)
            print("INSTRUCTION: a hub is exempt from the [LONG-RUN] mark, not from")
            print("carrying context. It needs AGENTS.md (canonical, harness-neutral),")
            print("a thin CLAUDE.md importing it with @AGENTS.md, and feature_list.json")
            print("holding the plan. If this repo has them on another branch they are")
            print("almost certainly still there -- check before writing new ones:")
            print("  git checkout origin/main -- AGENTS.md feature_list.json README.md")
            _stamp(claude_dir)
        return 0

    docs_missing = not has_agent_docs(cwd)
    lines = [
        "=" * 60,
        "LONG-RUN candidate: this project shows long-running signals but is",
        "NOT tracked as [LONG-RUN] (no feature_list.json / init.sh).",
        "  signals: " + "; ".join(signals),
    ]
    if docs_missing:
        lines += [
            "  ALSO: no agent-docs tree (docs/kb, docs/layers, kb/docs all absent).",
        ]
    lines += [
        "=" * 60,
        "INSTRUCTION: Consider the long-run harness (rules/long-run-harness.md):",
        "run the 15-point First Release Checklist; if it passes, mark the project",
        "[LONG-RUN] in MEMORY.md and add feature_list.json + init.sh.",
    ]
    if docs_missing:
        lines += [
            "ALSO PROPOSE to the user adopting the agent-docs KB now (kb-skeleton:",
            "docs/kb + scripts/validate_kb.py, rules/agent-docs-freshness.md) --",
            "a complex project without docs is the exact gap the freshness tiers",
            "close; once adopted, the Stop-gate + CI keep it current mechanically.",
        ]
    lines += [
        "Detection is automatic; the [LONG-RUN] mark and KB adoption stay a human",
        "decision by design (premature marks are an anti-pattern). Surface this to",
        "the user as an explicit proposal.",
        "=" * 60,
        "",
    ]
    print("\n".join(lines))
    _stamp(claude_dir)
    return 0


def _self_test() -> int:
    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # known-positive: 3 handoffs in one project subdir, not adopted
        proj = root / "proj"
        hd = proj / ".claude" / "handoffs" / "alpha"
        hd.mkdir(parents=True)
        for i in range(3):
            (hd / f"2026-06-1{i}_10-00_abc1234{i}.md").write_text("h", encoding="utf-8")
        pos = detect(proj)
        if not pos:
            print("SELF-TEST FAIL: long-run project not detected")
            ok = False
        # known-negative: same but adopted (feature_list.json present)
        (proj / "feature_list.json").write_text("{}", encoding="utf-8")
        if detect(proj) is not None:
            print("SELF-TEST FAIL: adopted project should be silent")
            ok = False
        # known-negative: aggregation hub (6 project subdirs)
        hub = root / "hub"
        hubh = hub / ".claude" / "handoffs"
        for n in range(6):
            sd = hubh / f"p{n}"
            sd.mkdir(parents=True)
            (sd / f"2026-06-10_10-00_dead000{n}.md").write_text("h", encoding="utf-8")
        if detect(hub) is not None:
            print("SELF-TEST FAIL: aggregation hub should be silent")
            ok = False
        # ...but a hub with no agent context must still be reported
        if hub_context_gap(hub) is None:
            print("SELF-TEST FAIL: hub without AGENTS.md/CLAUDE.md/feature_list.json "
                  "should report a context gap")
            ok = False
        # ...and must go quiet again once the context is there
        for name in ("AGENTS.md", "CLAUDE.md", "feature_list.json"):
            (hub / name).write_text("x", encoding="utf-8")
        if hub_context_gap(hub) is not None:
            print("SELF-TEST FAIL: hub with full context should be silent")
            ok = False
        # known-negative: trivial dir (no signals)
        triv = root / "triv"
        (triv / ".claude").mkdir(parents=True)
        if detect(triv) is not None:
            print("SELF-TEST FAIL: trivial project should be silent")
            ok = False
    print("SELF-TEST: PASS" if ok else "SELF-TEST: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
