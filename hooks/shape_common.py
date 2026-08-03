#!/usr/bin/env python3
"""One definition of "what shape is this file in", shared by everything that asks.

Two tools ask the question for different reasons and must not answer it differently:

  hooks/module-shape-advisor.py   reacts to a single edit, per file, advisory
  scripts/architecture_audit.py   sweeps a whole project on demand, advisory

They were written independently and had already drifted on day one -- the audit
exempted `coverage/` and the advisor did not, and the advisor's four thresholds were
env-tunable while the audit carried a bare inline 800. Tuning CLAUDE_SHAPE_MAX_LINES
would have moved one verdict and not the other, on the same file, which is worse than
either threshold being wrong: two tools disagreeing teaches you to trust neither.

Same class as safety_common.py in this directory, and the same reason it exists.

Tuning (read once, at import):
    CLAUDE_SHAPE_MAX_LINES     default 800
    CLAUDE_SHAPE_MAX_DEFS      default 40
    CLAUDE_SHAPE_MAX_STATE     default 6
    CLAUDE_SHAPE_MAX_FN_LINES  default 120
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

# Calibration, not findings. Chosen to stay quiet on ordinary files and to have spoken
# early on the module that motivated this: 8823 lines, 190 handlers, 13 shared objects.
MAX_LINES = int(os.environ.get("CLAUDE_SHAPE_MAX_LINES", "800"))
MAX_DEFS = int(os.environ.get("CLAUDE_SHAPE_MAX_DEFS", "40"))
MAX_STATE = int(os.environ.get("CLAUDE_SHAPE_MAX_STATE", "6"))
MAX_FN_LINES = int(os.environ.get("CLAUDE_SHAPE_MAX_FN_LINES", "120"))

CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".php"}

# A test suite is a list of cases, not a design; generated and vendored code is nobody's
# to restructure by hand. `coverage` is here because the audit had it and the advisor did
# not -- the union is correct, and the disagreement was the whole problem.
EXEMPT_PARTS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "coverage",
    "__pycache__", "vendor", "third_party", "generated", "migrations",
}
EXEMPT_NAME_HINTS = ("test_", "_test.", ".test.", ".spec.", "conftest", "_pb2")

MUTABLE_CALLS = {"Lock", "RLock", "Queue", "Event", "Semaphore", "defaultdict", "deque"}


def is_exempt(path: Path) -> bool:
    if EXEMPT_PARTS & set(path.parts):
        return True
    name = path.name.lower()
    return any(hint in name for hint in EXEMPT_NAME_HINTS)


def python_shape(src: str) -> dict[str, int] | None:
    """Top-level definitions, shared mutable state, longest definition.

    Returns None on invalid syntax -- mid-edit or not parseable yet. Callers must stay
    silent in that case rather than guess; a shape advisory that fires on a half-typed
    file trains people to ignore it.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
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
            state += int(fn in MUTABLE_CALLS)
    longest = max((n.end_lineno - n.lineno + 1 for n in funcs + classes), default=0)
    return {"defs": len(funcs) + len(classes), "state": state, "longest_fn": longest}


def shape_findings(path: Path, src: str) -> list[str]:
    """Human-readable reasons this file has outgrown its shape. Empty means fine."""
    out = []
    lines = len(src.splitlines())
    if lines >= MAX_LINES:
        out.append(f"{lines} lines in one file")
    if path.suffix.lower() == ".py":
        shape = python_shape(src)
        if shape is None:
            return out
        if shape["defs"] >= MAX_DEFS:
            out.append(f"{shape['defs']} top-level definitions")
        if shape["state"] >= MAX_STATE:
            out.append(f"{shape['state']} module-level mutable objects shared by all of them")
        if shape["longest_fn"] >= MAX_FN_LINES:
            out.append(f"a single definition of {shape['longest_fn']} lines")
    return out


def self_test() -> int:
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    check("small file quiet", shape_findings(Path("x.py"), "def a():\n    return 1\n"), [])
    check("long file speaks",
          bool(shape_findings(Path("x.py"), "\n".join(f"x{i}=1" for i in range(MAX_LINES + 5)))), True)
    check("many defs speak",
          any("definitions" in f for f in shape_findings(
              Path("x.py"), "\n".join(f"def f{i}():\n    pass\n" for i in range(MAX_DEFS + 3)))), True)
    check("shared state speaks",
          any("mutable" in f for f in shape_findings(
              Path("x.py"), "\n".join(f"_c{i} = {{}}" for i in range(MAX_STATE + 2)))), True)
    check("locks count as state",
          any("mutable" in f for f in shape_findings(
              Path("x.py"), "import threading\n" + "\n".join(
                  f"_L{i} = threading.Lock()" for i in range(MAX_STATE + 1)))), True)
    check("fat definition speaks",
          any("single definition" in f for f in shape_findings(
              Path("x.py"), "def big():\n" + "\n".join(f"    y{i}=1" for i in range(MAX_FN_LINES + 3)))), True)
    check("invalid syntax stays quiet", shape_findings(Path("x.py"), "def ("), [])
    check("non-python long file still speaks",
          bool(shape_findings(Path("x.ts"), "\n".join("const a=1;" for _ in range(MAX_LINES + 5)))), True)
    check("test file exempt", is_exempt(Path("tests/test_thing.py")), True)
    check("coverage dir exempt", is_exempt(Path("coverage/report.py")), True)
    check("vendored exempt", is_exempt(Path("node_modules/p/i.js")), True)
    check("ordinary source not exempt", is_exempt(Path("app/backend/main.py")), False)

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    import sys
    sys.exit(self_test())
