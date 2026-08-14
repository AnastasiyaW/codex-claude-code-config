#!/usr/bin/env python3
"""Stop hook: require a measurement line for a narrow class of outward claims.

The hook does not try to decide whether a statement is true. It catches only
hash/size/version/deploy assertions that look externally measurable but lack an
explicit probe and result. Code inspection is not a measurement of external
state. The full policy and human-readable classifications live in
``rules/no-guessing.md``.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from safety_common import stop_budget_consume, stop_budget_exhausted
except ImportError:  # Standalone copies are advisory rather than brittle.
    stop_budget_consume = stop_budget_exhausted = None  # type: ignore[assignment]


BUDGET_NAME = "outward-claim-evidence"
META_MARKERS = ("outward-claim-evidence-guard", "measured outward facts")
EXEMPT_MARKERS = ("hypothesis", "unverified", "not measured", "не проверено", "гипотез")
EVIDENCE_MARKERS = (
    "evidence:", "proof:", "measurement:", "проверка:", "доказательство:",
    "get-filehash", "sha256sum", "certutil", "get-item", "stat ", "curl ",
    "healthcheck", "deployment", "deploy log",
)
CLAIMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sha256", re.compile(r"\bsha[- ]?256\b[^\n.]{0,160}\b(?:equals|matches|is|равен|совпада\w*)\b", re.I)),
    ("filename-hash", re.compile(r"\b(?:file ?name|filename)\b[^\n.]{0,160}\b(?:sha[- ]?256|checksum|hash)\b|\bимя файла\b[^\n.]{0,160}\b(?:sha[- ]?256|контрольн\w* сумм\w*|хеш)\b", re.I)),
    ("size", re.compile(r"\b(?:file )?size\b[^\n.]{0,120}\b(?:is|equals)\s*\d+\s*(?:bytes?|kb|mb|gb)\b|\bразмер\b[^\n.]{0,120}\b(?:равен|составляет)\s*\d+\s*(?:байт|кб|мб|гб)", re.I)),
    ("version", re.compile(r"\b(?:installed )?version\b[^\n.]{0,120}\b(?:is|equals)\s*v?\d|\bверсия\b[^\n.]{0,120}\b(?:равна|составляет)\s*v?\d", re.I)),
    ("deployment", re.compile(r"\b(?:was |is )?(?:deployed|live in production)\b|\b(?:задеплоен\w*|в проде)\b", re.I)),
)


def final_assistant_message(transcript_path: str | None) -> str:
    if not transcript_path:
        return ""
    path = Path(transcript_path)
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = record.get("message", record)
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item.get("text", "") for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
    return ""


def uncovered_claims(message: str) -> list[str]:
    lowered = message.lower()
    if any(marker in lowered for marker in META_MARKERS):
        return []
    evidence_present = any(marker in lowered for marker in EVIDENCE_MARKERS)
    hits: list[str] = []
    for name, pattern in CLAIMS:
        for match in pattern.finditer(message):
            window = lowered[max(0, match.start() - 80):match.end() + 180]
            if any(marker in window for marker in EXEMPT_MARKERS):
                continue
            if not evidence_present:
                hits.append(name)
                break
    return hits


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    transcript_path = (
        event.get("transcript_path") or event.get("transcriptPath") or event.get("transcript")
        or os.environ.get("CLAUDE_CODE_TRANSCRIPT_PATH")
    )
    message = final_assistant_message(transcript_path)
    claims = uncovered_claims(message)
    if not claims:
        return 0
    cwd = Path.cwd()
    if stop_budget_exhausted is not None and stop_budget_exhausted(BUDGET_NAME, cwd):
        return 0
    if stop_budget_consume is not None:
        stop_budget_consume(BUDGET_NAME, cwd)
    reason = (
        "Outward claim evidence guard: the final report makes a measurement-shaped "
        f"claim ({', '.join(claims)}) without a measurement/result line. Code or a "
        "filename is not proof of external state. Run the smallest sufficient probe and "
        "write `Evidence: <command or API> -> <observed result>` plus its scope; or label "
        "the statement HYPOTHESIS/BLOCKED. This guard checks reporting discipline only, "
        "not the truth of a claimed command."
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
