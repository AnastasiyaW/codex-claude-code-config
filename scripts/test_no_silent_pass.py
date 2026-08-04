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
                    -- a COPY, never the live repo: the first version aimed
                    at the real tree and regenerated skills-lock.json, a probe
                    with a side effect on its own subject

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
import shutil
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

# A script that writes into the tree it is given is a producer, not a checker, and the
# two have different contracts. Cleaners count as producers here: "nothing to clean, exit
# 0" is correct for them and would be a vacuous pass for a checker.
PRODUCES = re.compile(r"\.write_text\(|\.write_bytes\(|shutil\.(copy|move|rmtree)|"
                      r"os\.replace|\.unlink\(|\.rename\(")
WROTE = re.compile(r"\bwrote\b|\bwritten\b|\bcreated\b|\bremoved\b|\bmoved\b|"
                   r"\bAggregate:|\bgenerated\b", re.I)


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


def _payload(out: str, root: Path) -> str:
    """The answer with its envelope stripped: the root path, any temp path, and digits.

    A neighbouring agent found this exact hole in a different detector -- an envelope
    carrying page numbers was counted as content, so an empty route read as healthy. The
    same shape here: two runs against two different directories differ in the directory
    they name, and that difference proves nothing about what either run saw.
    """
    text = out.replace(str(root), "<ROOT>").replace(root.as_posix(), "<ROOT>")
    text = re.sub(r"[A-Za-z]:[\\/][^\s\"']*?tmp[^\s\"']*", "<TMP>", text)
    text = re.sub(r"/tmp/[^\s\"']*", "<TMP>", text)
    # Digits are NOT normalised. An earlier version did, and that threw away the count --
    # which is the payload, not the envelope. "found 0 items" and "found 7 items" then
    # compared equal, so a checker that reported nothing looked exactly like one that
    # reported seven. That is the same failure this helper exists to remove, applied to
    # the other half of the string.
    return text.strip()


def classify(path: Path, src: str, empty: Path, populated: Path):
    on_empty = aim(path, src, empty)
    if on_empty is None:
        return "unprovable", "takes no root argument"
    e_code, e_out = on_empty

    on_real = aim(path, src, populated)
    if on_real is None:
        return "unprovable", "aimable at empty but not at the fixture"
    r_code, r_out = on_real

    # Vacuity, judged by EXIT CODE, not by the words.
    #
    # This used to look for "clean" in the text and for a phrase admitting emptiness.
    # That is form-matching, and it fails exactly where it matters: a checker whose count
    # sits one level deeper in its output, or which words its emptiness differently,
    # slips through the checker built to catch it. The same defect we hunt, in the hunter.
    #
    # Exit code is structural and cannot be phrased around. It is also the established
    # answer: pytest gives "no tests collected" its own code rather than folding it into
    # success, precisely so a pipeline cannot read one as the other. A checker that exits
    # 0 over an empty tree has told every caller it passed, whatever it printed for a
    # human who happens to be reading.
    # ...but only for a CHECKER. A generator or a cleaner has no pass/fail contract, so
    # "exit 0 having found nothing" is its correct behaviour, not a vacuous pass. Judging
    # them by the same rule flagged four of six wrongly, and a report that is wrong about
    # most of what it says trains its reader to skip it -- the failure this file exists
    # to prevent, arriving as noise instead of silence.
    #
    # Producers have their own version of the defect, and it is worth naming separately:
    # writing an artifact from an empty input. A skills catalogue of nothing is not a
    # pass, it is a lie with a filename.
    if PRODUCES.search(src):
        if e_code == 0 and WROTE.search(e_out):
            return "produced from nothing", (e_out.splitlines() or [""])[-1][:88]
        return "has content", "producer; nothing written on an empty tree"

    if e_code == 0:
        note = (e_out.splitlines() or ["(silent)"])[-1][:78]
        if EMPTY_WORD.search(e_out):
            return "vacuous pass", f"exit 0 on nothing (it does say so: {note})"
        return "vacuous pass", f"exit 0 on nothing: {note}"

    # Identical answers can mean two very different things, and collapsing them would
    # be its own version of form-without-content: "it is blind" and "I could not aim
    # it" deserve different responses. A usage error means it never reached the tree.
    # Compare with the ENVELOPE removed. The two trees have different paths, so a checker
    # that only echoes its root in a header produces two different strings while having
    # looked at nothing -- the wrapper counted as the payload. Normalising the paths and
    # the digits out is what distinguishes "it saw something" from "it printed where it
    # was pointed".
    if (e_code, r_code) == (e_code, r_code) and _payload(e_out, empty) == _payload(r_out, populated):
        if re.search(r"usage:|the following arguments are required|unrecognized arguments",
                     e_out, re.I):
            return "unprovable", "needs another required argument before it will scan"
        if e_out != r_out:
            return "no witness", "answers differ only in the path it was handed"
        return "no witness", "identical answer to an empty tree and to a populated one"

    return "has content", (e_out.splitlines() or ["(silent)"])[-1][:92]


def main() -> int:
    buckets: dict[str, list] = {"has content": [], "vacuous pass": [],
                                "produced from nothing": [],
                                "no witness": [], "unprovable": []}
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "empty"
        empty.mkdir()
        # The populated side is a COPY, never the live repository. Aiming the first
        # version at the real tree regenerated skills-lock.json: a probe with a side
        # effect on its own subject, which is the same class of defect it hunts.
        populated = Path(td) / "populated"
        populated.mkdir()
        for slice_ in ("skills/development", "rules", "principles"):
            src_dir = REPO / slice_
            if src_dir.is_dir():
                shutil.copytree(src_dir, populated / slice_, dirs_exist_ok=True)
        for path, src in candidates():
            kind, note = classify(path, src, empty, populated)
            buckets[kind].append((path.name, note))

    total = sum(len(v) for v in buckets.values())
    print(f"probed {total} checker(s): empty tree, then a copied fixture\n")
    for name, note in sorted(buckets["has content"]):
        print(f"  [content   ] {name:<36} says on empty: {note}")
    for name, note in sorted(buckets["unprovable"]):
        print(f"  [unprovable] {name:<36} {note}")
    for name, note in sorted(buckets["no witness"]):
        print(f"  [NO WITNESS] {name:<36} {note}")
    for name, note in sorted(buckets["vacuous pass"]):
        print(f"  [VACUOUS   ] {name:<36} {note}")
    for name, note in sorted(buckets["produced from nothing"]):
        print(f"  [FROM NOTHING] {name:<34} {note}")

    defects = (len(buckets["vacuous pass"]) + len(buckets["no witness"])
               + len(buckets["produced from nothing"]))
    unprovable = len(buckets["unprovable"])
    print(f"\n  content: {len(buckets['has content'])} | unprovable: {unprovable} | "
          f"vacuous: {len(buckets['vacuous pass'])} | "
          f"from nothing: {len(buckets['produced from nothing'])} | "
          f"no witness: {len(buckets['no witness'])}")

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
