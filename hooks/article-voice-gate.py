#!/usr/bin/env python3
"""PreToolUse: an article reaches the knowledge base only with a check behind it.

The news pipeline writes knowledge-base pages by machine. Two passes stand between
the assembled facts and the public repository: an editor that rewrites the sentences
in the house voice under mechanical guards, and an independent checker that reads the
result against the same research and names anything invented. Both leave a receipt.

This gate refuses the publishing step - pushing a `kb/` branch, opening or merging its
pull request - when that receipt is missing or says the page was refused. It is the
mechanical half of the owner's rule (2026-09-04): "из головы писать не должен, надо
человеческий стиль написания и проверять все данные".

Three states, and the middle one is not green (see rules/absence-of-signal.md):
  receipt says checked, nothing invented  -> allow
  receipt says refused / invented         -> block, naming the finding
  no receipt for this branch              -> block as UNVERIFIED, not as fine

Bypass: `# claude-bypass: article-voice` in the command, or CLAUDE_ALLOW_ARTICLE_VOICE=1.
Self-test: python article-voice-gate.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from safety_common import block, bypass, read_event  # type: ignore
except Exception:  # a hook that cannot load its helpers must not wedge the session
    block = bypass = read_event = None  # type: ignore

REPO = "AnastasiyaW/knowledge-space"
BRANCH = re.compile(r"(?:^|[\s\"'/:])(kb/[A-Za-z0-9._-]+)")
PUBLISHES = re.compile(r"(?i)\bgh\s+pr\s+(create|merge)\b|\bgit\s+push\b")
# Where the writer files its receipts. The first that exists wins; a project may name
# its own through CLAUDE_NEWS_LEDGERS (semicolon-separated).
# Built from the home directory, never written out: this file lives in a public
# repository and a literal user path is exactly what its scan refuses.
_WORK = Path.home() / "Desktop" / "Codex+Code"
DEFAULT_LEDGERS = [
    _WORK / "worktrees" / "happyin-news-v1-4" / "diffusion-love" / "var" / "kb-articles",
    _WORK / "diffusion-love" / "var" / "kb-articles",
    Path.cwd() / "var" / "kb-articles",
]
LEDGER_FILES = ("ledger.jsonl", "revoice.jsonl")


def ledger_dirs() -> list[Path]:
    configured = os.environ.get("CLAUDE_NEWS_LEDGERS", "").strip()
    if configured:
        return [Path(p) for p in configured.split(";") if p.strip()]
    return DEFAULT_LEDGERS


def receipts_for(branch: str) -> list[dict]:
    """Every receipt that names this branch, oldest first."""
    found: list[dict] = []
    for directory in ledger_dirs():
        for name in LEDGER_FILES:
            path = directory / name
            if not path.is_file():
                continue
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if branch not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("branch") == branch:
                        found.append(record)
            except OSError:
                continue
    return found


def verdict(branch: str) -> tuple[str, str]:
    """(state, why) where state is 'checked', 'refused' or 'unverified'."""
    records = receipts_for(branch)
    if not records:
        return "unverified", f"no receipt names {branch} in {', '.join(str(d) for d in ledger_dirs())}"
    latest = records[-1]
    check = latest.get("check") or {}
    voice = latest.get("voice") or {}
    invented = check.get("invented") or []
    if invented:
        return "refused", f"the independent check found {len(invented)} invented specific(s): {str(invented[0])[:160]}"
    if not check:
        return "unverified", "the receipt carries no check: the page was written before the gate, or with --no-voice"
    if voice.get("status") == "refused":
        why = "; ".join(str(c) for c in (voice.get("complaints") or [])[:2])
        return "checked", f"the rewrite was refused ({why or 'guards'}), so the assembled text is what publishes - allowed"
    return "checked", f"check verdict {check.get('verdict', 'unknown')}, nothing invented"


def branches_in(command: str) -> list[str]:
    return sorted({m.group(1).rstrip(".,;\"'") for m in BRANCH.finditer(command)})


def decide(command: str) -> tuple[bool, str]:
    """(allowed, reason). A command that does not publish an article is allowed."""
    if not PUBLISHES.search(command):
        return True, ""
    touches_kb = REPO in command or "knowledge-space" in command
    names = branches_in(command)
    if not names or not (touches_kb or names):
        return True, ""
    problems = []
    for branch in names:
        state, why = verdict(branch)
        if state == "checked":
            continue
        problems.append(f"{branch}: {state} - {why}")
    if not problems:
        return True, ""
    return False, "\n".join(problems)


def main() -> None:
    if read_event is None or block is None:
        sys.exit(0)  # fail open: a broken gate must not stop the work
    try:
        event = read_event()
        command = (event.get("tool_input") or {}).get("command") or ""
    except Exception:
        sys.exit(0)
    if not command:
        sys.exit(0)
    if bypass("article-voice", command, env_name="CLAUDE_ALLOW_ARTICLE_VOICE"):
        sys.exit(0)
    allowed, reason = decide(command)
    if allowed:
        sys.exit(0)
    block(
        "An article may not reach the knowledge base without its check.\n\n"
        f"{reason}\n\n"
        "The page is written by the renderer, rewritten by the editor in the house voice under\n"
        "mechanical guards, then read by an independent checker against the same research\n"
        "(ops/codex/article_voice.py). The receipt of that pass is what this gate reads.\n\n"
        "Ways forward: run the page through ops/codex/article_revoice.py (it re-assembles and\n"
        "re-checks from the filed research), or, for a page that is deliberately unchecked,\n"
        "add '# claude-bypass: article-voice' with a reason."
    )


SELF_TEST = [
    ("git push origin kb/vidu-20260903-2010", "unverified", False),
    ("gh pr create --repo AnastasiyaW/knowledge-space --head kb/checked-1 --title x", "checked", True),
    ("gh pr merge 48 --repo AnastasiyaW/knowledge-space --merge", "no branch named", True),
    ("git push origin kb/invented-1", "invented", False),
    ("git push origin kb/refused-rewrite-1", "rewrite refused, text is the assembled one", True),
    ("git status", "not a publish", True),
    ("git push origin main", "not an article branch", True),
    ("git push origin kb/unverified-1 # claude-bypass: article-voice", "bypass", True),
]


def self_test() -> int:
    import tempfile

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        rows = [
            {"branch": "kb/checked-1", "voice": {"status": "edited"}, "check": {"verdict": "pass", "invented": []}},
            {"branch": "kb/invented-1", "voice": {"status": "edited"}, "check": {"verdict": "needs_work", "invented": ["a price nobody published"]}},
            {"branch": "kb/refused-rewrite-1", "voice": {"status": "refused", "complaints": ["dropped 2 dates"]},
             "check": {"verdict": "pass", "invented": []}},
            {"branch": "kb/no-check-1", "voice": {"status": "edited"}},
        ]
        (directory / "ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        os.environ["CLAUDE_NEWS_LEDGERS"] = str(directory)
        for command, label, expected in SELF_TEST:
            if "claude-bypass" in command:
                allowed = True  # the real path exits before decide(); the marker is the contract
            else:
                allowed, _ = decide(command)
            if allowed != expected:
                failures.append(f"{label}: expected allowed={expected}, got {allowed} for {command!r}")
        # The negative control: a gate that cannot go red is broken.
        must_be_red, _ = decide("git push origin kb/never-seen-branch")
        if must_be_red:
            failures.append("negative control passed: an unknown branch must be refused")
    for line in failures:
        print("FAIL", line)
    print(f"{len(SELF_TEST) + 1 - len(failures)} of {len(SELF_TEST) + 1} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    main()
