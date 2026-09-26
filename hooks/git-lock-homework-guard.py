#!/usr/bin/env python3
"""Stop: do not hand a stale git lock to the user - clear it with the proof tool.

Measured 2026-09-26: a session found `.git/index.lock` ownerless, then ended its
turn telling the user to `rm` it in their own terminal. The deletion itself is
agent-owned: scripts/git_stale_lock.py proves "no owner" and verifies the result.
human-confirmation-guard only speaks when the agent TRIES rm; an agent that goes
straight to asking the user never sees that hint. This hook closes that path.

It judges state, not wording: the final message must mention a git lock AND that
lock must still exist on disk AND classify as STALE with the same function the
tool uses. A lock that is gone, young, or possibly owned never blocks, so a
report like "the tool refused: owner alive" ends the turn normally.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import git_stale_lock as gsl  # noqa: E402

TOOL = "python ~/.claude/claude-code-config/scripts/git_stale_lock.py <repo> --remove"
# absolute or relative path to a lock inside a .git dir, or a bare git lock name
LOCK_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s`'\"<>|]*?\.git[\\/][^\s`'\"<>|]*?\.lock"
                          r"|/[^\s`'\"<>|]*?\.git/[^\s`'\"<>|]*?\.lock")
BARE_LOCK_RE = re.compile(r"\b(?:index|HEAD|config|packed-refs|shallow)\.lock\b")


def final_message(event: dict) -> str:
    msg = event.get("last_assistant_message")
    if isinstance(msg, str) and msg.strip():
        return msg
    tp = event.get("transcript_path")
    if not tp or not Path(tp).exists():
        return ""
    for line in reversed(Path(tp).read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        m = obj.get("message", {}) if isinstance(obj, dict) else {}
        if (obj.get("role") or m.get("role")) != "assistant":
            continue
        content = obj.get("content") or m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            if text:
                return text
    return ""


def candidate_locks(message: str, cwd: str | None) -> list[Path]:
    found = [Path(m.group(0).replace("\\", "/")) for m in LOCK_PATH_RE.finditer(message)]
    if not found and BARE_LOCK_RE.search(message) and cwd:
        gdir = gsl.git_dir(Path(cwd))
        if gdir is not None:
            found = gsl.find_locks(gdir)
    return [p for p in found if p.is_file()]


def stale_locks(message: str, cwd: str | None, procs_fn=gsl.live_git_processes) -> list[str]:
    locks = candidate_locks(message, cwd)
    if not locks:
        return []
    try:
        procs = procs_fn()
    except Exception:
        return []  # cannot prove stale -> never block on a guess
    now = time.time()
    out = []
    for lock in locks:
        state, detail = gsl.classify_lock(lock, procs, now, gsl.DEFAULT_MIN_AGE)
        if state == "STALE":
            out.append(f"{lock} ({detail})")
    return out


def self_test() -> int:
    import subprocess
    import tempfile
    import os
    fails = []
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        lock = repo / ".git" / "index.lock"
        lock.write_bytes(b"")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        ask = f"Удалить безопасно, но это нужно сделать тебе:\n```\nrm \"{lock.as_posix()}\"\n```"
        none = lambda: []  # noqa: E731
        if not stale_locks(ask, None, none):
            fails.append("stale lock handed to user was not caught")
        if not stale_locks("Висит index.lock, удали его.", str(repo), none):
            fails.append("bare index.lock with cwd repo was not caught")
        if stale_locks(ask, None, lambda: [(1, "git.exe", old - 5)]):
            fails.append("possibly-owned lock blocked")
        if stale_locks("Всё готово, тесты зелёные.", str(repo), none):
            fails.append("message without a lock blocked")
        lock.unlink()
        if stale_locks(ask, None, none):
            fails.append("already-removed lock blocked")
    for f in fails:
        print("SELF-TEST FAIL:", f)
    print("SELF-TEST", "PASS" if not fails else "FAIL")
    return 0 if not fails else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if event.get("stop_hook_active"):
        return 0  # already re-prompted once; do not loop
    stale = stale_locks(final_message(event), event.get("cwd"))
    if stale:
        print(json.dumps({
            "decision": "block",
            "reason": (
                "Ты передаёшь пользователю протухший git-лок, который снимаешь сама:\n- "
                + "\n- ".join(stale)
                + f"\n\nВыполни: {TOOL}\n"
                "Инструмент удаляет лок только без владельца и сам проверяет git status. "
                "Потом продолжи задачу (коммит/пуш), не проси пользователя удалять лок."
            ),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
