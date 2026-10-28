#!/usr/bin/env python3
"""crap_probe.py - which functions are both complex and poorly tested? (CRAP, advisory)

Idea taken from unclebob/crapper (https://github.com/unclebob/crapper); the tool
itself is not vendored. Per function: CRAP = CC^2 * (1 - cov)^3 + CC, where CC is
the cyclomatic complexity counted with `ast` (1 + each if/elif, for, while,
except handler, match case, comprehension `if`, conditional expression, and each
extra operand of `and`/`or`), and cov is the share of the function's lines that
the coverage run executed. A complex function with no tests scores high; the same
function fully covered scores exactly its CC.

Coverage input: `coverage json` output (files -> executed_lines / missing_lines).
A function in a file the coverage data does not mention is listed as not measured
and does not count toward the exit decision. Coverage keys are paths relative to
the directory coverage.py ran from: produce the JSON from the same root as the
PATH arguments you pass. A mismatched root shows up as functions not in the
coverage data, and the run says so (exit 2).

Usage:
  python crap_probe.py PATH [PATH ...] --coverage coverage.json \
      [--changed] [--threshold 10] [--fail-at 30]

--changed keeps only Python files changed against `git merge-base HEAD origin/main`
(falls back to every file, with a note, when that base cannot be found).

Advisory: a flagged function is reduced by splitting it (lower CC), testing it
(higher coverage), or both. Pairs with the testing-strategy skill.

Exit: 0 nothing at or above --fail-at, 3 something at or above --fail-at,
2 not checked: no, unreadable or malformed coverage file; a given path that is
missing, not Python, or does not parse; a non-finite threshold; or no Python
function of the given paths present in the coverage data. A requested input
that was not measured never exits 0.
Same three-state contract as check_aggregate.py; `--self-test` carries the
negative controls.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules"}


class CoverageError(Exception):
    pass


def _key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def load_coverage(path: Path) -> dict[str, tuple[set[int], set[int]]]:
    """Map normalized file path -> (executed line set, missing line set)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CoverageError(f"cannot read coverage file {path}: {exc}") from exc
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise CoverageError(f"{path} is not a coverage.py JSON report (no 'files' object)")
    result = {}
    for name, entry in files.items():
        if not isinstance(entry, dict):
            raise CoverageError(f"malformed coverage entry for {name}: not an object")
        executed = _line_set(entry.get("executed_lines", []), name)
        missing = _line_set(entry.get("missing_lines", []), name)
        result[_key(name)] = (executed, missing)
    return result


def _line_set(values, name: str) -> set[int]:
    if not isinstance(values, list) or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in values):
        raise CoverageError(f"malformed coverage entry for {name}: line lists must hold integers")
    return set(values)


def collect_files(paths) -> tuple[list[Path], list[str]]:
    """Python files under the given paths, plus the given inputs that yielded none."""
    found: dict[str, Path] = {}
    skipped: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            new = [f for f in sorted(p.rglob("*.py")) if not SKIP_DIRS & set(f.parts)]
            if not new:
                skipped.append(f"{raw}: no Python files")
            for f in new:
                found.setdefault(_key(f), f)
        elif p.is_file() and p.suffix == ".py":
            found.setdefault(_key(p), p)
        else:
            skipped.append(f"{raw}: not an existing Python file or folder")
    return list(found.values()), skipped


def functions_in(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """(qualified name, node) for every function, methods and nested functions included."""
    out: list[tuple[str, ast.AST]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, FUNC_TYPES):
                name = prefix + child.name
                out.append((name, child))
                visit(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def _own_nodes(fn: ast.AST):
    """Nodes of this function's body, not descending into nested defs or classes."""
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, SCOPE_TYPES):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def cyclomatic(fn: ast.AST) -> int:
    cc = 1
    for node in _own_nodes(fn):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            cc += 1
        elif isinstance(node, ast.BoolOp):
            cc += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            cc += len(node.ifs)
        elif type(node).__name__ == "match_case":
            cc += 1
    return cc


def coverage_of(fn: ast.AST, executed: set[int], missing: set[int]) -> float:
    lo, hi = fn.lineno, fn.end_lineno
    e = sum(1 for n in executed if lo <= n <= hi)
    m = sum(1 for n in missing if lo <= n <= hi)
    return e / (e + m) if e + m else 0.0


def crap_score(cc: int, cov: float) -> float:
    return cc * cc * (1 - cov) ** 3 + cc


def measure(files, cov, changed):
    """Rows for every function in the given files; returns (rows, unparsed notes)."""
    rows, unparsed = [], []
    for path in files:
        if changed is not None and _key(path) not in changed:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            unparsed.append(f"{path}: {exc}")
            continue
        data = cov.get(_key(path))
        for name, fn in functions_in(tree):
            cc = cyclomatic(fn)
            if data is None:
                rows.append({"file": str(path), "function": name, "line": fn.lineno,
                             "cc": cc, "cov": None, "crap": None})
                continue
            ratio = coverage_of(fn, *data)
            rows.append({"file": str(path), "function": name, "line": fn.lineno,
                         "cc": cc, "cov": ratio, "crap": crap_score(cc, ratio)})
    rows.sort(key=lambda r: (r["crap"] is None, -(r["crap"] or 0.0)))
    return rows, unparsed


def changed_files() -> tuple[set[str] | None, str]:
    try:
        base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], capture_output=True,
                              text=True, check=True).stdout.strip()
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, check=True).stdout.strip()
        names = subprocess.run(["git", "diff", "--name-only", "--diff-filter=ACMR", base],
                               capture_output=True, text=True, check=True).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        return None, f"changed set unavailable ({exc}); measuring all files"
    return ({_key(Path(top) / n) for n in names if n.endswith(".py")},
            f"changed against merge-base {base[:10]}")


