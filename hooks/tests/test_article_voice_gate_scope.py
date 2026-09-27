# -*- coding: utf-8 -*-
"""The article-voice gate belongs to one pipeline, and must still bite inside it.

Measured 2026-09-27: editing an engineering reference under `kb/docs/` in another
repository was refused with "no receipt names kb/docs in ...", naming three ledger
directories that belong to the news project - only one of which exists, none of which
that repository could ever write to. It has no `ops/codex/article_voice.py` and no
`var/kb-articles`, so no receipt for that page can exist, and the gate's only exit
there was its own bypass. A gate that is always bypassed has stopped being a gate.

So the scope is read from the repository, not from the `kb/` prefix. This suite runs
the gate as the harness runs it - a PreToolUse event on stdin, the verdict read from
the block JSON - across three fixture repositories:

  pipeline  the repository that owns the renderer and the receipts (marker in root)
  clone     a clone of the knowledge base, which is where the writer actually pushes
            from and which carries no marker at all
  other     an unrelated repository that keeps engineering references under kb/docs

What must NOT change: an unchecked article branch is still refused in the first two.
Cases 1, 4, 5 and 7 are the negative control - a gate that cannot go red is broken,
and one that cannot go green on another repository's files is a bypass generator.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOKS = Path(os.environ.get("HOOKS_DIR", Path(__file__).resolve().parents[1])).resolve()
GATE = HOOKS / "article-voice-gate.py"
KB_URL = "https://github.com/AnastasiyaW/knowledge-space.git"

CHECKED = "kb/checked-page-20260927"
UNCHECKED = "kb/never-filed-20260927"
REFERENCE = "kb/docs/platform/service-notes.md"


def fixture(tmp: Path) -> dict[str, Path]:
    """Three repositories differing only in what the gate is supposed to read."""
    pipeline = tmp / "pipeline"
    (pipeline / ".git").mkdir(parents=True)
    (pipeline / "var" / "kb-articles").mkdir(parents=True)
    (pipeline / "ops" / "codex").mkdir(parents=True)
    (pipeline / "ops" / "codex" / "article_voice.py").write_text("# the checker\n", encoding="utf-8")

    clone = tmp / "clone"
    (clone / ".git").mkdir(parents=True)
    (clone / ".git" / "config").write_text(
        f'[remote "origin"]\n\turl = {KB_URL}\n', encoding="utf-8")

    other = tmp / "other"
    (other / ".git").mkdir(parents=True)
    (other / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://example.invalid/other-project.git\n', encoding="utf-8")
    (other / "kb" / "docs" / "platform").mkdir(parents=True)
    (other / "kb" / "docs" / "platform" / "service-notes.md").write_text("# reference\n", encoding="utf-8")
    return {"pipeline": pipeline, "clone": clone, "other": other}


def ledger(tmp: Path) -> Path:
    """One receipt, for the one branch that is allowed to pass."""
    directory = tmp / "ledger"
    directory.mkdir()
    (directory / "ledger.jsonl").write_text(
        json.dumps({"branch": CHECKED, "voice": {"status": "edited"},
                    "check": {"verdict": "pass", "invented": []}}) + "\n", encoding="utf-8")
    return directory


def ran(command: str, cwd: Path, event_cwd: Path | None | str, ledger_dir: Path) -> str:
    """The gate, run the way the harness runs it. Returns its stdout."""
    event: dict = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": command}}
    if event_cwd is not None:
        event["cwd"] = str(event_cwd)
    env = os.environ.copy()
    env["CLAUDE_NEWS_LEDGERS"] = str(ledger_dir)
    env.pop("CLAUDE_ALLOW_ARTICLE_VOICE", None)  # the bypass is a case, not the weather
    result = subprocess.run(
        [sys.executable, "-B", str(GATE)],
        input=json.dumps(event),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        cwd=str(cwd),
        env=env,
    )
    if result.returncode:
        return f'{{"decision": "crash", "reason": {json.dumps(result.stderr[-400:])}}}'
    return result.stdout


def blocked(output: str) -> bool:
    try:
        return json.loads(output or "{}").get("decision") == "block"
    except json.JSONDecodeError:
        return False


def main() -> int:
    push = "git push origin "
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        where = fixture(root)
        receipts = ledger(root)
        # (label, command, process cwd key, event cwd: True same / False absent / a key,
        #  expected verdict). The last form splits the two, so a gate that reads its own
        #  process directory instead of the event's cannot pass by coincidence.
        cases = [
            ("1 clone, unchecked article branch", push + UNCHECKED, "clone", True, "block"),
            ("2 other repo, kb/docs reference",
             f"git add {REFERENCE} && git commit -m x && git push", "other", True, "allow"),
            ("3 clone, checked article branch", push + CHECKED, "clone", True, "allow"),
            ("4 pipeline repo, unchecked", push + UNCHECKED, "pipeline", True, "block"),
            ("5 no cwd in event, process in clone", push + UNCHECKED, "clone", False, "block"),
            ("6 no cwd in event, process in other",
             f"git add {REFERENCE} && git commit -m x && git push", "other", False, "allow"),
            ("7 git -C into the clone", "git -C {clone} push origin " + UNCHECKED, "other", True, "block"),
            ("8 bypass marker", push + UNCHECKED + " # claude-bypass: article-voice", "clone", True, "allow"),
            ("9 not a publish at all", "git status", "clone", True, "allow"),
            ("10 not an article branch", "git push origin main", "clone", True, "allow"),
            # The event's working directory is the one that counts, not this process's.
            ("11 event says clone, process in other", push + UNCHECKED, "other", "clone", "block"),
            ("12 event says other, process in clone",
             f"git add {REFERENCE} && git commit -m x && git push", "clone", "other", "allow"),
        ]
        for label, command, place, in_event, expected in cases:
            command = command.replace("{clone}", str(where["clone"]))
            cwd = where[place]
            if in_event is True:
                event_cwd: Path | None = cwd
            elif in_event is False:
                event_cwd = None
            else:
                event_cwd = where[in_event]
            output = ran(command, cwd, event_cwd, receipts)
            got = "block" if blocked(output) else "allow"
            if '"crash"' in output:
                failures.append(f"{label}: the gate crashed - {output[:300]}")
            elif got != expected:
                failures.append(f"{label}: expected {expected}, got {got} for {command!r}")
        total = len(cases)
    for line in failures:
        print("FAIL", line)
    if failures:
        # Never a sentence that reads green on red: the runner judges by exit code,
        # and a human reading this output must see the same verdict.
        print(f"{len(failures)} of {total} checks FAILED")
        return 1
    print(f"all {total} checks correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
