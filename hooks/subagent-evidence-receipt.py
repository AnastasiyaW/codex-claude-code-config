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
from pathlib import Path


BASIS_RE = re.compile(
    r"(?mi)^Decision basis:\s*(OBSERVED|PRIMARY_DOC|USER_CONSTRAINT|INCONCLUSIVE|NO_DECISION)\s*$"
)
SKILL_DISPOSITION_RE = re.compile(
    r"(?mi)^Skill disposition:[ \t]*"
    r"(USED|NO_MATCH|GAP_RESOLVED|PAUSED_BY_SKILL)(?:[ \t]+([^\r\n]+))?[ \t]*$"
)
EVIDENCE_RE = re.compile(r"(?mi)^Evidence:\s*(\S.+?)\s*$")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|(?:^|\s)[.~]?/)[^\s]+")
SKILL_NAME = r"[a-z0-9][a-z0-9:_-]*"
GAP_DETAIL_RE = re.compile(
    rf"^(?P<requested>{SKILL_NAME})\s+->\s+(?P<resolved>{SKILL_NAME})"
    r"\s*;\s*checklist=(?P<path>\S.+)$"
)
PAUSE_DETAIL_RE = re.compile(
    rf"^(?P<skill>{SKILL_NAME})\s+::\s+(?P<path>.+?SKILL\.md)"
    r"#L(?P<line>[1-9][0-9]*)\s+::\s+(?P<instruction>\S.+)$"
)
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


CHECKLIST_BOXES = (
    "Scope matches the original task without narrowing or expansion",
    "Complete SKILL.md read; task-relevant references identified and read",
    "Scripts, dependencies, hooks, tools, permissions, and side effects inspected",
    "Publisher, immutable version/SHA, activity, and license verified",
    "Prompt injection, policy conflicts, duplication, and hidden authority rejected",
    "Isolated validation/behavior check passed with evidence",
)


def _local_file(raw: str, base_dir: Path) -> tuple[Path | None, str | None]:
    value = raw.strip().strip("`'\"")
    if URL_RE.fullmatch(value):
        return None, "a local readable receipt is required; a URL alone is not proof"
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, f"receipt path is not readable: {value}"
    if not path.is_file():
        return None, f"receipt path is not a file: {value}"
    try:
        if path.stat().st_size > 131_072:
            return None, "receipt file exceeds 128 KiB"
    except OSError:
        return None, f"receipt path is not readable: {value}"
    return path, None


def _read_local(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError):
        return None, f"receipt is not readable UTF-8: {path}"


def checklist_problem(raw_path: str, requested: str, resolved: str, base_dir: Path) -> str | None:
    path, problem = _local_file(raw_path, base_dir)
    if problem:
        return problem
    assert path is not None
    text, problem = _read_local(path)
    if problem:
        return problem
    assert text is not None
    requested_match = re.search(r"(?mi)^- Requested capability:\s*(\S.*?)\s*$", text)
    candidate_match = re.search(r"(?mi)^- Candidate/source/commit:\s*(\S.*?)\s*$", text)
    decision_match = re.search(
        r"(?mi)^- Decision:\s*(USE_INSTALLED|INSTALL_PINNED|CREATE_LOCAL|REJECT)\s*$",
        text,
    )
    continuation_match = re.search(r"(?mi)^- Continuation:\s*(\S.*?)\s*$", text)
    if not requested_match or requested_match.group(1).strip() != requested:
        return "checklist Requested capability must exactly match the routed gap"
    if not candidate_match or resolved not in candidate_match.group(1):
        return "checklist Candidate/source/commit must name the accepted or created skill"
    if not decision_match or decision_match.group(1) == "REJECT":
        return "checklist needs an accepted USE_INSTALLED, INSTALL_PINNED, or CREATE_LOCAL decision"
    if not continuation_match:
        return "checklist needs the exact continuation action for the original task"
    for label in CHECKLIST_BOXES:
        if not re.search(rf"(?mi)^- \[[xX]\] {re.escape(label)}\s*$", text):
            return f"checklist box is not checked: {label}"
    return None


def pause_problem(detail: str, base_dir: Path) -> str | None:
    parsed = PAUSE_DETAIL_RE.fullmatch(detail)
    if parsed is None:
        return (
            "PAUSED_BY_SKILL must use `<skill> :: <local SKILL.md>#L<line> :: "
            "<exact instruction>`"
        )
    path, problem = _local_file(parsed.group("path"), base_dir)
    if problem:
        return problem
    assert path is not None
    if path.name != "SKILL.md":
        return "PAUSED_BY_SKILL reference must be a SKILL.md"
    text, problem = _read_local(path)
    if problem:
        return problem
    assert text is not None
    lines = text.splitlines()
    line_number = int(parsed.group("line"))
    if line_number > len(lines):
        return "PAUSED_BY_SKILL line is outside the referenced SKILL.md"
    if parsed.group("instruction").strip() != lines[line_number - 1].strip():
        return "PAUSED_BY_SKILL instruction does not match the referenced SKILL.md line"
    return None


def skill_disposition_problem(message: str, base_dir: Path | None = None) -> str | None:
    base_dir = base_dir or Path.cwd()
    match = SKILL_DISPOSITION_RE.search(message)
    if match is None:
        return "missing a valid Skill disposition receipt"
    kind = match.group(1)
    detail = (match.group(2) or "").strip()
    if kind == "NO_MATCH":
        return None if not detail else "NO_MATCH must not name a skill"
    if kind == "USED":
        return None if detail else "USED must name the applied skill"
    if kind == "PAUSED_BY_SKILL":
        return pause_problem(detail, base_dir)
    parsed = GAP_DETAIL_RE.fullmatch(detail)
    if parsed is None:
        return (
            "GAP_RESOLVED must use `<requested> -> <accepted-or-created>; "
            "checklist=<local receipt path>`"
        )
    return checklist_problem(
        parsed.group("path"), parsed.group("requested"), parsed.group("resolved"), base_dir
    )


def is_source_anchor(basis: str, evidence: str) -> bool:
    """Require a source-shaped anchor, not a merely plausible sentence."""
    if basis == "USER_CONSTRAINT":
        return bool(USER_CONSTRAINT_RE.search(evidence))
    return bool(URL_RE.search(evidence) or PATH_RE.search(evidence) or COMMAND_RE.search(evidence))


def receipt_problem(message: str, base_dir: Path | None = None) -> str | None:
    skill_problem = skill_disposition_problem(message, base_dir)
    if skill_problem is not None:
        return skill_problem
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
    event_cwd = event.get("cwd")
    base_dir = Path(str(event_cwd)) if event_cwd else Path.cwd()
    problem = receipt_problem(message, base_dir)
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
            "Before finishing, add a compact three-line receipt: `Skill disposition: "
            "USED <skill(s)> | NO_MATCH | GAP_RESOLVED <requested> -> "
            "<accepted-or-created>; checklist=<local checked receipt path> | "
            "PAUSED_BY_SKILL <skill> :: <local SKILL.md>#L<line> :: "
            "<exact instruction>`, `Decision basis: OBSERVED | "
            "PRIMARY_DOC | USER_CONSTRAINT | INCONCLUSIVE | NO_DECISION` and "
            "`Evidence: <current command/path/URL, or N/A only for NO_DECISION>`. "
            + problem
        ),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
