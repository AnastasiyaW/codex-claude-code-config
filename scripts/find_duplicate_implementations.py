"""Find duplicated IMPLEMENTATION across the harness, not duplicated intent.

Two files may legitimately ask the same question for different reasons. What must not
happen is each carrying its own copy of the answer: they drift, and the copy nobody
re-reads is the one that goes stale. That already happened between module-shape-advisor
and architecture_audit; this looks for the rest.

Method: parse every hook and script, normalise each top-level function (drop the name,
the docstring, and all identifier spellings) and hash the resulting structure. Identical
hashes across files are the same code written twice. Also compares top-level constant
collections by value.
"""
import ast
import hashlib
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path.home() / ".claude" / "claude-code-config"
DIRS = ["hooks", "scripts"]
MIN_STATEMENTS = 4          # one-liners repeat innocently
SKIP = {"main", "self_test", "_render"}


class Normalise(ast.NodeTransformer):
    """Erase spellings so a renamed copy still matches its original."""

    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node):
        return ast.copy_location(ast.arg(arg="_", annotation=None), node)

    def visit_Attribute(self, node):
        self.generic_visit(node)
        return ast.copy_location(ast.Attribute(value=node.value, attr=node.attr, ctx=node.ctx), node)


def body_hash(fn):
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                       and isinstance(n.value.value, str))]
    if len(body) < MIN_STATEMENTS:
        return None, 0
    mod = ast.Module(body=[Normalise().visit(ast.parse(ast.unparse(n)).body[0]) for n in body],
                     type_ignores=[])
    return hashlib.sha1(ast.dump(mod).encode()).hexdigest()[:12], len(body)


funcs = defaultdict(list)
consts = defaultdict(list)
files = [p for d in DIRS for p in (R / d).glob("*.py")]

for p in files:
    try:
        tree = ast.parse(p.read_text(encoding="utf-8-sig", errors="replace"))
    except SyntaxError:
        continue
    rel = p.relative_to(R).as_posix()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.name in SKIP:
                continue
            h, size = body_hash(n)
            if h:
                funcs[h].append((rel, n.name, size))
        elif isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            name = n.targets[0].id
            if not name.isupper():
                continue
            try:
                v = ast.literal_eval(n.value)
            except (ValueError, TypeError):
                continue
            if isinstance(v, (set, frozenset, tuple, list, dict)) and len(v) >= 4:
                consts[repr(sorted(v) if isinstance(v, (set, frozenset)) else v)].append((rel, name))

print(f"scanned {len(files)} files in {', '.join(DIRS)}\n")

print("=== identical function bodies across files ===")
found = 0
for h, uses in sorted(funcs.items(), key=lambda kv: -kv[1][0][2]):
    where = {u[0] for u in uses}
    if len(where) < 2:
        continue
    found += 1
    print(f"\n  {uses[0][2]} statements, {len(uses)} copies:")
    for rel, name, _ in uses:
        print(f"      {rel:<44} {name}")
print("  none" if not found else "")

print("=== identical constant collections across files ===")
found_c = 0
for val, uses in consts.items():
    where = {u[0] for u in uses}
    if len(where) < 2:
        continue
    found_c += 1
    print(f"\n  value: {val[:88]}")
    for rel, name in uses:
        print(f"      {rel:<44} {name}")
print("  none" if not found_c else "")
print(f"\nduplicate function groups: {found} | duplicate constant groups: {found_c}")
