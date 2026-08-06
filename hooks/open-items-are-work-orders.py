#!/usr/bin/env python3
"""UserPromptSubmit: "what is still open?" is a work order, not a status request.

Asking what is unclosed is the moment the backlog becomes visible, and the honest
response to seeing it is to close it. Left to itself the exchange goes the other way:
the agent enumerates, the user reads, the list survives the conversation intact and
grows by whatever this session adds.

So when the prompt asks that question, this hook answers it first — with the actual
open entries, oldest first, ages attached — and states the expectation that they get
closed in this turn rather than restated.

Why age is printed and the label is not trusted: measured on this hub 2026-08-05,
51 open PROBLEMS.md entries carried 27 `arch-decision` — one of the five legitimate
deferral reasons holding 53% of everything deferred. A label saying "someone must
decide" that has sat unchanged for two weeks is not a decision pending, and the only
field that says so is the date.

Context only. It never blocks and never fires on its own; it answers a question the
user actually asked.

Bypass:    CLAUDE_SKIP_OPEN_ITEMS=1
Self-test: python open-items-are-work-orders.py --self-test
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import log  # noqa: E402

MAX_LISTED = 12
STALE_DAYS = 14

# Deliberately narrow: the question about open work, not any mention of a problem.
ASKS_WHAT_IS_OPEN = re.compile(
    r"(что|чего)\s+(?:там\s+|ещё\s+|еще\s+|у\s+нас\s+)*"
    r"(не\s*(закрыт\w*|сделан\w*|доделан\w*|решен\w*|решён\w*)|"
    r"остал\w*|открыт\w*|висит|недоделан\w*)"
    r"|what(?:'s| is| are)?\s+(?:still\s+)?(open|left|outstanding|unresolved|not\s+done)"
    r"|any(?:thing)?\s+(?:still\s+)?(open|outstanding|left\s+to\s+do)"
    r"|остал(?:о|и)сь\s+ли\s+что",
    re.I | re.U,
)

HEADING_RE = re.compile(r"^##\s+(?P<date>\d{4}-\d{2}-\d{2})[^\n]*$", re.M)
STATUS_RE = re.compile(r"^\*\*Status\*\*:\s*(?P<value>.+)$", re.M)
CLOSED_RE = re.compile(r"\b(RESOLVED|CLOSED|FIXED|DONE|NOT[_ ]A[_ ]BUG|WONTFIX|ОТОЗВАНО)\b", re.I)


def strip_quotes(prompt: str) -> str:
    """Drop quoted lines before matching.

    Two of the five hits in 30 days of real messages were the user quoting a previous
    report of mine back at me — including the words "Что НЕ закрыто". Answering a
    quotation of my own output as though it were a fresh question is noise.
    """
    return "\n".join(line for line in prompt.splitlines()
                     if not line.lstrip().startswith((">", "<!--")))


def open_entries(text: str, today: _dt.date) -> list[tuple[int, str, str]]:
    """(age_days, status, heading) for every entry that is not closed, oldest first."""
    out: list[tuple[int, str, str]] = []
    heads = list(HEADING_RE.finditer(text))
    for i, match in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[match.start():end]
        status_match = STATUS_RE.search(body)
        status = status_match.group("value").strip() if status_match else "NO STATUS"
        if CLOSED_RE.search(status):
            continue
        try:
            opened = _dt.date.fromisoformat(match.group("date"))
        except ValueError:
            continue
        heading = match.group(0).lstrip("# ").strip()
        out.append(((today - opened).days, status.split()[0][:22], heading[:96]))
    out.sort(key=lambda row: -row[0])
    return out


def render(entries: list[tuple[int, str, str]]) -> str:
    if not entries:
        return "[open-items] PROBLEMS.md has nothing open. Say so plainly."
    stale = [e for e in entries if e[0] >= STALE_DAYS]
    labels: dict[str, int] = {}
    for _, status, _h in entries:
        labels[status] = labels.get(status, 0) + 1
    top_label, top_count = max(labels.items(), key=lambda kv: kv[1])

    lines = [f"[open-items] {len(entries)} open in PROBLEMS.md. These are work, not a report:"]
    for age, status, heading in entries[:MAX_LISTED]:
        lines.append(f"  {age:4d}d  [{status}]  {heading}")
    if len(entries) > MAX_LISTED:
        # Never a silent cap: a truncated list read as "that is all" is the failure
        # this whole file exists to avoid.
        lines.append(f"  ... and {len(entries) - MAX_LISTED} more, not shown; the full "
                     f"list is in PROBLEMS.md.")
    if top_count >= max(3, len(entries) // 3):
        lines.append(f"  {top_count} of {len(entries)} carry `{top_label}`. One reason "
                     f"holding that share is a label doing the work of a decision.")
    if stale:
        lines.append(f"  {len(stale)} have been open {STALE_DAYS}+ days. That is not a "
                     f"decision pending; nobody is coming to make it.")
    lines.append("  Close what you can in THIS turn and report what you closed. "
                 "Restating the list back is not an answer to the question.")
    return "\n".join(lines)


def find_problems(start: Path) -> Path | None:
    for parent in [start, *start.parents][:5]:
        candidate = parent / "PROBLEMS.md"
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    if os.environ.get("CLAUDE_SKIP_OPEN_ITEMS") == "1":
        return 0
    try:
        event = json.loads(sys.stdin.read().lstrip("﻿") or "{}")
    except ValueError:
        return 0
    prompt = str(event.get("prompt") or event.get("user_prompt") or "")
    if not prompt or not ASKS_WHAT_IS_OPEN.search(strip_quotes(prompt)):
        return 0
    cwd = Path(str(event.get("cwd") or Path.cwd()))
    problems = find_problems(cwd)
    if problems is None:
        return 0
    try:
        text = problems.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    entries = open_entries(text, _dt.date.today())
    log("INFO", "open_items", "inject", f"{len(entries)}_open", prompt[:200])
    print(render(entries))
    return 0


def self_test() -> int:
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    for phrase in ("что не закрыто?", "что осталось доделать", "а что ещё открыто",
                   "what's still open?", "anything left to do", "что у нас не сделано",
                   "осталось ли что-то"):
        check(f"triggers on {phrase!r}", bool(ASKS_WHAT_IS_OPEN.search(phrase)), True)
    for phrase in ("закрой issue 42", "почему тест не проходит", "what did you close",
                   "открой файл", "это не закрытый вопрос архитектуры — переделай"):
        check(f"stays quiet on {phrase!r}", bool(ASKS_WHAT_IS_OPEN.search(phrase)), False)
    quoted = "> Что НЕ закрыто - написала прямо, чтобы не было иллюзии готовности\nспасибо"
    check("a quotation of my own report is not a question",
          bool(ASKS_WHAT_IS_OPEN.search(strip_quotes(quoted))), False)
    check("the same words unquoted still ask",
          bool(ASKS_WHAT_IS_OPEN.search(strip_quotes("что не закрыто?"))), True)

    today = _dt.date(2026, 8, 5)
    sample = (
        "## 2026-07-01 10:00 - OLD-1: ancient\n**Status**: arch-decision\n\n"
        "## 2026-08-04 10:00 - NEW-1: fresh\n**Status**: arch-decision\n\n"
        "## 2026-08-04 11:00 - NEW-2: handled\n**Status**: RESOLVED 2026-08-05\n\n"
        "## 2026-08-05 09:00 - NEW-3: today\n**Status**: missing-data\n"
    )
    rows = open_entries(sample, today)
    ids = [re.search(r"\b([A-Z]+-\d+)\b", row[2]).group(1) for row in rows]
    check("closed entries excluded", ids, ["OLD-1", "NEW-1", "NEW-3"])
    check("oldest first", rows[0][0], 35)
    text = render(rows)
    check("says how long the oldest has waited", "35d" in text, True)
    check("names the dominant label", "arch-decision" in text, True)
    check("demands closing in this turn", "THIS turn" in text, True)
    check("empty backlog is stated plainly", "nothing open" in render([]), True)

    many = [(i, "arch-decision", f"## 2026-01-01 - X-{i}") for i in range(30)]
    check("a truncated list says so", "and 18 more" in render(many), True)

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
