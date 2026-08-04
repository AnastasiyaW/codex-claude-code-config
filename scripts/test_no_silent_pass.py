#!/usr/bin/env python3
"""A checker must answer differently to an empty tree and a populated one.

The failure this catches has a name outside our house. In formal verification it is
VACUITY: a property that "passes" because its precondition never occurred. The canonical
example from the IBM Haifa work is exactly our shape -- "every request is eventually
followed by a grant" passes vacuously in a system where requests are never sent -- and
their answer is not a better assertion but a demand for an INTERESTING WITNESS: show a
run in which the precondition actually held.

The same idea reaches engineering twice. pytest gives "no tests collected" its own exit
code (5) rather than folding it into success, on the stated grounds that a project must
decide that policy deliberately instead of hiding a collection mistake. And mutation
testing answers "does this check have content" not by reading it but by breaking the
subject on purpose and seeing whether the check notices; a surviving mutant is a test
with the form of a test and none of its content.

So one probe is not enough. This runs each checker twice:

    empty tree      it must NOT claim a pass          (vacuity)
    populated tree  it must say something different   (witness)

A checker that gives the same answer to both is not looking at anything, whatever its
exit code says. One that cannot be aimed at a tree from outside is reported as
UNPROVABLE, and unprovable is not clean -- the first version of this file printed PASS
while eight of sixteen candidates were never tested, which is the very defect it exists
to catch, in the checker for that defect.

Sources: Beer, Ben-David, Eisner & Rodeh, "Efficient Detection of Vacuity in Temporal
Model Checking", FMSD 18(2) 2001; pytest exit codes; mutation-testing practice.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
SELF = {"test_no_silent_pass.py", "scan_report.py"}

SCANNING = re.compile(r"rglob|\.glob\(|iterdir|ls-files")
CLEAN_WORD = re.compile(r"\bclean\b|\bPASS\b|\bOK\b|no findings|0 findings", re.I)
EMPTY_WORD = re.compile(r"scanned nothing|no \w+ found|nothing to|not found|missing|"
                        r"absent|empty|does not exist|no such", re.I)
ROOT_FLAGS = ("--root", "--path", "--dir", "--tree")
TIMEOUT = 90


def candidates():
    for p in sorted(SCRIPTS.glob("*.py")):
        if p.name in SELF or p.name.startswith("test_"):
            continue
        src = p.read_text(encoding="utf-8-sig", errors="replace")
        if SCANNING.search(src) and CLEAN_WORD.search(src):
            yield p, src


def aim(path: Path, src: str, root: Path):
    """Run the checker against `root`. Returns (exit, output) or None if unaimable."""
    for flag in ROOT_FLAGS:
        if flag in src:
            argv = [sys.executable, str(path), flag, str(root)]
            break
    else:
        if not re.search(r"add_argument\(\s*[\"']roots?[\"']", src):
            return None
        argv = [sys.executable, str(path), str(root)]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT)
    except subprocess.SubprocessError:
        return None
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def classify(path: Path, src: str, empty: Path):
    on_empty = aim(path, src, empty)
    if on_empty is None:
        return "unprovable", "takes no root argument"
    e_code, e_out = on_empty

    on_real = aim(path, src, REPO)
    if on_real is None:
        return "unprovable", "aimable at empty but not at the repo"
    r_code, r_out = on_real

    # Vacuity: an empty tree must not read as a pass.
    if e_code == 0 and CLEAN_WORD.search(e_out) and not EMPTY_WORD.search(e_out):
        return "vacuous pass", (e_out.splitlines() or [""])[-1][:92]

    # Identical answers can mean two very different things, and collapsing them would
    # be its own version of form-without-content: "it is blind" and "I could not aim
    # it" deserve different responses. A usage error means it never reached the tree.
    if (e_code, e_out) == (r_code, r_out):
        if re.search(r"usage:|the following arguments are required|unrecognized arguments",
                     e_out, re.I):
            return "unprovable", "needs another required argument before it will scan"
        return "no witness", "identical answer to an empty tree and to the repo"

    return "has content", (e_out.splitlines() or ["(silent)"])[-1][:92]


def main() -> int:
    buckets: dict[str, list] = {"has content": [], "vacuous pass": [],
                                "no witness": [], "unprovable": []}
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "empty"
        empty.mkdir()
        for path, src in candidates():
            kind, note = classify(path, src, empty)
            buckets[kind].append((path.name, note))

    total = sum(len(v) for v in buckets.values())
    print(f"probed {total} checker(s): empty tree, then the real repo\n")
    for name, note in sorted(buckets["has content"]):
        print(f"  [content   ] {name:<36} says on empty: {note}")
    for name, note in sorted(buckets["unprovable"]):
        print(f"  [unprovable] {name:<36} {note}")
    for name, note in sorted(buckets["no witness"]):
        print(f"  [NO WITNESS] {name:<36} {note}")
    for name, note in sorted(buckets["vacuous pass"]):
        print(f"  [VACUOUS   ] {name:<36} {note}")

    defects = len(buckets["vacuous pass"]) + len(buckets["no witness"])
    unprovable = len(buckets["unprovable"])
    print(f"\n  content: {len(buckets['has content'])} | unprovable: {unprovable} | "
          f"vacuous: {len(buckets['vacuous pass'])} | no witness: {len(buckets['no witness'])}")

    if defects:
        print("\nRESULT: FAIL")
        print("  A checker that claims clean over nothing, or answers a populated tree")
        print("  exactly as it answers an empty one, has the form of a pass and none of")
        print("  its content. scan_report.verdict() cannot render that; use it.")
        return 1
    if unprovable:
        print("\nRESULT: INCOMPLETE")
        print(f"  {unprovable} checker(s) take no root argument, so they cannot be aimed at")
        print("  an empty tree from outside and this says nothing about them. Reporting")
        print("  PASS here would be the same defect one level up -- which is exactly what")
        print("  the first version of this file did.")
        return 0
    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
