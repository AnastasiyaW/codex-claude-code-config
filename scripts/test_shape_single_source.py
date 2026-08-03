#!/usr/bin/env python3
"""Regression: the two shape measurers must answer from one definition.

hooks/module-shape-advisor.py reacts to an edit; scripts/architecture_audit.py sweeps a
project. Different jobs, same question -- and they were written independently, so they
had already drifted: the audit exempted `coverage/` and the advisor did not, and the
advisor's thresholds were env-tunable while the audit carried a bare inline 800. Turning
the knob moved one verdict and not the other on the same file.

Two tools disagreeing about the same file is worse than either threshold being wrong,
because it teaches you to trust neither. This test fails if the shared definition is
bypassed again.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CFG = Path(__file__).resolve().parent.parent
ADVISOR = CFG / "hooks" / "module-shape-advisor.py"
AUDIT = CFG / "scripts" / "architecture_audit.py"


def _run(cmd, env, stdin=None):
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def main() -> int:
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "architecture.md").write_text("# arch\n", encoding="utf-8")
        target = root / "app.py"
        # comfortably under the default line threshold, comfortably over a lowered one
        target.write_text("\n".join(f"x{i} = {i}" for i in range(300)), encoding="utf-8")

        for label, limit, expected in (("default threshold", None, False),
                                       ("threshold lowered to 100", "100", True)):
            env = dict(os.environ)
            env.pop("CLAUDE_SHAPE_MAX_LINES", None)
            # the advisor keeps a per-file anti-nag stamp under HOME; give each run a
            # throwaway one so repetition is not mistaken for silence
            home = root / f"home-{limit or 'default'}"
            env["HOME"] = str(home)
            env["USERPROFILE"] = str(home)
            if limit:
                env["CLAUDE_SHAPE_MAX_LINES"] = limit

            ev = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
            adv = _run([sys.executable, str(ADVISOR)], env, stdin=ev)
            aud = _run([sys.executable, str(AUDIT), "--root", str(root)], env)

            adv_spoke = "[shape]" in (adv.stderr or "")
            aud_spoke = "app.py" in (aud.stdout or "")

            check(f"{label}: advisor", adv_spoke, expected)
            check(f"{label}: audit", aud_spoke, expected)
            check(f"{label}: they agree", adv_spoke == aud_spoke, True)
            check(f"{label}: advisor stays advisory", adv.returncode, 0)

    print("\nSHAPE SINGLE-SOURCE:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
