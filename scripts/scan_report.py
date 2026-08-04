#!/usr/bin/env python3
"""You cannot say "clean" without saying what you scanned.

One failure form turned up in three different substances one night:

    a repeat that looked controlled while the variable under it moved;
    a column that reads as intent and stores history;
    a retelling that looks like verification unless you say what it is.

Everywhere the same thing: the FORM is available and gets taken for the presence of
CONTENT. An empty answer does not raise. A repeat that never pins its input proves
nothing. Another agent's report does not become a measurement by being retold.

This closes the first substance at the only place it can be closed -- the moment of
reporting. A checker that matched nothing and prints "clean" has produced the form of a
pass with none of its content, and the reader cannot tell the difference. So:

    verdict(...) REFUSES to render a pass when nothing was scanned.

It is not advice. There is no code path through this helper that produces "clean" and a
zero, because the whole defect is that such a path existed and looked fine.

    from scan_report import verdict
    return verdict("privacy scan", scanned=len(files), findings=hits, unit="file")

    clean   -> "privacy scan: clean - 497 files scanned"        exit 0
    findings-> "privacy scan: 3 findings across 497 files"      exit 1
    nothing -> "privacy scan: SCANNED NOTHING - expected files  exit 2
                under <root>; a check that matched nothing has
                not passed, it has not run"

Exit 2 is deliberate and distinct from 1: a real finding and a misconfigured checker
need different responses, and collapsing them is how a broken path gets "fixed" by
deleting the thing it could not find.

Self-test: python scan_report.py --self-test
"""
from __future__ import annotations

import sys


class ScannedNothing(RuntimeError):
    """Raised by verdict() when a check reports on an empty input set."""


def verdict(label: str, *, scanned: int, findings=None, unit: str = "item",
            where: str = "", stream=None, raise_on_empty: bool = False) -> int:
    """Render a verdict that always carries what it was based on.

    scanned  how many things were actually examined. Zero is never a pass.
    findings a count, or any sized collection; empty means clean.
    where    what was expected to be there, quoted back when nothing was found -- it is
             the single most useful thing to know when a checker scans nothing.
    """
    out = stream or sys.stdout
    n_find = findings if isinstance(findings, int) else len(findings or ())
    plural = "" if scanned == 1 else "s"

    if scanned <= 0:
        msg = (f"{label}: SCANNED NOTHING"
               + (f" - expected {unit}s under {where}" if where else "")
               + "; a check that matched nothing has not passed, it has not run")
        print(msg, file=out)
        if raise_on_empty:
            raise ScannedNothing(msg)
        return 2

    if n_find:
        print(f"{label}: {n_find} finding{'' if n_find == 1 else 's'} "
              f"across {scanned} {unit}{plural}", file=out)
        return 1

    print(f"{label}: clean - {scanned} {unit}{plural} scanned", file=out)
    return 0


def self_test() -> int:
    import io

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    def run(**kw):
        buf = io.StringIO()
        code = verdict("probe", stream=buf, **kw)
        return code, buf.getvalue().strip()

    code, text = run(scanned=497, findings=[])
    check("clean carries the count", (code, "497 files" in text.replace("items", "files")
                                      or "497 item" in text), (0, True))

    code, text = run(scanned=497, findings=["a", "b", "c"], unit="file")
    check("findings exit 1", code, 1)
    check("findings carry both numbers", "3 findings across 497 files" in text, True)

    code, text = run(scanned=0, findings=[], unit="file", where="skills/")
    check("empty is NOT a pass", code, 2)
    check("empty says so plainly", "SCANNED NOTHING" in text, True)
    check("empty quotes what was expected", "skills/" in text, True)
    check("empty exit is distinct from a finding", code != 1, True)

    code, text = run(scanned=1, findings=0)
    check("singular reads correctly", "1 item scanned" in text, True)

    code, text = run(scanned=42, findings=7)
    check("an int findings count works too", (code, "7 findings" in text), (1, True))

    try:
        run(scanned=0, raise_on_empty=True)
        check("raise_on_empty raises", False, True)
    except ScannedNothing:
        check("raise_on_empty raises", True, True)

    # the property that matters: no input produces a pass with a zero
    passes_with_zero = [s for s in (0,) if verdict("x", scanned=s, findings=[],
                                                   stream=io.StringIO()) == 0]
    check("no path yields a pass on zero", passes_with_zero, [])

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else 0)
