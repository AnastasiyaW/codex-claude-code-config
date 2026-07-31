#!/usr/bin/env python3
"""sync_public_config.py - keep a PUBLIC config repo in sync with the ACTIVE ~/.claude.

Problem this solves: the active config (~/.claude) evolves daily; the public repo
(this one) goes stale silently. Blind copying is dangerous the other way: the active
config contains machine-specific rules/hooks (server names, IPs, local paths) that
must never reach a public repo.

Solution: manifest-driven one-way sync (active -> repo clone) with three safeguards:
  1. Only categories listed in sync-manifest.json are touched.
  2. "common" mode updates ONLY files already present in the repo; new active-only
     files are REPORTED as candidates, never auto-copied (a human promotes them by
     adding to "add" or copying manually).
  3. Every file written is scanned for privacy markers (machine names, IPs, user
     paths from the manifest); a hit skips the file and fails the run in --strict.

Usage:
  python scripts/sync_public_config.py              # dry-run report (default)
  python scripts/sync_public_config.py --apply      # actually copy
  python scripts/sync_public_config.py --scan-repo  # only scan the whole repo for markers
  python scripts/sync_public_config.py --strict     # non-zero exit on any marker hit

Comparison is EOL-normalized (CRLF==LF) so a git-clone on Windows does not produce
thousands of false "differs".
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "sync-manifest.json"

SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_DIRS = {"__pycache__", ".git"}


# A file whose last commit is newer than the active copy's mtime is a revert.
# The slack absorbs checkout/clock noise without hiding a real regression.
MTIME_SLACK = 120
# Removing this many lines without review is a stop, not a report line.
MAX_UNREVIEWED_DELETION = 30


def stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def repo_commit_times() -> dict[str, float]:
    """Last commit time per tracked path, in one pass over the log.

    Per-file `git log` calls would make the sync unusable on a repo this size,
    and a guard people disable for being slow protects nothing.
    """
    out: dict[str, float] = {}
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", "--name-only", "--format=%ct", "--no-merges"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return out
    if proc.returncode != 0:
        return out
    current: float | None = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.isdigit():
            current = float(line)
        elif current is not None:
            out.setdefault(line, current)   # log is newest-first, so first wins
    return out


def lines_removed(old_text: str, new_text: str) -> int:
    """Lines present in the repo version and absent from the incoming one."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = difflib.ndiff(old_lines, new_lines)
    return sum(1 for d in diff if d.startswith("- "))


