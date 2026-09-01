#!/usr/bin/env python3
"""SessionStart hook: surface queued Claude/Codex feedback-distillation work.

Companion to session-feedback-capture.py. That Stop hook queues session pointers
into ~/.claude/feedback/queue.jsonl; this one surfaces the pending count at session
start so the learn-from-corrections loop actually closes instead of the queue growing
silently. Self-clearing: the distill step marks entries processed, so the count drops.

Stays SILENT when nothing is pending, so sessions that never accumulate feedback see
zero output. Non-blocking, informational only.

Setup in ~/.claude/settings.json:
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{ "type": "command", "command": "python hooks/feedback-pending-show.py" }]
    }]
  }
}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FEEDBACK_DIR = Path.home() / ".claude" / "feedback"
QUEUE_PATH = FEEDBACK_DIR / "queue.jsonl"
PROCESSED_PATH = FEEDBACK_DIR / "processed.jsonl"


def _ids(path: Path) -> set[str]:
    """Collect session_ids from an append-only jsonl. Empty set if missing/unreadable."""
    out: set[str] = set()
    if not path.exists():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = rec.get("session_id")
            if sid:
                out.add(sid)
    except OSError:
        return out
    return out


def count_pending(queue_path: Path, processed_path: Path) -> int:
    """Pending = queued session_ids not yet in the append-only processed log."""
    queued = _ids(queue_path)
    processed = _ids(processed_path)
    return len(queued - processed)


def main() -> int:
    pending = count_pending(QUEUE_PATH, PROCESSED_PATH)
    if pending <= 0:
        return 0  # nothing queued - stay silent
    print(f"[learn-from-corrections] {pending} session(s) queued for feedback-distill.")
    print(
        "  Run /distill-feedback to extract durable corrections into rules "
        "(LLM-semantic, human-gated). See rules/learn-from-corrections.md."
    )
    return 0


def _self_test() -> int:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    q = tmp / "queue.jsonl"
    pr = tmp / "processed.jsonl"
    assert count_pending(q, pr) == 0, "missing queue => 0"
    q.write_text(
        "\n".join(
            [
                json.dumps({"session_id": "a"}),
                json.dumps({"session_id": "b"}),
                json.dumps({"session_id": "c"}),
                "not json",
            ]
        ),
        encoding="utf-8",
    )
    pr.write_text(json.dumps({"session_id": "b"}) + "\n", encoding="utf-8")
    assert count_pending(q, pr) == 2, "3 queued - 1 processed = 2 pending"
    print("self-test OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