def render(rows, threshold: float) -> str:
    head = ["file", "function", "line", "CC", "cov %", "CRAP", "flagged"]
    body = []
    for r in rows:
        if r["crap"] is None:
            body.append([r["file"], r["function"], str(r["line"]), str(r["cc"]), "n/a", "n/a",
                         "not in coverage"])
        else:
            body.append([r["file"], r["function"], str(r["line"]), str(r["cc"]),
                         f"{r['cov'] * 100:.0f}", f"{r['crap']:.1f}",
                         "yes" if r["crap"] >= threshold else ""])
    widths = [max(len(x) for x in col) for col in zip(head, *body)]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths)) for row in [head] + body)


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--coverage", required=True, help="coverage.py JSON report (coverage json)")
    parser.add_argument("--changed", action="store_true",
                        help="only files changed against merge-base with origin/main")
    parser.add_argument("--threshold", type=float, default=10.0, help="flag CRAP at or above this")
    parser.add_argument("--fail-at", type=float, default=30.0, help="exit 3 at or above this")
    args = parser.parse_args(argv)
    for name, value in (("--threshold", args.threshold), ("--fail-at", args.fail_at)):
        if not math.isfinite(value):
            print(f"UNKNOWN: {name} must be a finite number, got {value}")
            return 2

    try:
        cov = load_coverage(Path(args.coverage))
    except CoverageError as exc:
        print(f"UNKNOWN: {exc}")
        return 2
    files, skipped = collect_files(args.paths)
    if not files:
        print("UNKNOWN: no Python files under the given paths")
        return 2

    changed = None
    if args.changed:
        changed, note = changed_files()
        print(f"note: {note}")
    rows, unparsed = measure(files, cov, changed)
    unmeasured_inputs = skipped + unparsed
    for note in unmeasured_inputs:
        print(f"note: not measured: {note}")

    measured = [r for r in rows if r["crap"] is not None]
    if not measured:
        print("UNKNOWN: no function of the given paths is present in the coverage data")
        return 2

    print(render(rows, args.threshold))
    flagged = sum(1 for r in measured if r["crap"] >= args.threshold)
    at_fail = sum(1 for r in measured if r["crap"] >= args.fail_at)
    print(f"{len(measured)} measured, {flagged} flagged at >= {args.threshold:g}, "
          f"{at_fail} at or above --fail-at {args.fail_at:g}, "
          f"{len(rows) - len(measured)} not in coverage data")
    if unmeasured_inputs:
        print(f"UNKNOWN: {len(unmeasured_inputs)} given input(s) not measured; not checked")
        return 2
    return 3 if at_fail else 0


SAMPLE = '''
def simple(x):
    return x + 1


def branchy(a, b, items):
    if a and b:
        out = 1
    elif a or b:
        out = 2
    else:
        out = 3
    for i in items:
        if i > 0:
            out += i
    return [x for x in items if x]
'''
BOOL_SRC = "def g(a, b, c):\n    return a and b and c\n"
COMP_SRC = "def h(xs):\n    return [x for x in xs if x if x > 1]\n"


def naive_cc(fn: ast.AST) -> int:
    """Negative control: a counter that ignores boolean operands and comprehension ifs."""
    return 1 + sum(isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler))
                   for n in _own_nodes(fn))


