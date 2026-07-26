#!/usr/bin/env python3
"""SessionStart hook: check for handoffs from previous sessions.

Runs at the start of every Claude Code session. If recent handoff files
exist, prints the latest one per project so the agent sees them and can
offer to continue.

Handoff layout (v2, per-project):
    .claude/handoffs/<project-slug>/YYYY-MM-DD_HH-MM_<session-id>.md
    .claude/handoffs/INDEX.md   (single append-only index, all projects)

Legacy layouts still supported: flat .claude/handoffs/*.md (grouped under
"(no-project)") and single .claude/HANDOFF.md. The global store
~/.claude/handoffs/ is also scanned so handoffs written there by older
rules remain visible.

Register in ~/.claude/settings.json:
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "python path/to/session-handoff-check.py",
        "statusMessage": "Checking for handoffs..."
      }]
    }]
  }
}
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# How many projects to show (latest handoff per project, full content)
MAX_PROJECTS = 3
# After a compaction the session is mid-work, not starting: re-inject only the
# thread that was actually being worked on. Dumping every project's handoff
# right after the context was squeezed spends the space compaction just freed.
MAX_PROJECTS_AFTER_COMPACT = 1
# Only show handoffs newer than this (hours)
MAX_AGE_HOURS = 168  # 7 days

# YYYY-MM-DD_HH-MM prefix in handoff filenames
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:_(\d{2})-(\d{2}))?")


def file_timestamp(path: Path) -> float:
    """Timestamp from the filename prefix; fall back to mtime.

    The filename is authoritative: mtime drifts when a handoff is edited
    later (status updates, resolutions) or when files are copied.
    """
    m = TS_RE.match(path.name)
    if m:
        try:
            hh = int(m.group(2)) if m.group(2) else 0
            mm = int(m.group(3)) if m.group(3) else 0
            dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(hour=hh, minute=mm)
            return dt.timestamp()
        except ValueError:
            pass
    return path.stat().st_mtime


def scan_store(root: Path, store_label: str, now: float) -> list[dict]:
    """Collect recent handoffs from one store (flat files + project subdirs)."""
    found: list[dict] = []
    if not root.exists():
        return found
    for p in root.rglob("*.md"):
        rel = p.relative_to(root)
        if p.name.startswith("INDEX") or "archive" in rel.parts:
            continue
        ts = file_timestamp(p)
        if (now - ts) / 3600 > MAX_AGE_HOURS:
            continue
        project = rel.parts[0] if len(rel.parts) > 1 else "(no-project)"
        found.append(
            {"ts": ts, "path": p, "project": project, "store": store_label}
        )
    return found


def read_source() -> str:
    """SessionStart `source`: startup | resume | clear | compact.

    Reads the event JSON from stdin. Guarded by an isatty check so a manual
    terminal run cannot block waiting for input, and fails open to "" so a
    malformed event only costs the compact-specific behaviour.
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        raw = sys.stdin.read().lstrip(chr(0xFEFF)).strip()
        if not raw:
            return ""
        return str(json.loads(raw).get("source", "") or "")
    except (json.JSONDecodeError, OSError, ValueError):
        return ""


