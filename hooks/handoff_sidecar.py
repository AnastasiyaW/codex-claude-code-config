#!/usr/bin/env python3
"""Handoff JSON sidecar: the Closure Audit as fields next to the prose handoff.

A handoff `X.md` may have a sibling `X.json`. Prose stays the human briefing; the
sidecar is what machines read (handoff-closure-audit-guard.py validates it,
agent_roster.py prefers it). Handoffs without a sidecar keep working unchanged.

Agents do not hand-write the JSON:
  python handoff_sidecar.py write <handoff.md> --primary COMPLETE \
      --acceptance "..." --related "..." --why NONE --next "..." \
      [--unfinished "<item>" "<tracker>"]... [--status ACTIVE|CLOSED|ABANDONED] \
      [--session-id ID] [--project SLUG]
  python handoff_sidecar.py check <handoff.md|handoff.json>
Exit: 0 written/valid, 1 refused/invalid, 2 not checked (no sidecar, unreadable).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
HANDOFF_STATUSES = ("ACTIVE", "CLOSED", "ABANDONED")
PRIMARY_STATUS = r"COMPLETE|BLOCKED-[A-Z0-9_-]+|HANDOFF-NEAR-CONTEXT-LIMIT|USER-REDIRECTED"
CLOSURE_TEXT_FIELDS = ("acceptance_verified", "related_checked", "why_not_continuing")
# Folder names that are not a project: a flat handoffs/X.md and .claude/HANDOFF.md.
NOT_A_PROJECT = frozenset({"handoffs", ".claude"})

HEADING_RE = re.compile(r"^##\s+(Closure Audit|Аудит закрытия)\s*$", re.I | re.M)
NEXT_HEADING_RE = re.compile(r"^##\s+", re.M)
PRIMARY_STATUS_RE = re.compile(
    r"^\s*[-*]?\s*\**Primary request status\**\s*:\s*(" + PRIMARY_STATUS + r")\b",
    re.I | re.M,
)
TRACKER_RE = re.compile(
    r"\b(PROBLEMS\.md|feature_list\.json|issue\s*#?\d+|ticket\s*#?\d+|"
    r"backlog|task[-_ ]?inbox|DECISIONS\.md|BLOCKED-[A-Z0-9_-]+)\b",
    re.I,
)
BAD_EVASION_RE = re.compile(
    r"\b(todo later|later maybe|next session maybe|not checked|unknown|tbd|"
    r"unclear|probably done|seems done|should be fine)\b",
    re.I,
)


def sidecar_path(handoff_md: Path) -> Path:
    return handoff_md.with_suffix(".json")


def closure_section(content: str) -> str | None:
    match = HEADING_RE.search(content)
    if not match:
        return None
    next_match = NEXT_HEADING_RE.search(content, match.end())
    return content[match.start():next_match.start() if next_match else len(content)]


def prose_primary_status(md_text: str) -> str | None:
    section = closure_section(md_text)
    found = PRIMARY_STATUS_RE.search(section) if section else None
    return found.group(1).upper() if found else None


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_sidecar(data) -> list[str]:
    if not isinstance(data, dict):
        return ["sidecar must be a JSON object"]
    errors: list[str] = []
    version = data.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("session_id", "project", "next_step"):
        if not _text(data.get(key)):
            errors.append(f"{key} must be a non-empty string")
    if data.get("project") in NOT_A_PROJECT:
        errors.append(f"project {data['project']!r} is a folder name, not a project slug")
    if data.get("status") not in HANDOFF_STATUSES:
        errors.append(f"status must be one of {', '.join(HANDOFF_STATUSES)}")
    audit = data.get("closure_audit")
    if not isinstance(audit, dict):
        return errors + ["closure_audit must be an object"]
    primary = audit.get("primary_status")
    if not isinstance(primary, str) or not re.fullmatch(PRIMARY_STATUS, primary):
        errors.append("closure_audit.primary_status must be COMPLETE, BLOCKED-<REASON>, "
                      "HANDOFF-NEAR-CONTEXT-LIMIT or USER-REDIRECTED")
    for key in CLOSURE_TEXT_FIELDS:
        value = audit.get(key)
        if not _text(value):
            errors.append(f"closure_audit.{key} must be a non-empty string")
        elif bad := BAD_EVASION_RE.search(value):
            errors.append(f"closure_audit.{key} has evasive wording: {bad.group()!r}")
    unfinished = audit.get("unfinished")
    if not isinstance(unfinished, list):
        return errors + ["closure_audit.unfinished must be a list ([] when nothing is open)"]
    for i, entry in enumerate(unfinished):
        if not isinstance(entry, dict):
            errors.append(f"closure_audit.unfinished[{i}] must be an object {{item, tracker}}")
            continue
        if not _text(entry.get("item")):
            errors.append(f"closure_audit.unfinished[{i}].item must be a non-empty string")
        tracker = entry.get("tracker")
        if not _text(tracker) or not TRACKER_RE.search(tracker):
            errors.append(f"closure_audit.unfinished[{i}].tracker must cite a durable tracker "
                          "(PROBLEMS.md, feature_list.json, issue/ticket #N, backlog, task-inbox, BLOCKED-*)")
    return errors


def check_consistency(data: dict, md_text: str) -> list[str]:
    prose = prose_primary_status(md_text)
    audit = data.get("closure_audit") if isinstance(data, dict) else None
    sidecar = audit.get("primary_status") if isinstance(audit, dict) else None
    if prose is None or not isinstance(sidecar, str) or prose == sidecar.upper():
        return []
    return [f"sidecar primary_status {sidecar} contradicts the handoff's Closure Audit ({prose})"]


def load_sidecar(handoff_md: Path) -> tuple[dict | None, list[str]]:
    """(data, errors). No sidecar is (None, []); a broken one is (None, [reason])."""
    path = sidecar_path(handoff_md)
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, [f"sidecar {path.name} is not readable JSON: {exc}"]
    return data, validate_sidecar(data)


def read_valid_sidecar(handoff_md: Path) -> dict | None:
    data, errors = load_sidecar(handoff_md)
    return None if errors else data


def _cmd_write(args) -> int:
    md = Path(args.handoff)
    if md.suffix.lower() != ".md":
        print("handoff path must end in .md", file=sys.stderr)
        return 1
    if not md.is_file():
        print(f"write the handoff first: {md} does not exist", file=sys.stderr)
        return 1
    if not args.session_id and "_" not in md.stem:
        print("--session-id is required: the file name carries no session id", file=sys.stderr)
        return 1
    session_id = args.session_id or md.stem.rsplit("_", 1)[-1]
    data = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "project": args.project or md.parent.name,
        "status": args.status,
        "closure_audit": {
            "primary_status": args.primary,
            "acceptance_verified": args.acceptance,
            "related_checked": args.related,
            "unfinished": [{"item": item, "tracker": tracker} for item, tracker in args.unfinished],
            "why_not_continuing": args.why,
        },
        "next_step": args.next,
    }
    errors = validate_sidecar(data)
    errors += check_consistency(data, md.read_text(encoding="utf-8", errors="replace"))
    target = sidecar_path(md)
    # A valid sidecar naming another session_id is not replaced; a broken one may be repaired.
    existing = read_valid_sidecar(md)
    if existing and existing["session_id"] != session_id:
        errors.append(f"{target.name} belongs to session {existing['session_id']!r}; "
                      "pass that --session-id to update it")
    if errors:
        print("sidecar NOT written:\n" + "\n".join(f"  - {e}" for e in errors), file=sys.stderr)
        return 1
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    print(target)
    return 0


def _cmd_check(args) -> int:
    md = Path(args.path).with_suffix(".md")
    data, errors = load_sidecar(md)
    if data is None and not errors:
        print(f"no sidecar next to {md} (not checked)", file=sys.stderr)
        return 2
    if md.is_file():
        errors += check_consistency(data, md.read_text(encoding="utf-8", errors="replace"))
    if errors:
        print("sidecar INVALID:\n" + "\n".join(f"  - {e}" for e in errors), file=sys.stderr)
        return 1
    print(f"sidecar valid: {sidecar_path(md)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write X.json next to handoff X.md")
    w.add_argument("handoff")
    w.add_argument("--session-id")
    w.add_argument("--project")
    w.add_argument("--status", default="ACTIVE", choices=HANDOFF_STATUSES)
    w.add_argument("--primary", required=True)
    w.add_argument("--acceptance", required=True)
    w.add_argument("--related", required=True)
    w.add_argument("--why", required=True)
    w.add_argument("--next", required=True)
    w.add_argument("--unfinished", nargs=2, action="append", default=[], metavar=("ITEM", "TRACKER"))
    c = sub.add_parser("check", help="validate the sidecar of a handoff")
    c.add_argument("path")
    args = parser.parse_args(argv)
    return _cmd_write(args) if args.cmd == "write" else _cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
