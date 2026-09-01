"""Clean up stale handoff files with TTL and orphan distinction.

Inspired by Multica's daemon GC pattern (multica-ai/multica server/internal/daemon/gc):
separate TTL for DONE items (CLOSED/RESUMED) vs ORPHAN items (ACTIVE but stale).

Without this, .claude/handoffs/ grows unbounded. With it, recent handoffs stay,
old closed ones vacate to archive, and orphaned ACTIVE handoffs get flagged (not
deleted - they may represent real work someone forgot to close).

Run:
    python scripts/cleanup_handoffs.py                    # dry run, report only
    python scripts/cleanup_handoffs.py --apply            # actually move/archive
    python scripts/cleanup_handoffs.py --done-ttl 14      # 14-day TTL for CLOSED
    python scripts/cleanup_handoffs.py --orphan-ttl 30    # 30-day ORPHAN flag

Design notes:
  - DONE (CLOSED / RESUMED / ABANDONED) -> move to archive after TTL
  - ORPHAN (ACTIVE but stale) -> print warning, do NOT auto-delete
    (could be long-running work; user decides)
  - Unknown status -> treat as orphan (safer)
  - INDEX.md is never touched (append-only invariant from principle 18)
"""
from __future__ import annotations

import argparse
from datetime import datetime
import re
import shutil
import sys
import time
from pathlib import Path


DONE_STATUSES = {"CLOSED", "RESUMED", "ABANDONED"}
ACTIVE_STATUSES = {"ACTIVE"}

STATUS_RE = re.compile(r"^\s*\*\*Status:\*\*\s*([A-Z-]+)", re.MULTILINE)
FILENAME_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})(?:_|\.)")


def handoff_timestamp(md_path: Path) -> float | None:
    """Return the canonical handoff timestamp encoded in its filename.

    A checkout, sync, or an archive move changes mtime, so mtime is not valid
    evidence of when a handoff was written. Files without the canonical
    ``YYYY-MM-DD_HH-MM_...`` prefix are not inventory candidates; they may be
    project notes that happen to live beside handoffs.
    """
    match = FILENAME_TIMESTAMP_RE.match(md_path.name)
    if not match:
        return None
    try:
        written = datetime.strptime(
            f"{match.group(1)}_{match.group(2)}-{match.group(3)}",
            "%Y-%m-%d_%H-%M",
        )
        return time.mktime(written.timetuple())
    except ValueError:
        return None


def inventory_handoffs(handoffs_dir: Path) -> tuple[list[Path], list[Path]]:
    """Return canonical flat/nested handoffs and non-canonical files skipped.

    The multi-session format stores one handoff directly below the project
    directory. Do not recurse beyond that contract: deeper markdown can be
    task evidence or an archived tree, neither of which is cleanup input.
    """
    candidates = list(handoffs_dir.glob("*.md")) + list(handoffs_dir.glob("*/*.md"))
    handoffs: list[Path] = []
    skipped: list[Path] = []
    for md_path in sorted(set(candidates)):
        relative = md_path.relative_to(handoffs_dir)
        if md_path.name.startswith("INDEX") or "archive" in relative.parts:
            continue
        if handoff_timestamp(md_path) is None:
            skipped.append(md_path)
            continue
        handoffs.append(md_path)
    return handoffs, skipped


def parse_status(md_path: Path) -> str:
    """Extract status from handoff frontmatter-style field."""
    try:
        # Read just the first 3KB - status is always near the top
        with md_path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(3000)
    except OSError:
        return "UNKNOWN"
    m = STATUS_RE.search(head)
    if not m:
        return "UNKNOWN"
    # RESUMED-by-XXX counts as RESUMED
    status = m.group(1).split("-")[0]
    return status


def classify(md_path: Path, now: float, done_ttl: int, orphan_ttl: int) -> str:
    """Classify handoff into: keep | archive | orphan."""
    status = parse_status(md_path)
    timestamp = handoff_timestamp(md_path)
    if timestamp is None:
        raise ValueError(f"non-canonical handoff filename: {md_path.name}")
    age_days = (now - timestamp) / 86400

    if status in DONE_STATUSES:
        if age_days > done_ttl:
            return "archive"
        return "keep"

    if status in ACTIVE_STATUSES or status == "UNKNOWN":
        if age_days > orphan_ttl:
            return "orphan"
        return "keep"

    return "keep"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=Path(".claude/handoffs"),
                        help="Handoffs directory (default: .claude/handoffs)")
    parser.add_argument("--done-ttl", type=int, default=14,
                        help="Days before archiving DONE handoffs (default 14)")
    parser.add_argument("--orphan-ttl", type=int, default=30,
                        help="Days before flagging ACTIVE as orphan (default 30)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually move files (default is dry run)")
    args = parser.parse_args()

    handoffs_dir = args.dir
    if not handoffs_dir.is_dir():
        print(f"[handoff-cleanup] No handoffs dir at {handoffs_dir} - nothing to do")
        return 0

    archive_dir = handoffs_dir / "archive"
    now = time.time()

    buckets = {"keep": [], "archive": [], "orphan": []}

    handoff_files, skipped_files = inventory_handoffs(handoffs_dir)
    for md_path in handoff_files:
        bucket = classify(md_path, now, args.done_ttl, args.orphan_ttl)
        buckets[bucket].append(md_path)

    print(f"[handoff-cleanup] Scanned {handoffs_dir}")
    print(f"  Keep:    {len(buckets['keep'])}")
    print(f"  Archive: {len(buckets['archive'])} (DONE, older than {args.done_ttl}d)")
    print(f"  Orphan:  {len(buckets['orphan'])} (ACTIVE/UNKNOWN, older than {args.orphan_ttl}d)")
    if skipped_files:
        print(f"  Skipped: {len(skipped_files)} (non-canonical filenames; no trustworthy handoff timestamp)")
    print()

    if buckets["orphan"]:
        print("ORPHANS (review manually - may be real forgotten work):")
        for p in sorted(buckets["orphan"]):
            age = (now - handoff_timestamp(p)) / 86400
            print(f"  {p.name}  ({age:.0f}d old, status={parse_status(p)})")
        print()

    if not args.apply:
        if buckets["archive"]:
            print("Would archive (dry run):")
            for p in sorted(buckets["archive"]):
                age = (now - handoff_timestamp(p)) / 86400
                print(f"  {p.name}  ({age:.0f}d old)")
            print()
            print("Run with --apply to actually move files.")
        return 0

    if buckets["archive"]:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for p in buckets["archive"]:
            target = archive_dir / p.name
            if target.exists():
                # Preserve uniqueness - handoff names include session-id already
                # but be defensive
                stem_i = 1
                while target.exists():
                    target = archive_dir / f"{p.stem}_{stem_i}{p.suffix}"
                    stem_i += 1
            try:
                shutil.move(str(p), str(target))
                print(f"  archived: {p.name} -> archive/{target.name}")
            except OSError as e:
                print(f"  SKIP (move failed): {p.name} - {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
