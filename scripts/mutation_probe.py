#!/usr/bin/env python3
"""mutation_probe.py - does a test actually fail when the code it guards breaks?

Idea taken from unclebob/mutator (https://github.com/unclebob/mutator); the tool
itself is not vendored. One mutation at a time is applied to the named functions
of a Python file inside a private copy of its folder, and the test command runs
against that copy. A mutant that the test does not notice "survives": the test
proves less than it claims. This automates what our rules already ask by hand
("proven by mutations", absence-of-signal rule 4: every instrument needs a case
that must go red).

Mutations: comparison flip (== !=, < >=, > <=, in / not in, is / is not), each
operator of a chain (a < b <= c) is its own site; arithmetic flip (+ <-> -,
* <-> /, // -> *); int literal 0->1, 1->0, n->n+1; bool literal True<->False
outside a return; and <-> or, dropped `not`, `return True/False` flipped, any
other `return X` replaced by `return None` (the null-return check).

Usage:
  python mutation_probe.py TARGET.py --function NAME [--function NAME ...] \
      --test "python tests/test_x.py" [--dir-env HOOKS_DIR] [--timeout SEC] [--work-root DIR]

The test command runs with cwd = the private copy of TARGET's folder; with
--dir-env the copy's path is also exported in that variable for tests that
locate the code through it. Without --timeout the per-mutant limit is
max(10 s, 10 x the baseline run time), the mutator's rule; the chosen limit is printed.
A test that outlives its limit is killed together with its whole process tree
(taskkill /T on Windows, process group on POSIX) and the mutant counts as killed.

Exit: 0 every mutant killed, 3 a mutant survived, 2 not checked (baseline test
already red, no mutation site found, bad arguments, private copy could not be
created or removed). Same three-state contract as check_aggregate.py;
`--self-test` carries the negative controls.
"""
from __future__ import annotations

import argparse
import ast
import copy
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

COMPARE_FLIP = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}
ARITH_FLIP = {
    ast.Add: ast.Sub, ast.Sub: ast.Add,
    ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Mult,
}
MIN_TIMEOUT = 10
BASELINE_TIMEOUT = 600  # cap for the baseline run when --timeout is not given
TIMED_OUT = 124


def _flip_label(before: type, after: type) -> str:
    return f"{before.__name__}->{after.__name__}"


def _literal_flip(value: object) -> object | None:
    """Replacement for an int or bool constant; None when the constant is not mutable."""
    if isinstance(value, bool):
        return not value
    if type(value) is int:
        return {0: 1, 1: 0}.get(value, value + 1)
    return None


def _sites(tree: ast.Module, functions: set[str]) -> list[tuple[int, int, str, int]]:
    """(node index in ast.walk order, operator index, label, line) for every mutable site in the named functions.

    The operator index is 0 except for a Compare, where each operator of a chain is its own site."""
    wanted: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions:
            wanted.update(id(child) for child in ast.walk(node))
    returned = {id(node.value) for node in ast.walk(tree)
                if isinstance(node, ast.Return) and node.value is not None}
    sites = []
    for index, node in enumerate(ast.walk(tree)):
        if id(node) not in wanted:
            continue
        found: list[tuple[int, str]] = []
        if isinstance(node, ast.Compare):
            for op_index, op in enumerate(node.ops):
                if type(op) in COMPARE_FLIP:
                    found.append((op_index, _flip_label(type(op), COMPARE_FLIP[type(op)])))
        elif isinstance(node, ast.BinOp) and type(node.op) in ARITH_FLIP:
            found.append((0, _flip_label(type(node.op), ARITH_FLIP[type(node.op)])))
        elif isinstance(node, ast.BoolOp):
            found.append((0, "and->or" if isinstance(node.op, ast.And) else "or->and"))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            found.append((0, "drop not"))
        elif isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
                found.append((0, f"return {not node.value.value}"))
            elif not (isinstance(node.value, ast.Constant) and node.value.value is None):
                found.append((0, "return None"))
        elif isinstance(node, ast.Constant) and _literal_flip(node.value) is not None:
            # A bool inside a return is already the "return X" site above.
            if not (isinstance(node.value, bool) and id(node) in returned):
                found.append((0, f"{node.value}->{_literal_flip(node.value)}"))
        line = getattr(node, "lineno", 0)
        sites.extend((index, op_index, label, line) for op_index, label in found)
    return sites


def _mutate(tree: ast.Module, index: int, op_index: int) -> str:
    tree = copy.deepcopy(tree)
    node = list(ast.walk(tree))[index]
    if isinstance(node, ast.Compare):
        node.ops[op_index] = COMPARE_FLIP[type(node.ops[op_index])]()
    elif isinstance(node, ast.BinOp):
        node.op = ARITH_FLIP[type(node.op)]()
    elif isinstance(node, ast.Constant):
        node.value = _literal_flip(node.value)
    elif isinstance(node, ast.BoolOp):
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif isinstance(node, ast.UnaryOp):
        replacement = node.operand
        for parent in ast.walk(tree):
            for field, value in ast.iter_fields(parent):
                if value is node:
                    setattr(parent, field, replacement)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if item is node:
                            value[i] = replacement
    elif isinstance(node, ast.Return):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
            node.value = ast.Constant(value=not node.value.value)
        else:
            node.value = ast.Constant(value=None)
    return ast.unparse(ast.fix_missing_locations(tree))


