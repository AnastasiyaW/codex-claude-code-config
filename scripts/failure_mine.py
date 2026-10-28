#!/usr/bin/env python3
"""failure_mine.py - read-only, deterministic miner of agent failures in session transcripts.

WHY THIS EXISTS
---------------
Fixes get written from memory of the last bad session. A repeated failure seen
across several sessions is a better target than the one that felt worst, and the
transcripts already hold that evidence. This script counts it without an LLM:
same tool, same normalised error text, in more than one session.

WHAT IT READS
-------------
Claude Code session transcripts: JSONL, one object per line, top level only
(default root `~/.claude/projects`, glob `*/*.jsonl`; override with --root).

Failure events:
  * error      - a tool_result with `is_error: true`;
  * hook_block - a tool_result whose text starts with `PreToolUse:` or
                 `PostToolUse:` and contains "hook error" or "blocked";
  * repeat     - the same tool call (tool name + identical input JSON) made
                 3 or more times in one session (recorded once, at the 3rd call).

Each error event gets a signature: the first non-empty line of the text,
lowercased, with quoted strings, paths, hex ids and digits replaced by
placeholders, cut to 160 characters. Events are grouped by (tool, signature).

OUTPUT
------
JSON on stdout (or --out FILE): counts, then clusters sorted by number of
distinct sessions. Each cluster has count, sessions, and up to 5 samples
(snippets cut to 300 characters). Clusters seen in one session are dropped
unless --include-single is given. The output may contain private data
(commands, paths, error text): never commit it, and --out refuses paths
inside this repository.

Usage:
  python failure_mine.py [--root DIR] [--top N] [--out FILE] [--include-single]
  python failure_mine.py --self-test

Exit: 0 ran and found clusters; 1 ran and found none (also: self-test has a
failing check); 2 nothing could be read (no files, all unreadable, bad
arguments, or --out inside the repository).

NEXT STEP (not done by this script)
-----------------------------------
A fresh-context critic (no access to this session) labels the top clusters with
`cause` and `fix_type` in {hook/validator, script, skill, prose, none}. Each fix
goes forward as ONE candidate through scripts/harness_improvement_pilot.py, with
a held-out case taken from a different session than the one the fix was drawn
from. A human approves every rule change; the miner never edits rules or hooks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = Path.home() / ".claude" / "projects"
SAMPLES_PER_CLUSTER = 5
SNIPPET_CHARS = 300
SIGNATURE_CHARS = 160
REPEAT_THRESHOLD = 3
REPEAT_SIGNATURE = "repeated identical call (3+ times in one session)"
HOOK_PREFIXES = ("PreToolUse:", "PostToolUse:")
NOTE = ("NOTE: output may contain private data (commands, paths, error text from "
        "your sessions). Do not commit it; keep it in a temp or scratch folder.")

_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
_ABS_PATH = re.compile(r"(?:[a-z]:)?[\\/][^\s'\"`]*")
_REL_PATH = re.compile(r"\b[\w.\-]+[\\/][\w.\-\\/]*")
_HEX_PREFIX = re.compile(r"\b0x[0-9a-f]+\b")
_HEX_ID = re.compile(r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{8,}\b")
_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Signature of an error text: first non-empty line with volatile parts replaced."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    s = (lines[0] if lines else "<empty>").lower()
    s = _QUOTED.sub("<q>", s)
    s = _ABS_PATH.sub("<path>", s)
    s = _REL_PATH.sub("<path>", s)
    s = _HEX_PREFIX.sub("<hex>", s)
    s = _HEX_ID.sub("<hex>", s)
    s = _DIGITS.sub("<n>", s)
    return _SPACES.sub(" ", s).strip()[:SIGNATURE_CHARS]


def result_text(content: object) -> str:
    """Flatten a tool_result content field (string or list of text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


def is_hook_block(text: str) -> bool:
    head = text.lstrip()
    if not head.startswith(HOOK_PREFIXES):
        return False
    low = head.lower()
    return "hook error" in low or "blocked" in low


def _event(session: str, tool: str, kind: str, signature: str, snippet: str) -> dict:
    return {
        "session": session,
        "tool": tool,
        "kind": kind,
        "signature": signature,
        "snippet": " ".join(snippet.split())[:SNIPPET_CHARS],
    }


def mine_file(path: Path, stats: dict) -> list[dict]:
    """Events of one transcript, in file order. Raises OSError if it cannot be read."""
    session = path.stem
    tool_names: dict[str, str] = {}
    calls: Counter = Counter()
    events: list[dict] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except ValueError:
                stats["lines_skipped"] += 1
                continue
            message = obj.get("message") if isinstance(obj, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use":
                    name = str(item.get("name", "unknown"))
                    if item.get("id") is not None:
                        tool_names[item["id"]] = name
                    key = (name, json.dumps(item.get("input", {}), sort_keys=True, ensure_ascii=False))
                    calls[key] += 1
                    if calls[key] == REPEAT_THRESHOLD:
                        events.append(_event(session, name, "repeat", REPEAT_SIGNATURE, key[1]))
                elif item.get("type") == "tool_result":
                    tool = tool_names.get(item.get("tool_use_id"), "unknown")
                    text = result_text(item.get("content"))
                    if item.get("is_error") is True:
                        events.append(_event(session, tool, "error", normalise(text), text))
                    if is_hook_block(text):
                        events.append(_event(session, tool, "hook_block", normalise(text), text))
    return events


def scan(root: Path, include_single: bool, top: int) -> tuple[dict, int]:
    """Mine every transcript under root. Returns (report, exit code)."""
    stats = {"files_scanned": 0, "files_unreadable": 0, "lines_skipped": 0}
    files = sorted(p for p in root.glob("*/*.jsonl") if p.is_file()) if root.is_dir() else []
    if not files:
        return {"error": "no transcript files found under the given root"}, 2
    all_events: list[dict] = []
    for path in files:
        try:
            events = mine_file(path, stats)
        except OSError:
            stats["files_unreadable"] += 1
            continue
        stats["files_scanned"] += 1
        all_events.extend(events)
    if stats["files_scanned"] == 0:
        return {"error": "every transcript file was unreadable"}, 2

    clusters: dict[tuple[str, str], dict] = {}
    for ev in all_events:
        cl = clusters.setdefault(
            (ev["tool"], ev["signature"]),
            {"count": 0, "sessions": set(), "samples": []},
        )
        cl["count"] += 1
        cl["sessions"].add(ev["session"])
        if len(cl["samples"]) < SAMPLES_PER_CLUSTER:
            cl["samples"].append({"session": ev["session"], "kind": ev["kind"], "snippet": ev["snippet"]})

    rows = []
    for (tool, signature), cl in clusters.items():
        if not include_single and len(cl["sessions"]) < 2:
            continue
        rows.append({
            "tool": tool,
            "signature": signature,
            "count": cl["count"],
            "sessions_count": len(cl["sessions"]),
            "sessions": sorted(cl["sessions"]),
            "samples": cl["samples"],
        })
    rows.sort(key=lambda r: (-r["sessions_count"], -r["count"], r["tool"], r["signature"]))
    report = {
        "files_scanned": stats["files_scanned"],
        "files_unreadable": stats["files_unreadable"],
        "lines_skipped": stats["lines_skipped"],
        "events": len(all_events),
        "clusters_found": len(rows),
        "clusters": rows[:top],
        "note": NOTE,
    }
    return report, (0 if rows else 1)


def self_test() -> int:
    def line_use(use_id: str, name: str, inp: dict) -> str:
        return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": use_id, "name": name, "input": inp}]}})

    def line_result(use_id: str, text: str, is_error: bool = False) -> str:
        return json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": use_id, "content": text, "is_error": is_error}]}})

    edit = {"file_path": "/a/b.py", "old_string": "x", "new_string": "y"}
    fixtures = {
        # same error, different path/digits/ids in two sessions -> one cluster
        "s1": [
            line_use("a1", "Bash", {"command": "rm x"}),
            line_result("a1", "Error: file C:\\Users\\proj\\abc12ef9 not found at line 42", True),
            line_use("a2", "Bash", {"command": "ls"}),
            line_result("a2", "PreToolUse:Bash hook error: blocked by policy 7f3a9b2c"),
            *[line_use(f"e{i}", "Edit", edit) for i in range(3)],
        ],
        "s2": [
            line_use("b1", "Bash", {"command": "cat"}),
            line_result("b1", "Error: file /opt/app/q/zz9 not found at line 7", True),
            line_use("b2", "Bash", {"command": "cat2"}),
            line_result("b2", "PreToolUse:Bash hook error: blocked by policy 0badc0de"),
            *[line_use(f"f{i}", "Edit", {**edit, "file_path": "/c/d.py"}) for i in range(3)],
        ],
        # single-session noise: must be dropped by default, kept with --include-single
        "s3": [
            line_use("c1", "Read", {"file_path": "/z"}),
            line_result("c1", "Totally different failure xyz", True),
            *[line_use(f"r{i}", "Read", {"file_path": "/z"}) for i in range(3)],
            *[line_use(f"g{i}", "Grep", {"pattern": "p"}) for i in range(2)],
        ],
    }

    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        root = base / "projects"
        (root / "proj").mkdir(parents=True)
        for stem, lines in fixtures.items():
            (root / "proj" / f"{stem}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        report, code = scan(root, include_single=False, top=50)
        by_key = {(c["tool"], c["signature"]): c for c in report.get("clusters", [])}
        err_key = ("Bash", "error: file <path> not found at line <n>")
        hook_key = ("Bash", "pretooluse:bash hook error: blocked by policy <hex>")
        edit_key = ("Edit", REPEAT_SIGNATURE)
        checks.append(("same error across 2 sessions clusters into one", err_key in by_key
                       and by_key[err_key]["sessions_count"] == 2))
        checks.append(("hook block across 2 sessions clusters", hook_key in by_key
                       and by_key[hook_key]["sessions_count"] == 2))
        checks.append(("3x identical call detected across 2 sessions", edit_key in by_key
                       and by_key[edit_key]["sessions_count"] == 2))
        checks.append(("single-session error dropped by default", not any(
            "totally different" in c["signature"] for c in report.get("clusters", []))))
        checks.append(("single-session 3x repeat dropped by default", ("Read", REPEAT_SIGNATURE)
                       not in by_key))
        checks.append(("2x repeat is not an event", ("Grep", REPEAT_SIGNATURE) not in by_key))
        checks.append(("exit 0 when clusters found", code == 0))

        wide, _ = scan(root, include_single=True, top=50)
        wide_keys = {(c["tool"], c["signature"]) for c in wide.get("clusters", [])}
        checks.append(("--include-single keeps the single-session error", (
            "Read", "totally different failure xyz") in wide_keys))
        checks.append(("--include-single detects the single-session 3x repeat", (
            "Read", REPEAT_SIGNATURE) in wide_keys))

        empty = base / "empty"
        empty.mkdir()
        _, code_empty = scan(empty, include_single=False, top=5)
        checks.append(("must-fail control: empty root -> exit 2", code_empty == 2))

        clean = base / "clean" / "proj"
        clean.mkdir(parents=True)
        (clean / "ok.jsonl").write_text(line_use("x", "Bash", {"command": "ok"}) + "\n"
                                        + line_result("x", "fine") + "\n", encoding="utf-8")
        _, code_clean = scan(base / "clean", include_single=False, top=5)
        checks.append(("clean transcript -> exit 1 (nothing found)", code_clean == 1))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"self-test: {len(checks) - len(failed)}/{len(checks)} checks behaved")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mine agent failures from Claude Code transcripts (read-only).")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="projects root (default ~/.claude/projects)")
    parser.add_argument("--top", type=int, default=20, help="clusters to print (default 20)")
    parser.add_argument("--out", type=Path, help="write JSON to FILE instead of stdout (not inside the repo)")
    parser.add_argument("--include-single", action="store_true", help="keep clusters seen in one session")
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures and controls")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.top < 1:
        print("error: --top must be >= 1", file=sys.stderr)
        return 2
    if args.out is not None and args.out.resolve().is_relative_to(REPO_ROOT):
        print("error: --out must not be inside the repository", file=sys.stderr)
        return 2

    report, code = scan(args.root, args.include_single, args.top)
    if "error" in report:
        print(f"error: {report['error']}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"files_scanned={report['files_scanned']} events={report['events']} "
              f"clusters={report['clusters_found']} written={args.out}", file=sys.stderr)
    else:
        print(text)
    print(NOTE, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