def self_test() -> int:
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="crap-probe-self-") as tmp:
        folder = Path(tmp) / "pkg"
        folder.mkdir()
        mod = folder / "sample.py"
        mod.write_text(SAMPLE, encoding="utf-8")
        spans = {name: set(range(fn.lineno, fn.end_lineno + 1))
                 for name, fn in functions_in(ast.parse(SAMPLE))}

        def cov_file(name: str, executed: set[int], missing: set[int]) -> str:
            p = Path(tmp) / name
            p.write_text(json.dumps({"files": {str(mod): {
                "executed_lines": sorted(executed), "missing_lines": sorted(missing)}}}),
                encoding="utf-8")
            return str(p)

        uncovered = cov_file("uncovered.json", spans["simple"], spans["branchy"])
        full = cov_file("full.json", spans["simple"] | spans["branchy"], set())
        (Path(tmp) / "empty-files.json").write_text('{"files": {}}', encoding="utf-8")

        def quiet(argv):
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    return run(argv)
                except Exception:  # an uncaught error is a failed check, never a pass
                    return -1

        def branchy_row(cov_path):
            rows, _ = measure([mod], load_coverage(Path(cov_path)), None)
            return next(r for r in rows if r["function"] == "branchy")

        row = branchy_row(uncovered)
        results["branchy uncovered: CRAP >= 30 and exit 3"] = (
            row["crap"] >= 30 and quiet([str(mod), "--coverage", uncovered]) == 3)
        row = branchy_row(full)
        results["branchy fully covered: CRAP equals CC (8) and exit 0"] = (
            row["cc"] == 8 and row["crap"] == row["cc"] and quiet([str(mod), "--coverage", full]) == 0)
        results["missing coverage file: exit 2"] = quiet(
            [str(mod), "--coverage", str(Path(tmp) / "nope.json")]) == 2
        results["file absent from coverage data: exit 2 (nothing measured)"] = quiet(
            [str(mod), "--coverage", str(Path(tmp) / "empty-files.json")]) == 2
        bool_fn = ast.parse(BOOL_SRC).body[0]
        comp_fn = ast.parse(COMP_SRC).body[0]
        counted = cyclomatic(bool_fn) == 3 and cyclomatic(comp_fn) == 3
        results["complexity counts boolean operands and comprehension ifs"] = counted
        # Must-fail control: the naive counter gives 1 for both, so the check above would fail on it.
        results["negative control: naive counter (ignores operands/ifs) is caught"] = (
            naive_cc(bool_fn) != 3 and naive_cc(comp_fn) != 3)
        # Exact formula values: exponent 3 vs 4 gives 6.0 vs 5.0 at CC 4, cov 0.5.
        results["crap_score exact: CC 4, cov 0.5 gives 6.0"] = crap_score(4, 0.5) == 6.0
        results["crap_score exact: CC 2, cov 0 gives 6.0; CC 4, cov 1 gives 4.0"] = (
            crap_score(2, 0.0) == 6.0 and crap_score(4, 1.0) == 4.0)
        results["crap_score exact: CC 4, cov 0 gives 20.0"] = crap_score(4, 0.0) == 20.0
        cov_fn = ast.parse("def f():\n    a = 1\n    b = 2\n    c = 3\n").body[0]
        # Missing lines 2,3 are inside [1,4]; 0 and 5 are outside on each side. Ends 1 and 4 count.
        results["coverage_of: only lines inside the function, both ends counted"] = (
            coverage_of(cov_fn, {1, 4, 9}, {2, 3, 0, 5}) == 0.5)
        results["coverage_of: no statement lines gives 0.0"] = (
            coverage_of(cov_fn, set(), set()) == 0.0 and coverage_of(cov_fn, {9}, {8}) == 0.0)
        bad_lines = Path(tmp) / "bad-lines.json"
        bad_lines.write_text(json.dumps({"files": {str(mod): {
            "executed_lines": ["a"], "missing_lines": []}}}), encoding="utf-8")
        results["malformed coverage (non-integer lines): exit 2"] = quiet(
            [str(mod), "--coverage", str(bad_lines)]) == 2
        results["coverage file that is not a report: exit 2"] = quiet(
            [str(mod), "--coverage", str(mod)]) == 2
        broken = folder / "broken.py"
        broken.write_text("def oops(:\n", encoding="utf-8")
        results["given path that does not parse: exit 2"] = quiet(
            [str(broken), str(mod), "--coverage", full]) == 2
        results["given path that does not exist: exit 2"] = quiet(
            [str(folder / "ghost.py"), str(mod), "--coverage", full]) == 2
        results["non-finite --fail-at (nan): exit 2"] = quiet(
            [str(mod), "--coverage", full, "--fail-at", "nan"]) == 2
        results["non-finite --threshold (inf): exit 2"] = quiet(
            [str(mod), "--coverage", full, "--threshold", "inf"]) == 2
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    sys.exit(run())
