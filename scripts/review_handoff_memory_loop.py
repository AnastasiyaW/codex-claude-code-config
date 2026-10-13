#!/usr/bin/env python3
"""Review the handoff -> hook -> memory feedback loop.

This is a deterministic hub health check. It verifies that:
- Codex/Claude hook wiring still contains handoff and compaction hooks.
- Handoff files are indexed and latest project handoffs are audited for the
  current required sections.
- Recent ad-hoc memory notes exist and include the finish/handoff closure rules.
- The loop emits a durable JSON report for future agents.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_HANDOFF_SECTIONS = (
    "## Goal",
    "## What was done",
    "## What did NOT work",
    "## Current state",
    "## Key decisions",
    "## Single next step",
)
HANDOFF_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_.+\.md$")

REQUIRED_HOOK_KEYWORDS = (
    "session-handoff-check.py",
    "precompact-handoff-guard.py",
    "session-handoff-reminder.py",
)

REQUIRED_MEMORY_NOTES = (
    "handoff-unfinished-work",
    "finish-all-tasks-to-completion",
)

MEMORY_REGISTRY_PATTERNS = {
    "handoff-unfinished-work": (
        "handoff must preserve unfinished work",
        "unfinished related task",
        "unfinished list",
    ),
    "finish-all-tasks-to-completion": (
        "finish every task to full completion",
        "full reachable result",
        "finish implementation verification documentation",
    ),
}

MEMORY_NOTE_PATTERNS = {
    "handoff-unfinished-work": (
        "explicitly list every known unfinished related task",
        "finish reversible and reachable related work before writing the handoff",
        "blocked with the exact evidence",
    ),
    "finish-all-tasks-to-completion": (
        "carry it through to the full reachable result",
        "finish implementation verification documentation",
        "do not leave adjacent required tasks implicit",
    ),
}

CANONICAL_HANDOFF_SECTIONS = {
    "goal": "## Goal",
    "what was done": "## What was done",
    "what did not work": "## What did NOT work",
    "current state": "## Current state",
    "key decisions": "## Key decisions",
    "single next step": "## Single next step",
}

CANONICAL_HANDOFF_SECTION_ALIASES = {
    "what was done": {
        "done",
        "done verified",
        "done this session",
        "done this session all deployed live verified",
    },
    "what did not work": {
        "not yet confirmed open",
        "what did not close",
        "what did not work fixed",
        "what did not work gotchas",
        "what did not work notes",
        "what did not work reasons",
    },
    "current state": {
        "what is running now",
        "current state running",
        "current status",
        "state",
    },
    "single next step": {
        "next actions",
        "next step",
        "next step in priority order",
        "next step optional nothing critical pending",
        "watch next",
    },
}


@dataclass
class Finding:
    level: str
    area: str
    message: str
    path: str | None = None


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def normalize_heading(value: str) -> str:
    value = re.sub(r"[*_`]+", "", value).strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def handoff_missing_sections(text: str) -> list[str]:
    headings = {
        normalize_heading(match.group(1))
        for match in re.finditer(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", text, flags=re.MULTILINE)
    }
    missing = []
    for key, label in CANONICAL_HANDOFF_SECTIONS.items():
        accepted = {key, *CANONICAL_HANDOFF_SECTION_ALIASES.get(key, set())}
        if not any(heading == item or heading.startswith(f"{item} ") for heading in headings for item in accepted):
            missing.append(label)
    return missing


def check_hooks(hooks_path: Path, findings: list[Finding]) -> dict:
    result = {
        "path": str(hooks_path),
        "exists": hooks_path.exists(),
        "json_ok": False,
        "required_keywords": {},
    }
    if not hooks_path.exists():
        findings.append(Finding("fail", "hooks", "hooks.json is missing", str(hooks_path)))
        return result

    raw = read_text(hooks_path)
    if "codex_hook_dispatch.py" in raw:   # one dispatcher entry per event: the handlers live in hooks.dispatch.json
        dispatch = hooks_path.with_name("hooks.dispatch.json")
        if not dispatch.exists():
            findings.append(Finding("fail", "hooks", "hooks.json uses the dispatcher but hooks.dispatch.json is missing", str(dispatch)))
            return result
        raw = read_text(dispatch)
        result["dispatch"] = str(dispatch)
    try:
        json.loads(raw)
        result["json_ok"] = True
    except json.JSONDecodeError as exc:
        findings.append(Finding("fail", "hooks", f"hooks.json is not valid JSON: {exc}", str(hooks_path)))

    for keyword in REQUIRED_HOOK_KEYWORDS:
        present = keyword in raw
        result["required_keywords"][keyword] = present
        if not present:
            findings.append(Finding("fail", "hooks", f"required hook keyword missing: {keyword}", str(hooks_path)))
    return result


LEGACY_INDEX_CUTOFF = "2026-06-20"


def is_accepted_legacy_index_line(line: str) -> bool:
    """Accept known pre-canonical index formats without weakening new records.

    The hub used several pipe-delimited layouts before the canonical
    ``date time | session | project | summary | status`` record was adopted.
    Old history remains useful and should not create permanent health warnings,
    while records on or after the cutoff must use the modern parser below.
    """
    candidate = line.strip().lstrip("-").strip().strip("|").strip()
    parts = [part.strip() for part in candidate.split("|")]
    if len(parts) < 4:
        return False
    date_match = re.match(r"(?P<date>\d{4}-\d{2}-\d{2})(?:\s+[^|]+)?$", parts[0])
    return bool(date_match and date_match.group("date") < LEGACY_INDEX_CUTOFF)


def parse_index(index_path: Path, findings: list[Finding]) -> list[dict]:
    entries: list[dict] = []
    if not index_path.exists():
        findings.append(Finding("fail", "handoffs", "handoff INDEX.md is missing", str(index_path)))
        return entries

    pattern = re.compile(
        r"^-?\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}[:-]\d{2})\s+\|\s+"
        r"(?P<session>[^|]+)\|\s+(?P<project>[^|]+)\|\s+(?P<summary>[^|]+)\|\s+(?P<status>.+)$"
    )
    for lineno, line in enumerate(read_text(index_path).splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = pattern.match(stripped)
        if not match:
            if is_accepted_legacy_index_line(stripped):
                continue
            findings.append(Finding("warn", "handoffs", f"unparseable INDEX line {lineno}: {stripped}", str(index_path)))
            continue
        entry = match.groupdict()
        entry["line"] = lineno
        entries.append(entry)
    return entries


def check_handoff_files(root: Path, findings: list[Finding], strict_legacy: bool = False) -> dict:
    handoff_root = root / ".claude" / "handoffs"
    index_path = handoff_root / "INDEX.md"
    entries = parse_index(index_path, findings)
    files = sorted(
        p
        for p in handoff_root.glob("*/*.md")
        if HANDOFF_FILENAME_RE.fullmatch(p.name)
    )
    latest_by_project: dict[str, Path] = {}
    for path in files:
        project = path.parent.name
        current = latest_by_project.get(project)
        # Git checkout time is not handoff time. The canonical filename begins
        # with an ISO date/time, so lexical order is stable across clones.
        if current is None or path.name > current.name:
            latest_by_project[project] = path

    checked_latest: dict[str, dict] = {}
    for project, path in sorted(latest_by_project.items()):
        text = read_text(path)
        missing = handoff_missing_sections(text)
        status_match = re.search(r"\*\*Status:\*\*\s*(.+)", text)
        checked_latest[project] = {
            "file": rel(path, root),
            "status": status_match.group(1).strip() if status_match else None,
            "missing_sections": missing,
            "is_auto_draft": "AUTO-DRAFT" in text[:500] or project == "codex-auto",
        }
        if project != "codex-auto" and missing:
            level = "fail" if strict_legacy else "warn"
            findings.append(
                Finding(
                    level,
                    "handoffs",
                    f"latest handoff for {project} is missing required sections: {', '.join(missing)}",
                    str(path),
                )
            )

    if not entries:
        findings.append(Finding("fail", "handoffs", "handoff index has no parseable entries", str(index_path)))

    if not files:
        findings.append(Finding("fail", "handoffs", "no handoff files found", str(handoff_root)))

    non_auto_projects = [p for p, v in checked_latest.items() if p != "codex-auto" and not v["is_auto_draft"]]
    if not non_auto_projects:
        findings.append(Finding("fail", "handoffs", "no non-auto latest project handoff found", str(handoff_root)))

    return {
        "root": str(handoff_root),
        "index_entries": len(entries),
        "handoff_files": len(files),
        "projects": len(latest_by_project),
        "latest_by_project": checked_latest,
    }


def check_memory(memory_base: Path, root: Path, findings: list[Finding]) -> dict:
    notes_dir = memory_base / "extensions" / "ad_hoc" / "notes"
    result = {
        "memory_base": str(memory_base),
        "notes_dir": str(notes_dir),
        "notes_dir_exists": notes_dir.exists(),
        "required_notes": {},
        "recent_notes": [],
    }
    if not notes_dir.exists():
        findings.append(Finding("fail", "memory", "ad_hoc memory notes directory is missing", str(notes_dir)))
        return result

    notes = sorted(notes_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    result["recent_notes"] = [str(p) for p in notes[:10]]

    memory_md = memory_base / "MEMORY.md"
    result["memory_md_exists"] = memory_md.exists()
    memory_registry = normalize_heading(read_text(memory_md)) if memory_md.exists() else ""

    names = [p.name for p in notes]
    for slug in REQUIRED_MEMORY_NOTES:
        matched_paths = [p for p in notes if slug in p.name]
        matched = [p.name for p in matched_paths]
        registry_visible = any(normalize_heading(pattern) in memory_registry for pattern in MEMORY_REGISTRY_PATTERNS[slug])
        note_text = "\n".join(read_text(p) for p in matched_paths)
        note_text_norm = normalize_heading(note_text)
        note_content_ok = any(normalize_heading(pattern) in note_text_norm for pattern in MEMORY_NOTE_PATTERNS[slug])
        result["required_notes"][slug] = {
            "files": matched,
            "note_content_ok": note_content_ok,
            "registry_visible": registry_visible,
        }
        if not matched:
            findings.append(Finding("fail", "memory", f"required ad-hoc memory note missing: {slug}", str(notes_dir)))
        elif not note_content_ok:
            findings.append(Finding("fail", "memory", f"required ad-hoc memory note content is incomplete: {slug}", str(notes_dir)))

    if not memory_md.exists():
        findings.append(Finding("warn", "memory", "MEMORY.md registry is missing", str(memory_md)))

    return result


def write_report(reports_dir: Path, payload: dict) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = reports_dir / f"{stamp}.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path = reports_dir / "latest.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Hub root")
    parser.add_argument("--memory-base", default=str(Path.home() / ".codex" / "memories"))
    parser.add_argument("--hooks", default=str(Path.home() / ".codex" / "hooks.json"))
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="Runtime report directory (default: <root>/reports/handoff-memory-loop).",
    )
    parser.add_argument(
        "--strict-legacy",
        action="store_true",
        help="Fail when existing latest handoffs do not match the current canonical section format.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    memory_base = Path(args.memory_base).resolve()
    hooks_path = Path(args.hooks).resolve()
    findings: list[Finding] = []

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "hooks": check_hooks(hooks_path, findings),
        "handoffs": check_handoff_files(root, findings, strict_legacy=args.strict_legacy),
        "memory": check_memory(memory_base, root, findings),
        "findings": [asdict(f) for f in findings],
    }
    payload["summary"] = {
        "fail": sum(1 for f in findings if f.level == "fail"),
        "warn": sum(1 for f in findings if f.level == "warn"),
        "pass": not any(f.level == "fail" for f in findings),
    }

    if args.write_report:
        reports_dir = args.report_dir or (root / "reports" / "handoff-memory-loop")
        payload["report_path"] = str(write_report(reports_dir, payload))

    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    if findings:
        for finding in findings:
            print(f"[{finding.level.upper()}] {finding.area}: {finding.message}")
            if finding.path:
                print(f"  {finding.path}")
    return 0 if payload["summary"]["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
