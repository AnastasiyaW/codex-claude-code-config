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

import ast
import json
import os
import sys
import time
from pathlib import Path

# Calibration, not findings. Chosen to stay quiet on ordinary files and to have spoken
# early on the module described above -- it crossed every one of these many times over.
MAX_LINES = int(os.environ.get("CLAUDE_SHAPE_MAX_LINES", "800"))
MAX_DEFS = int(os.environ.get("CLAUDE_SHAPE_MAX_DEFS", "40"))
MAX_STATE = int(os.environ.get("CLAUDE_SHAPE_MAX_STATE", "6"))
MAX_FN_LINES = int(os.environ.get("CLAUDE_SHAPE_MAX_FN_LINES", "120"))

NAG_DAYS = 3  # per file, so a long session on one module is not a drumbeat

CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".php"}

# Test files legitimately grow long: a suite is a list of cases, not a design. Same for
# generated and vendored code, which nobody is going to restructure by hand.
EXEMPT_PARTS = {"node_modules", ".venv", "venv", "dist", "build", "__pycache__",
                "vendor", "third_party", "migrations", "generated", ".git"}
EXEMPT_NAME_HINTS = ("test_", "_test.", ".test.", ".spec.", "conftest", "_pb2")

MUTABLE_CALLS = {"Lock", "RLock", "Queue", "Event", "Semaphore", "defaultdict", "deque"}


def _exempt(path: Path) -> bool:
    if EXEMPT_PARTS & set(path.parts):
        return True
    name = path.name.lower()
    return any(h in name for h in EXEMPT_NAME_HINTS)


def python_shape(src: str) -> dict:
    """Structure of a Python module: defs, shared mutable state, longest function."""
    tree = ast.parse(src)
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    state = 0
    for n in tree.body:
        if not isinstance(n, (ast.Assign, ast.AnnAssign)):
            continue
        v = n.value
        if isinstance(v, (ast.Dict, ast.List, ast.Set)):
            state += 1
        elif isinstance(v, ast.Call):
            fn = getattr(getattr(v, "func", None), "attr", "") or \
                 getattr(getattr(v, "func", None), "id", "")
            if fn in MUTABLE_CALLS:
                state += 1
    longest = max((n.end_lineno - n.lineno + 1 for n in funcs + classes), default=0)
    return {"defs": len(funcs) + len(classes), "state": state, "longest_fn": longest}


def findings_for(path: Path, src: str) -> list[str]:
    lines = len(src.splitlines())
    out = []
    if lines >= MAX_LINES:
        out.append(f"{lines} lines in one file")

    if path.suffix == ".py":
        try:
            shape = python_shape(src)
        except SyntaxError:
            return out  # mid-edit or not valid yet; say nothing rather than guess
        if shape["defs"] >= MAX_DEFS:
            out.append(f"{shape['defs']} top-level definitions")
        if shape["state"] >= MAX_STATE:
            out.append(f"{shape['state']} module-level mutable objects shared by all of them")
        if shape["longest_fn"] >= MAX_FN_LINES:
            out.append(f"a single function of {shape['longest_fn']} lines")
    return out


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
    check("one fat function speaks",
          any("single function" in f for f in findings_for(Path("x.py"), fat_fn)), True)

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
