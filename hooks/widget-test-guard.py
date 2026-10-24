#!/usr/bin/env python3
"""PreToolUse (Bash|PowerShell): widget tests run only on the hidden desktop.

Tk widget suites (tools/*-widget, widget-common) open real windows. Run directly, they flash on the
owner's screen for minutes, and without the test sandbox they ask her running tray program to quit
— she saw "a double of the program flickering endlessly" while several agents tested at once
(2026-10-17). `python scripts/ci_local.py --job widgets --no-post` runs the same suites on a
desktop of its own (hidden_desktop.py) with a LOCALAPPDATA sandbox and its test-sandbox flag.

Blocks a command that starts unittest/pytest/unittest_tk.py for a widget folder (by command text
or working directory) unless it goes through ci_local.py.
Self-test: python widget-test-guard.py --self-test
"""
from __future__ import annotations

import json
import re
import sys

_TEST_RUN = re.compile(r"(-m\s+(unittest|pytest)\b|unittest_tk\.py|\bpytest\b)", re.I)
_WIDGET = re.compile(r"[-\w]*widget[-\w]*", re.I)

MESSAGE = (
    "Тесты виджетов — только на невидимом рабочем столе: python scripts/ci_local.py --job widgets --no-post\n"
    "Прямой unittest/pytest в tools/*-widget поднимает настоящие окна на экране владелицы (программа «мигает»),\n"
    "а без песочницы ещё и просит её живую программу закрыться. ci_local гоняет те же наборы скрыто,\n"
    "с отдельным LOCALAPPDATA и флагом тестовой песочницы."
)


def blocked(command: str, cwd: str) -> bool:
    if not _TEST_RUN.search(command) or "ci_local.py" in command:
        return False
    return bool(_WIDGET.search(command) or _WIDGET.search(cwd))


def main() -> int:
    try:
        event = json.loads(sys.stdin.read().lstrip("\ufeff") or "{}")
    except json.JSONDecodeError:
        return 0
    command = str((event.get("tool_input") or {}).get("command") or "")
    if blocked(command, str(event.get("cwd") or "")):
        print(MESSAGE, file=sys.stderr)
        return 2
    return 0


def self_test() -> int:
    cases = [
        (("cd tools/todo-widget && python -m unittest test_panel", ""), True),
        (("python -m unittest discover -p test_*.py", "D:/repo/tools/widget-common"), True),
        (("timeout 500 D:/x/.venv/Scripts/python.exe -m unittest test_store", "D:/r/tools/vikunja-widget"), True),
        (("python scripts/unittest_tk.py -v", "D:/repo/tools/ops-widget"), True),
        (("python scripts/ci_local.py --job widgets --no-post", "D:/repo"), False),
        (("cd bot && pytest -q", "D:/repo"), False),
        (("python -m unittest test_x", "D:/other/project"), False),
        (("python tools/todo-widget/todo.py resume 1038", ""), False),
    ]
    bad = [i for i, ((cmd, cwd), want) in enumerate(cases) if blocked(cmd, cwd) is not want]
    print("self-test:", "FAIL " + str(bad) if bad else "PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(main())
