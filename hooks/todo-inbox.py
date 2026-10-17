#!/usr/bin/env python3
"""UserPromptSubmit + PreToolUse: the owner's new words on a project reach the agent working on it.

The owner writes in the feed under a project task of her to-do («Личное → Проекты»). An agent
session that took the project (`todo.py resume` / `handoff` recorded its session id in
project_sessions.json) gets those comments here as additional context:
- on UserPromptSubmit at most every 45 s, on PreToolUse at most every 3 min per session (THROTTLE_S),
  so a long autonomous run hears her too and no prompt waits on the network each time.

No network unless this session has claimed a project (local file check first). Advisory, never
blocks. CLI path: env TODO_WIDGET_CLI; unset = the to-do is not installed here, nothing happens.
Self-test: python todo-inbox.py --self-test
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

TIMEOUT_S = 8
# Не чаще: на сообщениях — раз в 45 с (поток сообщений не ждёт сеть каждый раз), во время работы — раз в 3 мин.
THROTTLE_S = {"UserPromptSubmit": 45, "PreToolUse": 180}


def data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "TodoWidget"


def has_claim(folder: Path, session: str) -> bool:
    try:
        data = json.loads((folder / "project_sessions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(isinstance(v, dict) and session in v for v in data.values())


def throttled(folder: Path, session: str, event: str, now: float) -> bool:
    """True — проверяли недавно; иначе отмечает «проверяем сейчас»."""
    path = folder / "inbox_throttle.json"
    key = f"{session}:{event}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if now - float(data.get(key, 0)) < THROTTLE_S.get(event, 180):
        return True
    data = {k: v for k, v in data.items() if now - float(v) < 86400}
    data[key] = now
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return False


def main() -> int:
    try:
        event = json.loads(sys.stdin.read().lstrip("﻿") or "{}")
    except json.JSONDecodeError as exc:
        print(f"[todo-inbox] event did not parse, nothing checked: {exc}", file=sys.stderr)
        return 0
    cli = os.environ.get("TODO_WIDGET_CLI")
    session = str(event.get("session_id") or "")
    name = event.get("hook_event_name") or ""
    if not cli or not session:
        return 0
    folder = data_dir()
    if not has_claim(folder, session):
        return 0
    if throttled(folder, session, name, time.time()):
        return 0
    try:
        r = subprocess.run([sys.executable, cli, "inbox"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT_S,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8", "CLAUDE_CODE_SESSION_ID": session})
    except subprocess.TimeoutExpired:
        print(f"[todo-inbox] слова владелицы не проверены: нет ответа за {TIMEOUT_S} с", file=sys.stderr)
        return 0
    if r.returncode != 0:
        print(f"[todo-inbox] слова владелицы не проверены (код {r.returncode}): "
              f"{(r.stderr or r.stdout).strip()[:200]}", file=sys.stderr)
        return 0
    text = r.stdout.strip()
    if r.returncode == 0 and text:
        out = {"hookSpecificOutput": {"hookEventName": name or "UserPromptSubmit",
                                      "additionalContext": f"[todo-inbox] {text}\n(это слова владелицы из ленты проекта — учти в работе; ответ в ленту: todo.py comment <проект> \"...\")"}}
        print(json.dumps(out, ensure_ascii=False))
    return 0


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "project_sessions.json").write_text(json.dumps({"7": {"s1": "x"}}), encoding="utf-8")
        pre, prompt = "PreToolUse", "UserPromptSubmit"
        checks = [has_claim(folder, "s1") is True, has_claim(folder, "s2") is False,
                  throttled(folder, "s1", pre, 1000.0) is False, throttled(folder, "s1", pre, 1100.0) is True,
                  throttled(folder, "s1", prompt, 1100.0) is False,  # у сообщений свой отсчёт
                  throttled(folder, "s1", prompt, 1120.0) is True,
                  throttled(folder, "s1", pre, 1000.0 + THROTTLE_S[pre] + 1) is False,
                  has_claim(Path(d) / "missing", "s1") is False]
    bad = [i for i, ok in enumerate(checks) if not ok]
    print("self-test:", "FAIL " + str(bad) if bad else "PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.exit(main())
    except Exception as exc:  # advisory hook: report, never wedge the session
        print(f"[todo-inbox] сбой, входящие не проверены: {exc}", file=sys.stderr)
        sys.exit(0)
