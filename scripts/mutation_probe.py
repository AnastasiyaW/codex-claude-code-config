#!/usr/bin/env python3
"""mutation_probe.py - does a test actually fail when the code it guards breaks?

Idea taken from unclebob/mutator (https://github.com/unclebob/mutator); the tool
itself is not vendored. One mutation at a time is applied to the named functions
of a Python file inside a private copy of its folder, and the test command runs
against that copy. A mutant that the test does not notice "survives": the test
proves less than it claims. This automates what our rules already ask by hand
("proven by mutations", absence-of-signal rule 4: every instrument needs a case
that must go red).

Mutations: comparison flip (== !=, < >=, > <=, in / not in, is / is not),
and <-> or, dropped `not`, `return True/False` flipped, any other `return X`
replaced by `return None` (the null-return check).

Usage:
  python mutation_probe.py TARGET.py --function NAME [--function NAME ...] \
      --test "python tests/test_x.py" [--dir-env HOOKS_DIR] [--timeout 60] [--work-root DIR]

The test command runs with cwd = the private copy of TARGET's folder; with
--dir-env the copy's path is also exported in that variable for tests that
locate the code through it.

Exit: 0 every mutant killed, 3 a mutant survived, 2 not checked (baseline test
already red, no mutation site found, bad arguments). Same three-state contract
as check_aggregate.py; `--self-test` carries the negative control.
"""
from __future__ import annotations

import argparse
import ast
import copy
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

COMPARE_FLIP = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}


def _sites(tree: ast.Module, functions: set[str]) -> list[tuple[int, str, str]]:
    """(node index in ast.walk order, label, line) for every mutable node in the named functions."""
    wanted: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions:
            wanted.update(id(child) for child in ast.walk(node))
    sites = []
    for index, node in enumerate(ast.walk(tree)):
        if id(node) not in wanted:
            continue
        label = None
        if isinstance(node, ast.Compare) and type(node.ops[0]) in COMPARE_FLIP:
            label = f"{type(node.ops[0]).__name__}->{COMPARE_FLIP[type(node.ops[0])].__name__}"
        elif isinstance(node, ast.BoolOp):
            label = "and->or" if isinstance(node.op, ast.And) else "or->and"
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            label = "drop not"
        elif isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
                label = f"return {not node.value.value}"
            elif not (isinstance(node.value, ast.Constant) and node.value.value is None):
                label = "return None"
        if label:
            sites.append((index, label, getattr(node, "lineno", 0)))
    return sites


def _mutate(tree: ast.Module, index: int) -> str:
    tree = copy.deepcopy(tree)
    node = list(ast.walk(tree))[index]
    if isinstance(node, ast.Compare):
        node.ops[0] = COMPARE_FLIP[type(node.ops[0])]()
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


def _run(test: str, cwd: Path, env: dict, timeout: int) -> int:
    try:
        return subprocess.run(test, shell=True, cwd=cwd, env=env, timeout=timeout,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except subprocess.TimeoutExpired:
        return 124


def probe(target: Path, functions: set[str], test: str, dir_env: str | None, timeout: int,
          work_root: str | None = None) -> int:
    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source)
    sites = _sites(tree, functions)
    if not sites:
        print(f"UNKNOWN: no mutation site in {sorted(functions)} of {target}")
        return 2
    with tempfile.TemporaryDirectory(prefix="mutation-probe-", dir=work_root) as tmp:
        work = Path(tmp) / target.parent.name
        shutil.copytree(target.parent, work, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        copy_target = work / target.name
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        if dir_env:
            env[dir_env] = str(work)
        if _run(test, work, env, timeout) != 0:
            print("UNKNOWN: baseline test is already red; mutants would prove nothing")
            return 2
        survivors = 0
        for index, label, line in sites:
            copy_target.write_text(_mutate(tree, index), encoding="utf-8")
            killed = _run(test, work, env, timeout) != 0
            survivors += not killed
            print(f"  {'killed  ' if killed else 'SURVIVED'} line {line:<5} {label}")
        copy_target.write_text(source, encoding="utf-8")
    print(f"{len(sites) - survivors} of {len(sites)} mutants killed, {survivors} survived")
    return 3 if survivors else 0


SELF_TEST_CODE = '''
def is_adult(age):
    if age >= 18 and age < 150:
        return True
    return False
'''
STRONG_TEST = ("import sys; sys.path.insert(0, '.'); from m import is_adult as f; "
               "assert f(18) is True and f(17) is False and f(149) is True and f(150) is False and f(30) is True")
# The null-return case: passes whatever the function returns, so every mutant must survive.
WEAK_TEST = "import sys; sys.path.insert(0, '.'); from m import is_adult as f; f(30)"


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="mutation-probe-self-") as tmp:
        folder = Path(tmp) / "pkg"
        folder.mkdir()
        target = folder / "m.py"
        target.write_text(SELF_TEST_CODE, encoding="utf-8")
        py = f'"{sys.executable}" -c'
        results = {
            "strong test kills all": probe(target, {"is_adult"}, f'{py} "{STRONG_TEST}"', None, 30) == 0,
            "weak test leaves survivors (negative control)": probe(target, {"is_adult"}, f'{py} "{WEAK_TEST}"', None, 30) == 3,
            "red baseline is UNKNOWN, not green": probe(target, {"is_adult"}, f'{py} "raise SystemExit(1)"', None, 30) == 2,
            "missing function is UNKNOWN": probe(target, {"nope"}, f'{py} "pass"', None, 30) == 2,
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
    parser.add_argument("--timeout", type=int, default=60)
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
