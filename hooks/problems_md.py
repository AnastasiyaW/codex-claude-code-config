"""PROBLEMS.md: the one parser and the one set of status values.

PROBLEMS.md stays markdown for humans. problems-md-validator.py (Stop) and
handoff-closure-audit-guard.py (today's open tickets) both read entries here,
so a status value means the same thing to both.
"""
from __future__ import annotations

import re

DEFERRAL_ORDER = ("missing-data", "missing-dep", "arch-decision", "scope-explosion", "inaccessible-repo")
DEFERRAL_REASONS = frozenset(DEFERRAL_ORDER)
RESOLVED_STATES = frozenset({"RESOLVED", "WORKAROUND", "NOT_A_BUG", "CLOSED"})
# Closed for the handoff guard: an entry it no longer asks the session to mention.
# WORKAROUND is a valid status but the problem is still there, so it stays open here.
CLOSED_STATUS_RE = re.compile(r"\b(RESOLVED|CLOSED|FIXED|DONE|NOT[_ ]A[_ ]BUG|WONTFIX|ОТОЗВАНО)\b", re.I)

ENTRY_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
STATUS_LINE_RE = re.compile(r"^\s*\**\s*Status\s*\**\s*:\s*(?P<line>[^\n]*)$", re.I | re.M)
STATUS_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+")


def parse_entries(content: str) -> list[dict]:
    """Entries are `## YYYY-MM-DD ...` sections; `## Open`-style group headings are not."""
    entries = []
    lines = content.split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")] + [len(lines)]
    for k in range(len(starts) - 1):
        heading = lines[starts[k]].lstrip("#").strip()
        date = ENTRY_DATE_RE.match(heading)
        if not date:
            continue
        body = "\n".join(lines[starts[k]:starts[k + 1]])
        found = STATUS_LINE_RE.search(body)
        status_line = found.group("line").strip() if found else ""
        token = STATUS_TOKEN_RE.match(status_line)
        entries.append({
            "heading": heading,
            "date": date.group(),
            "status": token.group() if token else None,
            "status_line": status_line,
            "body": body,
            "line": starts[k] + 1,
        })
    return entries


def is_closed(status_line: str) -> bool:
    return bool(CLOSED_STATUS_RE.search(status_line))


def validate_entry(entry: dict) -> tuple[bool, str]:
    status = entry["status"]
    where = f"line {entry['line']} '{entry['heading'][:60]}'"
    if status is None:
        return (False, f"{where}: missing 'Status:' field")
    norm = status.lower().replace("_", "-")
    if norm == "open":
        return (False,
                f"{where}: STATUS: OPEN without 5-exception. "
                f"Need one of: {', '.join(DEFERRAL_ORDER)}. "
                f"Or fix it now and change to RESOLVED.")
    if norm in DEFERRAL_REASONS or status.upper() in RESOLVED_STATES or norm.startswith("blocked-"):
        return (True, "")
    return (False,
            f"{where}: unrecognized status '{status[:40]}'. "
            f"Use OPEN+5-exception, RESOLVED, WORKAROUND, NOT_A_BUG, or BLOCKED-<thing>.")
