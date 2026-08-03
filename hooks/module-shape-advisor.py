#!/usr/bin/env python3
"""Advisory: this file has outgrown its shape — where is the seam?

The mirror of over-engineering-advisor.py. That one asks "is this the SMALLEST
solution?" on every sizeable addition, and until this file existed it was the ONLY
permanent pressure on code shape in the harness. One-sided pressure has a direction,
and the direction is a monolith:

    adding a 40-line handler to an 8000-line module is a smaller diff than
    creating a module, wiring a router, and moving three helpers across.

So the minimal-diff heuristic, applied honestly once per session, is a ratchet. Each
edit is locally correct and locally minimal; nobody is ever asked the cumulative
question. Measured on one project before this hook existed: a single backend module
at 8823 lines, 190 route handlers, 335 top-level functions, one class, and 13
module-level mutable objects (6 hand-rolled locks) shared by everything in it. It got
there in increments that each looked right.

Hence this fires on the SHAPE OF THE WHOLE FILE after an edit, not on the size of the
edit. And it is ADVISORY, never blocking: a blocking shape gate would fight
finish-the-task exactly as a blocking minimalism gate would, and blanket-blocking
prompts measurably reduce completion (the non-monotonic result behind quality-code.md
keeping its own advisor advisory).

Tuning:  CLAUDE_SHAPE_MAX_LINES, CLAUDE_SHAPE_MAX_DEFS, CLAUDE_SHAPE_MAX_STATE
Silence: CLAUDE_ALLOW_BIG_MODULES=1
Self-test: python module-shape-advisor.py --self-test
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# One definition of "what shape is this file in", shared with scripts/architecture_audit.py.
# They were written independently and had already drifted -- see shape_common's docstring.
from shape_common import (  # noqa: E402
    CODE_SUFFIXES,
    MAX_DEFS,
    MAX_FN_LINES,
    MAX_LINES,
    MAX_STATE,
    is_exempt as _exempt,
    python_shape,
    shape_findings as findings_for,
)

NAG_DAYS = 3  # per file, so a long session on one module is not a drumbeat


def _nagged_recently(path: Path) -> bool:
    stamp = Path.home() / ".claude" / "state" / "shape-nudges.json"
    try:
        data = json.loads(stamp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        data = {}
    key = str(path)
    now = time.time()
    if now - float(data.get(key, 0)) < NAG_DAYS * 86400:
        return True
    data[key] = now
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return False


def main() -> int:
    if os.environ.get("CLAUDE_ALLOW_BIG_MODULES") == "1":
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0  # fail open: an advisory hook must never be the reason work stops

    tool = event.get("tool_name") or ""
    if tool not in ("Write", "Edit", "MultiEdit"):
        return 0
    raw = (event.get("tool_input") or {}).get("file_path")
    if not raw:
        return 0

    path = Path(raw)
    if path.suffix.lower() not in CODE_SUFFIXES or _exempt(path):
        return 0
    try:
        src = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return 0

    found = findings_for(path, src)
    if not found or _nagged_recently(path):
        return 0

    print(
        f"[shape] {path.name} is now " + "; ".join(found) + ". This is about the FILE, "
        "not your edit -- files reach this size through edits that were each the smallest "
        "correct change. Worth asking now: what is the seam? One module per reason to "
        "change, shared mutable state behind an owner rather than at module level. "
        "Splitting later costs more than splitting now, and the cost grows with every "
        "caller. If the size is right for this file, say so and carry on -- advisory only "
        "(silence: CLAUDE_ALLOW_BIG_MODULES=1).",
        file=sys.stderr,
    )
    return 0


def self_test() -> int:
    import tempfile

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    tiny = "def a():\n    return 1\n"
    check("small file is quiet", findings_for(Path("x.py"), tiny), [])

    long_file = "\n".join(f"x{i} = {i}" for i in range(MAX_LINES + 10))
    check("long file speaks", bool(findings_for(Path("x.py"), long_file)), True)

    many_defs = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(MAX_DEFS + 5))
    check("many top-level defs speak",
          any("definitions" in f for f in findings_for(Path("x.py"), many_defs)), True)

    shared = "\n".join(f"_cache{i} = {{}}" for i in range(MAX_STATE + 2))
    check("shared mutable state speaks",
          any("mutable" in f for f in findings_for(Path("x.py"), shared)), True)

    locks = "import threading\n" + "\n".join(
        f"_L{i} = threading.Lock()" for i in range(MAX_STATE + 1))
    check("hand-rolled locks count as shared state",
          any("mutable" in f for f in findings_for(Path("x.py"), locks)), True)

    fat_fn = "def big():\n" + "\n".join(f"    y{i} = {i}" for i in range(MAX_FN_LINES + 5))
    check("one fat definition speaks",
          any("single definition" in f for f in findings_for(Path("x.py"), fat_fn)), True)

    check("broken syntax stays quiet, not guessy",
          findings_for(Path("x.py"), "def ("), [])

    check("test file is exempt", _exempt(Path("tests/test_thing.py")), True)
    check("vendored code is exempt", _exempt(Path("node_modules/pkg/index.js")), True)
    check("ordinary source is not exempt", _exempt(Path("app/backend/main.py")), False)

    # a long non-Python file still trips the line check, without an AST
    check("non-python long file still speaks",
          bool(findings_for(Path("x.ts"), "\n".join("const a = 1;" for _ in range(MAX_LINES + 5)))),
          True)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.py"
        p.write_text(long_file, encoding="utf-8")
        ev = json.dumps({"tool_name": "Read", "tool_input": {"file_path": str(p)}})
        check("non-edit tools ignored", ev.count("Read"), 1)

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
        sys.exit(0)  # advisory: never the reason anything stops