def main() -> int:
    cwd = Path.cwd()
    claude_dir = cwd / ".claude"
    source = read_source()
    after_compact = source == "compact"

    # Reset per-session markers (so Stop hook can remind again this session)
    if claude_dir.exists():
        for marker in (".handoff-reminded", ".session-start", ".stop-phrase-guard-fired"):
            m = claude_dir / marker
            if m.exists():
                m.unlink()
        # Stop-gate rejection budgets (safety_common.stop_budget_*) are
        # per-session: clear them so every gate starts with a full budget.
        for budget in claude_dir.glob(".stop-budget-*"):
            try:
                budget.unlink()
            except OSError:
                pass
        # Re-create session-start marker with current time
        (claude_dir / ".session-start").touch()

    lines: list[str] = []

    # Surface PreCompact marker (set by precompact-handoff-guard.py when the
    # context was compacted without a fresh handoff). Runs here because
    # SessionStart also fires with source=compact right after auto-compaction.
    precompact_marker = claude_dir / ".precompact-handoff-needed"
    if precompact_marker.exists():
        try:
            info = precompact_marker.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            info = ""
        lines.append("=" * 60)
        lines.append("WARNING: context was COMPACTED without a fresh handoff.")
        lines.append("=" * 60)
        if info:
            lines.append(f"marker: {info}")
        lines.append(
            "INSTRUCTION: Before any other work, write a handoff to "
            ".claude/handoffs/<project-slug>/YYYY-MM-DD_HH-MM_<session-short-id>.md "
            "(format in .claude/rules/session-handoff.md; <=1500 tokens) and "
            "append one line to .claude/handoffs/INDEX.md. This is the "
            "near-overflow exception in finish-the-task.md."
        )
        lines.append("")
        try:
            precompact_marker.unlink()
        except Exception:
            pass

    now = time.time()
    found: list[dict] = []

    # Project-local store (canonical), then the global store written by
    # older rules — kept visible so nothing is operationally absent.
    local_store = (claude_dir / "handoffs").resolve()
    found.extend(scan_store(local_store, "project", now))
    global_store = (Path.home() / ".claude" / "handoffs").resolve()
    if global_store != local_store:
        found.extend(scan_store(global_store, "global", now))

    # Fallback: old single HANDOFF.md
    handoff_old = claude_dir / "HANDOFF.md"
    if not found and handoff_old.exists():
        age_hours = (now - handoff_old.stat().st_mtime) / 3600
        if age_hours <= MAX_AGE_HOURS:
            found.append(
                {
                    "ts": handoff_old.stat().st_mtime,
                    "path": handoff_old,
                    "project": "(no-project)",
                    "store": "project",
                }
            )

    if found:
        # Group by project; show the newest handoff per project,
        # projects ordered by their newest handoff.
        groups: dict[str, list[dict]] = {}
        for h in found:
            groups.setdefault(h["project"], []).append(h)
        for items in groups.values():
            items.sort(key=lambda h: h["ts"], reverse=True)
        ordered = sorted(groups.items(), key=lambda kv: kv[1][0]["ts"], reverse=True)
        limit = MAX_PROJECTS_AFTER_COMPACT if after_compact else MAX_PROJECTS
        shown = ordered[:limit]
        rest = ordered[limit:]

        lines.append("=" * 60)
        if after_compact:
            lines.append(
                f"POST-COMPACT STATE RE-INJECT - newest handoff of "
                f"{len(groups)} project(s) with recent work"
            )
        else:
            lines.append(
                f"SESSION HANDOFF(S) - {len(found)} found across "
                f"{len(groups)} project(s), showing latest per project"
            )
        lines.append("=" * 60)

        for project, items in shown:
            top = items[0]
            ts_str = datetime.fromtimestamp(top["ts"]).strftime("%Y-%m-%d %H:%M")
            extra = f", {len(items) - 1} older" if len(items) > 1 else ""
            lines.append(
                f"\n--- [{project}] {ts_str} · {top['path'].name} "
                f"({top['store']} store{extra}) ---"
            )
            lines.append(
                top["path"].read_text(encoding="utf-8", errors="replace")
            )

        if rest:
            lines.append("")
            lines.append("Other projects with recent handoffs (see INDEX.md):")
            for project, items in rest:
                ts_str = datetime.fromtimestamp(items[0]["ts"]).strftime("%Y-%m-%d %H:%M")
                lines.append(f"  - {project}: {len(items)} handoff(s), latest {ts_str}")

        lines.append("=" * 60)
        lines.append("")
        if after_compact:
            lines.append(
                "INSTRUCTION: The context was just compacted mid-session — this "
                "is state re-injection, not a session start. Resume the work "
                "described above from where it stopped. Do NOT ask the user "
                "which handoff to continue, and do NOT re-summarise the "
                "handoff back to them."
            )
        else:
            lines.append(
                "INSTRUCTION: List the handoff(s) briefly to the user "
                "(project, timestamp, session ID, topic). Ask if they want to "
                "continue one of them or start fresh."
            )
        lines.append("")

    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
