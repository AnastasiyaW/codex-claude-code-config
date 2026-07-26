#!/usr/bin/env python3
"""Stop hook: validate PROBLEMS.md status discipline.

Companion to test-gate-stop-hook.py and stop-phrase-guard.py. Implements
Layer 4 of the no-pre-existing-evasion stack: when an agent finds a bug
mid-task and decides to defer, that decision must land in PROBLEMS.md
with one of five explicit reasons - not as silent abandonment.

This hook validates that every entry in PROBLEMS.md has a Status field
and the value is one of:

- A 5-exception status (open with reason): missing-data, missing-dep,
  arch-decision, scope-explosion, inaccessible-repo
- A resolution: RESOLVED, WORKAROUND, NOT_A_BUG, CLOSED
- A specific blocker: BLOCKED-<thing> (e.g. BLOCKED-ON-CREDS)

Plain `OPEN` with no further qualification is rejected: it is the
cardinal sin of agent laziness ("I noticed but did nothing").

## What counts as an entry

Only `## YYYY-MM-DD ...` headings are treated as problem entries.
Section headings like `## Open`, `## Resolved`, `## Workarounds` (which
the long-running-projects pattern recommends as group containers) are
correctly ignored.

## Behaviour

- All entries valid → silent pass
- One or more invalid → emit JSON `{"decision": "block", "reason": "..."}`
  with line numbers and headings, plus instructions
- `stop_hook_active=true` → silent pass (anti-loop, REQUIRED)
- No PROBLEMS.md found → silent pass (graceful, file is opt-in)

## Bypass

- env var `CLAUDE_SKIP_PROBLEMS_CHECK=1`
- file `.claude/.skip-problems-check` (project-level)

## Register

```json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python path/to/problems-md-validator.py",
        "statusMessage": "PROBLEMS.md validation..."
      }]
    }]
  }
}
```

Order in `Stop[].hooks[]` does not matter functionally - all hooks run -
but for human-readable status messages put structural gates (test, problems)
before reminders (handoff, cleanup).

## Reference

- Principle 26: docs/principles/26-no-pre-existing-evasion.md
- bradfeld "fix or ticket" with 5 valid exceptions (accept no others)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from safety_common import (  # noqa: E402
        stop_budget_consume,
        stop_budget_exhausted,
        untrusted_block,
    )
except ImportError:  # fail-open: keep the original one-shot behaviour
    stop_budget_consume = stop_budget_exhausted = untrusted_block = None  # type: ignore[assignment]

# Gate name for the shared Stop-hook rejection budget (safety_common).
BUDGET_NAME = "problems-md"

VALID_5_EXCEPTIONS = {
    "missing-data",
    "missing-dep",
    "arch-decision",
    "scope-explosion",
    "inaccessible-repo",
}
RESOLVED_STATES = {
    "RESOLVED",
    "WORKAROUND",
    "NOT_A_BUG",
    "CLOSED",
}

STATUS_LINE_RE = re.compile(
    r"^\s*\**\s*Status\s*\**\s*:\s*([A-Za-z0-9_\-]+)",
    re.IGNORECASE | re.MULTILINE,
)
# Real entries start with a date; pure section headings are not entries.
ENTRY_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def find_problems_md(cwd: Path) -> Path | None:
    candidates = [
        cwd / "PROBLEMS.md",
        cwd / ".claude" / "PROBLEMS.md",
        cwd / "GOTCHAS.md",
        cwd / ".claude" / "GOTCHAS.md",
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def parse_problems(content: str) -> list[dict]:
    entries = []
    lines = content.split("\n")
    heading_idxs = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    heading_idxs.append(len(lines))

    for k in range(len(heading_idxs) - 1):
        start = heading_idxs[k]
        end = heading_idxs[k + 1]
        heading = lines[start].lstrip("#").strip()

        if not ENTRY_DATE_RE.match(heading):
            continue

        body = "\n".join(lines[start:end])
        m = STATUS_LINE_RE.search(body)
        status = m.group(1).strip() if m else None

        entries.append({
            "heading": heading,
            "status": status,
            "body": body,
            "line": start + 1,
        })

    return entries


def validate_entry(entry: dict) -> tuple[bool, str]:
    status = entry["status"]
    if status is None:
        return (False, f"line {entry['line']} '{entry['heading'][:60]}': missing 'Status:' field")

    status_norm = status.lower().replace("_", "-")

    if status_norm == "open":
        return (False,
                f"line {entry['line']} '{entry['heading'][:60]}': STATUS: OPEN without 5-exception. "
                f"Need one of: missing-data, missing-dep, arch-decision, scope-explosion, inaccessible-repo. "
                f"Or fix it now and change to RESOLVED.")

    if status_norm in VALID_5_EXCEPTIONS:
        return (True, "")

    if status.upper() in RESOLVED_STATES:
        return (True, "")

    if status_norm.startswith("blocked-"):
        return (True, "")

    return (False,
            f"line {entry['line']} '{entry['heading'][:60]}': unrecognized status "
            f"'{str(status)[:40]}'. "
            f"Use OPEN+5-exception, RESOLVED, WORKAROUND, NOT_A_BUG, or BLOCKED-<thing>.")


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return 0

    # Anti-loop with a budget, not a one-shot surrender (safety_common).
    if event.get("stop_hook_active"):
        if stop_budget_exhausted is None or stop_budget_exhausted(BUDGET_NAME):
            return 0

    if os.environ.get("CLAUDE_SKIP_PROBLEMS_CHECK"):
        return 0

    cwd = Path.cwd()

    if (cwd / ".claude" / ".skip-problems-check").exists():
        return 0

    problems_path = find_problems_md(cwd)
    if problems_path is None:
        return 0

    try:
        content = problems_path.read_text(encoding="utf-8")
    except OSError:
        return 0

    entries = parse_problems(content)
    if not entries:
        return 0

    invalid = [reason for entry in entries
               for ok, reason in [validate_entry(entry)] if not ok]

    if not invalid:
        return 0

    rel_path = problems_path.relative_to(cwd) if cwd in problems_path.parents else problems_path
    # Each line quotes a heading and status straight out of PROBLEMS.md, so the
    # listing is framed as data: the file must not be able to address the agent
    # through the block reason.
    detail = "".join(f"  - {line}\n" for line in invalid[:6])
    if len(invalid) > 6:
        detail += f"  ... and {len(invalid) - 6} more\n"
    if untrusted_block is not None:
        detail = untrusted_block(detail.rstrip("\n"), "quoted from PROBLEMS.md")

    reason = (
        f"PROBLEMS.md ({rel_path}) has {len(invalid)} invalid entries. "
        f"Per no-pre-existing-evasion rule: every problem entry must have explicit Status. "
        f"OPEN allowed only with one of 5 exceptions.\n\n"
        f"Invalid entries:\n{detail}\n"
    )

    reason += (
        f"\nTo unblock:\n"
        f"1. Fix the OPEN items now (preferred)\n"
        f"2. Change status to RESOLVED if already fixed\n"
        f"3. Specify 5-exception: change 'OPEN' to one of: "
        f"missing-data, missing-dep, arch-decision, scope-explosion, inaccessible-repo\n"
        f"4. Bypass for emergency: CLAUDE_SKIP_PROBLEMS_CHECK=1"
    )

    if stop_budget_consume is not None:
        stop_budget_consume(BUDGET_NAME)
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
