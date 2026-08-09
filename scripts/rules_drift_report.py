#!/usr/bin/env python3
"""Report how the LIVE rule tree and this repo's `rules/` differ, and why.

These two directories are **not** copies of each other and must never be
reconciled by copying one over the other:

* ``~/.claude/rules/``            - what the harness actually loads. Machine
  specific: real hostnames, real secret filenames, rules for boxes only this
  machine reaches. Not published anywhere.
* ``<this repo>/rules/``          - a drop-in starter set other people install.
  Deliberately redacted, and nothing on this machine loads it (verified: no
  reference in settings.json, CLAUDE.md or any hook).

Measured 2026-08-10 on this machine: of 29 shared filenames, 8 were byte
identical, 4 differed only by CRLF, and 17 differed in content - with **both**
sides adding lines in 16 of those 17. So "sync them" in either direction
destroys real content, and copying live -> repo additionally leaks concrete
secret filenames into a shareable tree. Hence a report, not a sync.

Run:  python scripts/rules_drift_report.py [--live DIR] [--repo DIR]
      python scripts/rules_drift_report.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

DEFAULT_LIVE = Path.home() / ".claude" / "rules"
DEFAULT_REPO = Path(__file__).resolve().parent.parent / "rules"


def _norm(path: Path) -> str:
    return hashlib.md5(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def classify(live: Path, repo: Path) -> dict[str, list[str]]:
    """Bucket every rule filename by how the two trees disagree."""
    buckets: dict[str, list[str]] = {
        "identical": [], "eol_only": [], "both_added": [],
        "live_superset": [], "repo_superset": [],
        "live_only": [], "repo_only": [],
    }
    live_names = {p.name for p in live.glob("*.md")} if live.is_dir() else set()
    repo_names = {p.name for p in repo.glob("*.md")} if repo.is_dir() else set()
    for name in sorted(live_names | repo_names):
        if name not in repo_names:
            buckets["live_only"].append(name)
            continue
        if name not in live_names:
            buckets["repo_only"].append(name)
            continue
        left, right = live / name, repo / name
        if left.read_bytes() == right.read_bytes():
            buckets["identical"].append(name)
            continue
        if _norm(left) == _norm(right):
            buckets["eol_only"].append(name)
            continue
        lines_l = {l for l in left.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").split("\n") if l}
        lines_r = {l for l in right.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").split("\n") if l}
        only_l, only_r = lines_l - lines_r, lines_r - lines_l
        if only_l and only_r:
            buckets["both_added"].append(f"{name} (+{len(only_l)} live / +{len(only_r)} repo)")
        elif only_l:
            buckets["live_superset"].append(f"{name} (+{len(only_l)} live)")
        else:
            buckets["repo_superset"].append(f"{name} (+{len(only_r)} repo)")
    return buckets


def report(live: Path, repo: Path) -> int:
    buckets = classify(live, repo)
    print(f"live: {live}\nrepo: {repo}\n")
    order = [
        ("identical", "byte-identical, nothing to do"),
        ("eol_only", "differ only by CRLF - cosmetic"),
        ("repo_superset", "repo has lines live lacks - candidate to pull IN, read them first"),
        ("live_superset", "live has lines repo lacks - candidate to publish, REDACT first"),
        ("both_added", "both sides added lines - merge by hand or leave alone, never copy"),
        ("live_only", "only on this machine - usually correct: machine-specific rules"),
        ("repo_only", "only in the repo - usually correct: retired here, still shipped to others"),
    ]
    for key, blurb in order:
        items = buckets[key]
        print(f"{key:15} {len(items):>3}  {blurb}")
        for item in items:
            print(f"                    {item}")
        print()
    print("Reminder: this is a report. Do not resolve it with a copy in either")
    print("direction - the repo tree is redacted on purpose and nothing loads it.")
    return 0


def _self_test() -> int:
    import tempfile

    fails: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        live, repo = tmp / "live", tmp / "repo"
        live.mkdir(), repo.mkdir()
        (live / "same.md").write_text("a\nb\n", encoding="utf-8")
        (repo / "same.md").write_text("a\nb\n", encoding="utf-8")
        (live / "eol.md").write_bytes(b"a\nb\n")
        (repo / "eol.md").write_bytes(b"a\r\nb\r\n")
        (live / "both.md").write_text("a\nonly-live\n", encoding="utf-8")
        (repo / "both.md").write_text("a\nonly-repo\n", encoding="utf-8")
        (live / "bigger.md").write_text("a\nb\nextra\n", encoding="utf-8")
        (repo / "bigger.md").write_text("a\nb\n", encoding="utf-8")
        (live / "smaller.md").write_text("a\n", encoding="utf-8")
        (repo / "smaller.md").write_text("a\nextra\n", encoding="utf-8")
        (live / "mine.md").write_text("x\n", encoding="utf-8")
        (repo / "theirs.md").write_text("y\n", encoding="utf-8")

        got = classify(live, repo)
        expected = {
            "identical": ["same.md"],
            "eol_only": ["eol.md"],
            "live_only": ["mine.md"],
            "repo_only": ["theirs.md"],
        }
        for key, want in expected.items():
            if got[key] != want:
                fails.append(f"{key}: expected {want}, got {got[key]}")
        for key, prefix in (("both_added", "both.md"), ("live_superset", "bigger.md"),
                            ("repo_superset", "smaller.md")):
            if len(got[key]) != 1 or not got[key][0].startswith(prefix):
                fails.append(f"{key}: expected one entry for {prefix}, got {got[key]}")

        # A missing tree must degrade to a listing, not an exception.
        try:
            classify(live, tmp / "nope")
        except Exception as exc:  # noqa: BLE001
            fails.append(f"missing repo tree raised {exc!r}")

    for line in fails:
        print("FAIL:", line)
    print("rules_drift_report self-test:", "FAILED" if fails else "ok")
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, default=DEFAULT_LIVE)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    return report(args.live, args.repo)


if __name__ == "__main__":
    sys.exit(main())