def _timeout_for(baseline_seconds: float, explicit: int | None) -> int:
    """Per-mutant limit: the explicit one, else max(MIN_TIMEOUT, 10 x baseline)."""
    if explicit is not None:
        return explicit
    return max(MIN_TIMEOUT, math.ceil(10 * baseline_seconds))


def _spawn(test: str, cwd: Path, env: dict) -> subprocess.Popen:
    """Start the test command as the leader of its own process group, so a timeout can reach its children."""
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        return subprocess.Popen(test, shell=True, cwd=cwd, env=env,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, **quiet)
    return subprocess.Popen(test, shell=True, cwd=cwd, env=env, start_new_session=True, **quiet)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the shell and everything it started. Killing only the shell leaves the python child running."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run(test: str, cwd: Path, env: dict, timeout: int) -> int:
    proc = _spawn(test, cwd, env)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.wait()
        return TIMED_OUT


def probe(target: Path, functions: set[str], test: str, dir_env: str | None, timeout: int | None,
          work_root: str | None = None) -> int:
    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source)
    sites = _sites(tree, functions)
    if not sites:
        print(f"UNKNOWN: no mutation site in {sorted(functions)} of {target}")
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix="mutation-probe-", dir=work_root) as tmp:
            return _check_copy(target, tree, source, sites, Path(tmp), test, dir_env, timeout)
    except OSError as exc:
        # Cleanup can fail while a leftover process still holds the copy (Windows: WinError 32).
        print(f"UNKNOWN: private copy could not be created or removed ({exc}); result not trusted")
        return 2


