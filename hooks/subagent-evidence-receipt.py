#!/usr/bin/env python3
"""Codex SubagentStop: require one structured decision-source receipt.

This is deliberately a narrow receipt check, not a natural-language fact
checker. Codex exposes the subagent's final message at SubagentStop, so the
hook can require an explicit basis and evidence anchor before accepting a
conclusion. It cannot establish that a cited web page or command is truthful;
the parent and task-specific validators remain responsible for that proof.
"""
from __future__ import annotations

import json
import re
import sys


BASIS_RE = re.compile(
    r"(?mi)^Decision basis:\s*(OBSERVED|PRIMARY_DOC|USER_CONSTRAINT|INCONCLUSIVE|NO_DECISION)\s*$"
)
EVIDENCE_RE = re.compile(r"(?mi)^Evidence:\s*(\S.+?)\s*$")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|(?:^|\s)[.~]?/)[^\s]+")
COMMAND_RE = re.compile(
    r"\b(?:python(?:3)?|git|rg|pytest|curl|powershell|Get-[A-Za-z]+|"
    r"Test-[A-Za-z]+|Invoke-[A-Za-z]+|docker|systemctl|npm|uv|cargo|go|make)\b",
    re.IGNORECASE,
)
USER_CONSTRAINT_RE = re.compile(
    r"\buser\s+(?:request|message|constraint|instruction)\s*:", re.IGNORECASE
)
STALE_LEAD_RE = re.compile(
    r"\b(?:memory|remember|prior|previous|earlier|assistant|chat)\b", re.IGNORECASE
)


def is_source_anchor(basis: str, evidence: str) -> bool:
    """Require a source-shaped anchor, not a merely plausible sentence."""
    if basis == "USER_CONSTRAINT":
        return bool(USER_CONSTRAINT_RE.search(evidence))
    return bool(URL_RE.search(evidence) or PATH_RE.search(evidence) or COMMAND_RE.search(evidence))


def receipt_problem(message: str) -> str | None:
    basis = BASIS_RE.search(message)
    if basis is None:
        return "missing a valid Decision basis receipt"
    evidence = EVIDENCE_RE.search(message)
    if evidence is None:
        return "missing an Evidence receipt"
    value = evidence.group(1).strip()
    if basis.group(1) == "NO_DECISION":
        if value != "N/A":
            return "NO_DECISION must use Evidence: N/A"
        return None
    if value == "N/A":
        return "a factual decision needs a current evidence anchor"
    lowered = value.casefold()
    if STALE_LEAD_RE.search(lowered):
        return "memory or prior assistant text is not a decision basis"
    if not is_source_anchor(basis.group(1), value):
        if basis.group(1) == "USER_CONSTRAINT":
            return "USER_CONSTRAINT needs `Evidence: user request: <exact constraint>`"
        return "Evidence needs a current command, filesystem path, or primary-document URL"
    return None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read().lstrip("\ufeff"))
    except (json.JSONDecodeError, EOFError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "SubagentStop":
        return 0
    message = str(event.get("last_assistant_message") or "")
    problem = receipt_problem(message)
    if problem is None:
        return 0
    if event.get("stop_hook_active"):
        print(json.dumps({
            "systemMessage": "Subagent ended without a valid decision-source receipt after one repair pass: " + problem,
        }, ensure_ascii=False))
        return 0
    print(json.dumps({
        "decision": "block",
        "reason": (
            "Before finishing, add a compact receipt: `Decision basis: OBSERVED | "
            "PRIMARY_DOC | USER_CONSTRAINT | INCONCLUSIVE | NO_DECISION` and "
            "`Evidence: <current command/path/URL, or N/A only for NO_DECISION>`. "
            + problem
        ),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
