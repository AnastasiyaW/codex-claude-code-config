#!/usr/bin/env python3
"""PostToolUse: a handoff written for a project tracked in «Личное → Проекты» is attached to its task.

Long-running projects are tasks of the «Проекты» list in the owner's to-do (a Vikunja-backed
todo-widget with a todo.py CLI). A task's note binds it to handoff folders (`Проект: <slug>`). When an agent
writes `.claude/handoffs/<slug>/<file>.md`, this hook runs `todo.py handoff <file>`, which attaches
the file to the bound task with its status/next step as the feed comment. The owner sees the
course of work on the task; a new chat resumes with `todo.py resume "<task title>"`.

Exit codes of todo.py: 0 attached (or identical copy already there), 1 slug not bound — old
per-folder handoffs stay as they are, silently; 2 not checked (no key / network) — said aloud,
because a missing attachment must not look like a delivered one.

Advisory only, never blocks. CLI path: env TODO_WIDGET_CLI (set in the private settings.json
"env"); unset = the to-do is not installed on this machine, the hook does nothing.
Self-test: python handoff-to-todo.py --self-test
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TIMEOUT_S = 25


def handoff_path(event: dict) -> Path | None:
    raw = (event.get("tool_input") or {}).get("file_path") or ""
    if not raw:
        return None
    p = Path(raw)
    parts = [x.casefold() for x in p.parts]
    if p.suffix.lower() != ".md" or p.name.upper().startswith("INDEX") or len(parts) < 4:
        return None
    if parts[-3] != "handoffs" or parts[-4] != ".claude" or parts[-2] in ("archive", "handoff-history"):
        return None
    return p


def _say(text: str) -> None:
    out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}
    print(json.dumps(out, ensure_ascii=False))


def main() -> int:
    try:
        event = json.loads(sys.stdin.read().lstrip("\ufeff") or "{}")
    except json.JSONDecodeError as exc:
        print(f"[handoff-to-todo] event did not parse, nothing checked: {exc}", file=sys.stderr)
        return 0
    path = handoff_path(event if isinstance(event, dict) else {})
    if path is None:
        return 0
    if not os.environ.get("TODO_WIDGET_CLI"):
        return 0
    cli = Path(os.environ["TODO_WIDGET_CLI"])
    if not cli.is_file():
        _say(f"[handoff-to-todo] НЕ ПРОВЕРЕНО: нет {cli}; хендоф {path.name} не вложен в «Личное → Проекты».")
        return 0
    try:
        r = subprocess.run([sys.executable, str(cli), "handoff", str(path)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                # todo.py помечает проект как взятый этой сессией (подсветка во вкладке)
                                "CLAUDE_CODE_SESSION_ID": str(event.get("session_id")
                                                              or os.environ.get("CLAUDE_CODE_SESSION_ID", ""))})
    except subprocess.TimeoutExpired:
        _say(f"[handoff-to-todo] НЕ ПРОВЕРЕНО: Vikunja не ответила за {TIMEOUT_S} с. "
             f'Повтори: python "{cli}" handoff "{path}"')
        return 0
    if r.returncode == 0:
        _say(f"[handoff-to-todo] {r.stdout.strip()} — хендоф виден в задаче проекта «Личное → Проекты».")
    elif r.returncode != 1:
        _say(f"[handoff-to-todo] НЕ ВЛОЖЕН (код {r.returncode}): {(r.stderr or r.stdout).strip()[:300]}. "
             f'Повтори: python "{cli}" handoff "{path}"')
    return 0


def self_test() -> int:
    ok = lambda p: handoff_path({"tool_input": {"file_path": p}})
    cases = [
        (ok("C:/x/.claude/handoffs/project-alpha/2026-10-17_14-50_df270518.md"), Path("C:/x/.claude/handoffs/project-alpha/2026-10-17_14-50_df270518.md")),
        (ok("C:/x/.claude/handoffs/INDEX.md"), None),
        (ok("C:/x/.claude/handoffs/project-alpha/INDEX.md"), None),
        (ok("C:/x/.claude/handoffs/archive/a.md"), None),
        (ok("C:/x/.claude/HANDOFF.md"), None),
        (ok("C:/x/docs/handoffs/a/b.md"), None),
        (handoff_path({}), None),
    ]
    bad = [i for i, (got, want) in enumerate(cases) if got != want]
    print("self-test:", "FAIL " + str(bad) if bad else "PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.exit(main())
    except Exception as exc:  # advisory hook: report, never wedge the session
        print(f"[handoff-to-todo] сбой, хендоф не вложен: {exc}", file=sys.stderr)
        sys.exit(0)
