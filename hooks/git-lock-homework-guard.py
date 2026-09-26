#!/usr/bin/env python3
"""Stop: do not hand a stale git lock to the user - clear it with the proof tool.

Measured 2026-09-26: a session found `.git/index.lock` ownerless, then ended its
turn telling the user to `rm` it in their own terminal. The deletion itself is
agent-owned: scripts/git_stale_lock.py proves "no owner" and verifies the result.
human-confirmation-guard only speaks when the agent TRIES rm; an agent that goes
straight to asking the user never sees that hint. This hook closes that path.

It judges state, not wording: the final message must NAME a git lock AND that
lock must still exist on disk AND classify as STALE with the same function the
tool uses. A lock that is gone, young, skewed or possibly owned never blocks, so
a report like "the tool refused: owner alive" ends the turn normally. Any
internal error allows the stop (this hook must never wedge a session).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

TOOL = "python ~/.claude/claude-code-config/scripts/git_stale_lock.py <repo> --remove"
_P = r"[^\s`'\"<>|]"
# quoted path (may contain spaces) or bare path containing a .git dir and ending in .lock
LOCK_PATH_RE = re.compile(
    r"[\"']([^\"'\n]*?\.git[\\/][^\"'\n]*?\.lock)[\"']"
    rf"|((?:[A-Za-z]:|/[A-Za-z](?=/)|\.{{0,2}})?[\\/]?{_P}*?\.git[\\/]{_P}*?\.lock)"
)
BARE_LOCK_RE = re.compile(r"\b((?:index|HEAD|config|packed-refs|shallow)\.lock)\b")


def _gsl():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import git_stale_lock
    return git_stale_lock


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def final_message(event: dict) -> str:
    msg = event.get("last_assistant_message")
    if isinstance(msg, str) and msg.strip():
        return msg
    tp = event.get("transcript_path")
    if not isinstance(tp, str) or not Path(tp).is_file():
        return ""
    for line in reversed(Path(tp).read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        m = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        if (obj.get("role") or m.get("role")) != "assistant":
            continue
        text = _text_of(obj.get("content") or m.get("content"))
        if text:
            return text
    return ""


def _normalize(raw: str, cwd: Path | None) -> Path:
    s = raw.replace("\\", "/")
    m = re.match(r"^/([A-Za-z])/(.*)$", s)  # git-bash /c/Users -> C:/Users
    if m:
        s = f"{m.group(1).upper()}:/{m.group(2)}"
    p = Path(s)
    if not p.is_absolute() and cwd is not None:
        p = cwd / p
    return p


def candidate_locks(message: str, cwd_raw) -> list[Path]:
    cwd = Path(cwd_raw) if isinstance(cwd_raw, str) and cwd_raw else None
    found = [_normalize(m.group(1) or m.group(2), cwd) for m in LOCK_PATH_RE.finditer(message)]
    if not found and cwd is not None:
        names = {m.group(1) for m in BARE_LOCK_RE.finditer(message)}
        gdir = _gsl().git_dir(cwd) if names else None
        if gdir is not None:
            found = [gdir / n for n in sorted(names)]  # only the locks actually named
    seen, out = set(), []
    for p in found:
        key = str(p).lower()
        if key not in seen and p.is_file():
            seen.add(key)
            out.append(p)
    return out


def stale_locks(message: str, cwd, procs_fn=None) -> list[str]:
    locks = candidate_locks(message, cwd)
    if not locks:
        return []
    gsl = _gsl()
    try:
        procs = (procs_fn or gsl.live_git_processes)()
    except Exception:
        return []  # cannot prove stale -> never block on a guess
    now = time.time()
    out = []
    for lock in locks:
        if gsl.on_remote_fs(lock):
            continue  # the tool refuses network/WSL locks; do not demand what it won't do
        state, detail = gsl.classify_lock(lock, procs, now, gsl.DEFAULT_MIN_AGE)
        if state == "STALE":
            out.append(f"{lock} ({detail})")
    return out


def self_test() -> int:
    import os
    import subprocess
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "my repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        lock = repo / ".git" / "index.lock"
        lock.write_bytes(b"")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        none = lambda: []  # noqa: E731
        quoted = f"Please run in your terminal:\n```\nrm \"{lock.as_posix()}\"\n```"
        if not stale_locks(quoted, None, none):
            fails.append("quoted path with a space was not caught")
        if not stale_locks("stale lock at .git/index.lock, remove it", str(repo), none):
            fails.append("relative path resolved against cwd was not caught")
        if not stale_locks("index.lock is stuck, delete it", str(repo), none):
            fails.append("bare index.lock with cwd repo was not caught")
        if stale_locks("HEAD.lock is stuck", str(repo), none):
            fails.append("a lock not present on disk (HEAD.lock) blocked")
        if stale_locks(quoted, None, lambda: [(1, "git.exe", old - 5)]):
            fails.append("possibly-owned lock blocked")
        if stale_locks("All done, tests green.", str(repo), none):
            fails.append("message without a lock blocked")
        if _normalize("/c/Users/x/.git/index.lock", None) != Path("C:/Users/x/.git/index.lock"):
            fails.append("git-bash /c/ path not normalized")
        lock.unlink()
        if stale_locks(quoted, None, none):
            fails.append("already-removed lock blocked")
    for bad in ("[]", "123", "null", '{"last_assistant_message": 5}', "{bad json"):
        r = subprocess.run([sys.executable, __file__], input=bad, capture_output=True, text=True)
        if r.returncode != 0 or r.stdout.strip():
            fails.append(f"odd stdin {bad!r} -> exit {r.returncode} out {r.stdout.strip()[:40]!r}")
    for f in fails:
        print("SELF-TEST FAIL:", f)
    print("SELF-TEST", "PASS" if not fails else "FAIL")
    return 0 if not fails else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if not isinstance(event, dict) or event.get("stop_hook_active"):
            return 0  # odd payload, or already re-prompted once: do not loop
        stale = stale_locks(final_message(event), event.get("cwd"))
    except Exception as exc:  # never wedge the Stop event on our own bug
        print(f"git-lock-homework-guard: internal error, allowing stop: {exc!r}", file=sys.stderr)
        return 0
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