def norm_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    except OSError:
        return None


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if p.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def marker_hits(text: str, markers: list[str]) -> list[str]:
    hits = []
    for m in markers:
        try:
            if re.search(m, text, re.IGNORECASE):
                hits.append(m)
        except re.error:
            if m.lower() in text.lower():
                hits.append(m)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any privacy-marker hit")
    ap.add_argument("--allow-regressions", action="store_true",
                    help="copy even when the repo version is newer or a large deletion is "
                         "proposed. Read the diff of every refused file first.")
    ap.add_argument("--scan-repo", action="store_true", help="only scan repo tree for markers")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"ERROR: manifest not found: {MANIFEST}", file=sys.stderr)
        return 2
    cfg = json.loads(MANIFEST.read_text(encoding="utf-8"))
    markers: list[str] = cfg.get("privacy_markers", [])
    active_root = Path(cfg["active_root"]).expanduser()

    any_marker_hit = False

    if args.scan_repo:
        print(f"== privacy scan of repo tree: {REPO_ROOT}")
        for f in iter_files(REPO_ROOT):
            if f == MANIFEST or f.resolve() == Path(__file__).resolve():
                continue  # manifest/scanner legitimately contain the marker strings
            text = norm_text(f)
            if text is None:
                continue
            hits = marker_hits(text, markers)
            if hits:
                any_marker_hit = True
                print(f"  MARKER {f.relative_to(REPO_ROOT)} :: {', '.join(hits)}")
        if not any_marker_hit:
            print("  clean - no privacy markers found")
        return 1 if (any_marker_hit and args.strict) else 0

    if not active_root.exists():
        print(f"ERROR: active root not found: {active_root}", file=sys.stderr)
        return 2

    updated, candidates, stale, skipped_private = [], [], [], []
    regressive: list[str] = []
    repo_times = repo_commit_times()

    for mapping in cfg["mappings"]:
        src_dir = active_root / mapping["from"]
        dst_dir = REPO_ROOT / mapping["to"]
        deny = set(mapping.get("deny", []))
        add = set(mapping.get("add", []))
        if not src_dir.exists():
            print(f"  WARN: source missing, skipping mapping: {src_dir}")
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)

        src_files = {p.relative_to(src_dir).as_posix(): p for p in iter_files(src_dir)}
        dst_files = {p.relative_to(dst_dir).as_posix(): p for p in iter_files(dst_dir)}

        for rel, sp in src_files.items():
            if rel in deny:
                continue
            in_repo = rel in dst_files
            promote = rel in add
            if not in_repo and not promote:
                candidates.append(f"{mapping['from']}/{rel}")
                continue
            s_text = norm_text(sp)
            if s_text is None:
                continue
            d_text = norm_text(dst_files[rel]) if in_repo else None
            if in_repo and s_text == d_text:
                continue
            hits = marker_hits(s_text, markers)
            if hits:
                any_marker_hit = True
                skipped_private.append(f"{mapping['from']}/{rel} :: {', '.join(hits)}")
                continue
            # Barrier 1 - freshness. The repository is declared the source of
            # truth, but this tool treats the active tree as authoritative. Run
            # it from a tree that has fallen behind and it silently reverts newer
            # work, reporting the loss as an ordinary line under `updated`.
            repo_rel = f"{mapping['to']}/{rel}"
            repo_time = repo_times.get(repo_rel)
            if (in_repo and not args.allow_regressions and repo_time is not None
                    and sp.stat().st_mtime < repo_time - MTIME_SLACK):
                regressive.append(f"{repo_rel} :: repo is newer "
                                  f"(committed {stamp(repo_time)}, active file {stamp(sp.stat().st_mtime)})")
                continue

            # Barrier 2 - volume. mtime is forgeable: a checkout or merge rewrites
            # it, so the first barrier can be fooled exactly when it matters. A
            # large unreviewed deletion is therefore a stop in its own right.
            if in_repo and d_text is not None and not args.allow_regressions:
                removed = lines_removed(d_text, s_text)
                if removed >= MAX_UNREVIEWED_DELETION:
                    regressive.append(f"{repo_rel} :: would remove {removed} lines "
                                      f"(limit {MAX_UNREVIEWED_DELETION})")
                    continue

            updated.append(f"{mapping['to']}/{rel}")
            if args.apply:
                target = dst_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sp, target)

        for rel in dst_files:
            if rel not in src_files:
                stale.append(f"{mapping['to']}/{rel}")

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"== sync report ({mode}) active={active_root} -> repo={REPO_ROOT}")
    print(f"-- updated ({len(updated)}):")
    for x in updated:
        print(f"   {x}")
    print(f"-- active-only candidates, NOT copied - promote manually ({len(candidates)}):")
    for x in candidates:
        print(f"   {x}")
    print(f"-- repo-only (in repo, absent in active - maybe genericized fork, review) ({len(stale)}):")
    for x in stale:
        print(f"   {x}")
    print(f"-- SKIPPED, privacy markers ({len(skipped_private)}):")
    for x in skipped_private:
        print(f"   {x}")
    print(f"-- REFUSED, would overwrite newer work ({len(regressive)}):")
    for x in regressive:
        print(f"   {x}")
    if regressive:
        print("   Run this from a tree that is up to date: git -C <active> pull, or copy")
        print("   the repository's version over the active one, then sync again. Override")
        print("   with --allow-regressions only after reading the diff of each file above.")

    if any_marker_hit and args.strict:
        return 1
    if regressive and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