def _check_copy(target: Path, tree: ast.Module, source: str, sites: list, tmp: Path, test: str,
                dir_env: str | None, timeout: int | None) -> int:
    work = tmp / target.parent.name
    shutil.copytree(target.parent, work, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    copy_target = work / target.name
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if dir_env:
        env[dir_env] = str(work)
    started = time.monotonic()
    baseline_red = _run(test, work, env, timeout if timeout is not None else BASELINE_TIMEOUT) != 0
    baseline = time.monotonic() - started
    if baseline_red:
        print("UNKNOWN: baseline test is already red; mutants would prove nothing")
        return 2
    limit = _timeout_for(baseline, timeout)
    origin = "--timeout" if timeout is not None else f"auto: 10 x baseline {baseline:.1f} s, min {MIN_TIMEOUT} s"
    print(f"per-mutant timeout: {limit} s ({origin})")
    survivors = 0
    for index, op_index, label, line in sites:
        copy_target.write_text(_mutate(tree, index, op_index), encoding="utf-8")
        killed = _run(test, work, env, limit) != 0
        survivors += not killed
        print(f"  {'killed  ' if killed else 'SURVIVED'} line {line:<5} {label}")
    copy_target.write_text(source, encoding="utf-8")
    print(f"{len(sites) - survivors} of {len(sites)} mutants killed, {survivors} survived")
    return 3 if survivors else 0


SELF_TEST_CODE = '''
def is_adult(age):
    if 18 <= age < 150:
        return True
    return False

def months_to_adult(age):
    if age >= 18:
        return 0
    return (18 - age) * 12 + 1

def is_eligible(age, banned):
    allowed = True
    if banned and age < 150:
        allowed = False
    return allowed

def may_enter(banned):
    return not banned

def is_free(banned, minor):
    if banned or minor:
        return False
    return True

def halves(n):
    return n // 2
'''
SELF_TEST_FUNCTIONS = {"is_adult", "months_to_adult", "is_eligible", "may_enter", "is_free", "halves"}
SELF_TEST_IMPORT = ("import sys; sys.path.insert(0, '.'); from m import is_adult as f, months_to_adult as g, "
                    "is_eligible as h, may_enter as k, is_free as u, halves as p; ")
STRONG_TEST = (SELF_TEST_IMPORT +
               "assert f(18) is True and f(17) is False and f(149) is True and f(150) is False and f(30) is True "
               "and g(18) == 0 and g(20) == 0 and g(10) == 97 "
               "and h(20, False) is True and h(20, True) is False and h(150, True) is True "
               "and k(False) is True and k(True) is False "
               "and u(False, False) is True and u(True, False) is False and u(False, True) is False "
               "and p(5) == 2 and p(4) == 2")
# The null-return case: passes whatever the functions return, so every mutant must survive.
WEAK_TEST = SELF_TEST_IMPORT + "f(30); g(30); h(30, False); k(False); u(False, False); p(5)"

# Infinite-loop case: the 1->0 mutant of `i += 1` never ends. Every run appends its pid to
# MUTATION_PROBE_PIDFILE so the self-test can check that no test process outlives the probe.
LOOP_CODE = '''
def count_to(n):
    i = 0
    while i < n:
        i += 1
    return i
'''
LOOP_TEST = ("import os; open(os.environ['MUTATION_PROBE_PIDFILE'], 'a').write(str(os.getpid()) + ' '); "
             "import sys; sys.path.insert(0, '.'); from m import count_to as f; assert f(0) == 0 and f(3) == 3")
PIDFILE_ENV = "MUTATION_PROBE_PIDFILE"


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out.split()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


_REAL_TEMPDIR = tempfile.TemporaryDirectory


class _StuckDirectory:
    """Stands in for TemporaryDirectory when the copy cannot be removed (as on a locked Windows file)."""

    def __init__(self, **kwargs):
        self._inner = _REAL_TEMPDIR(**kwargs)

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, *exc):
        self._inner.__exit__(*exc)
        raise PermissionError(13, "held by another process")


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="mutation-probe-self-") as tmp:
        folder = Path(tmp) / "pkg"
        folder.mkdir()
        target = folder / "m.py"
        target.write_text(SELF_TEST_CODE, encoding="utf-8")
        py = f'"{sys.executable}" -c'
        sample_labels = {label for _, _, label, _ in _sites(ast.parse(SELF_TEST_CODE), SELF_TEST_FUNCTIONS)}
        chain_ops = sorted(op for _, op, label, _ in
                           _sites(ast.parse("def f(a, b, c):\n    return a < b <= c\n"), {"f"})
                           if label in ("Lt->GtE", "LtE->Gt"))

        loop_dir = Path(tmp) / "loop"
        loop_dir.mkdir()
        (loop_dir / "m.py").write_text(LOOP_CODE, encoding="utf-8")
        loop_work = Path(tmp) / "loop-work"
        loop_work.mkdir()
        pidfile = Path(tmp) / "pids.txt"
        os.environ[PIDFILE_ENV] = str(pidfile)
        try:
            loop_rc = probe(loop_dir / "m.py", {"count_to"}, f'{py} "{LOOP_TEST}"', None, 2, str(loop_work))
        finally:
            del os.environ[PIDFILE_ENV]
        loop_pids = [int(p) for p in pidfile.read_text().split()] if pidfile.exists() else []
        left_over = [pid for pid in loop_pids if _alive(pid)]

        tempfile.TemporaryDirectory = _StuckDirectory
        try:
            stuck_rc = probe(target, SELF_TEST_FUNCTIONS, f'{py} "{STRONG_TEST}"', None, 30)
        finally:
            tempfile.TemporaryDirectory = _REAL_TEMPDIR

        results = {
            "strong test kills all (explicit timeout)":
                probe(target, SELF_TEST_FUNCTIONS, f'{py} "{STRONG_TEST}"', None, 30) == 0,
            "strong test kills all (automatic timeout)":
                probe(target, SELF_TEST_FUNCTIONS, f'{py} "{STRONG_TEST}"', None, None) == 0,
            "arithmetic, literal, drop-not, or->and, // mutants exist in the sample":
                {"Add->Sub", "Sub->Add", "Mult->Div", "0->1", "1->0", "True->False",
                 "drop not", "or->and", "FloorDiv->Mult"} <= sample_labels,
            "chained comparison: each operator is its own site": chain_ops == [0, 1],
            "timeout rule: max(10 s, 10 x baseline) unless given":
                _timeout_for(0.2, None) == 10 and _timeout_for(3.0, None) == 30 and _timeout_for(3.0, 7) == 7,
            "weak test leaves survivors (negative control)":
                probe(target, SELF_TEST_FUNCTIONS, f'{py} "{WEAK_TEST}"', None, 30) == 3,
            "red baseline is UNKNOWN, not green":
                probe(target, SELF_TEST_FUNCTIONS, f'{py} "raise SystemExit(1)"', None, 30) == 2,
            "missing function is UNKNOWN": probe(target, {"nope"}, f'{py} "pass"', None, 30) == 2,
            "infinite-loop mutant is killed by timeout (exit 0 or 3, never 1)": loop_rc in (0, 3),
            "no test process survives the timeout (checked by pid)": bool(loop_pids) and not left_over,
            "work dir is removed after the infinite-loop run": not any(loop_work.iterdir()),
            "cleanup failure is UNKNOWN (exit 2), not a traceback": stuck_rc == 2,
        }
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?")
    parser.add_argument("--function", action="append", default=[])
    parser.add_argument("--test")
    parser.add_argument("--dir-env")
    parser.add_argument("--timeout", type=int, default=None,
                        help="per-mutant limit in seconds (default: max(10, 10 x baseline run time))")
    # For code whose tests behave differently inside the OS temp folder.
    parser.add_argument("--work-root", help="parent folder for the private copy (default: OS temp)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not (args.target and args.function and args.test) or not Path(args.target).is_file():
        print("UNKNOWN: need TARGET.py, at least one --function and --test")
        return 2
    return probe(Path(args.target).resolve(), set(args.function), args.test, args.dir_env, args.timeout,
                 args.work_root)


if __name__ == "__main__":
    sys.exit(main())
