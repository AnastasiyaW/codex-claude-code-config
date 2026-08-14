"""Generate skills-lock.json for reproducible skill versioning.

Inspired by Multica's skills-lock.json pattern (multica-ai/multica).

Each skill is identified by:
  - path (relative to skills/)
  - content_hash (sha256 of canonical SKILL.md + all files under references/
    and scripts/)
  - size (total canonical bytes of tracked files)

Purpose:
  - Detect unintentional skill drift (someone edits SKILL.md and forgets to
    bump its declared version).
  - Let downstream consumers pin specific skill versions.
  - Make PR diffs on skills explicit: if skills-lock.json changes, something
    substantive changed.

Run:
    python scripts/generate_skills_lock.py              # write skills-lock.json
    python scripts/generate_skills_lock.py --check      # verify lock matches
                                                          filesystem (CI mode)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SKILL_FILES = ("SKILL.md",)           # the canonical entry
SKILL_DIRS = ("references", "scripts")  # content trees included in hash
IGNORED_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def _walk_skill(skill_dir: Path) -> list[Path]:
    """All files that contribute to a skill's identity."""
    files: list[Path] = []
    for fname in SKILL_FILES:
        fp = skill_dir / fname
        if fp.is_file():
            files.append(fp)
    for dname in SKILL_DIRS:
        subdir = skill_dir / dname
        if not subdir.is_dir():
            continue
        for fp in sorted(subdir.rglob("*")):
            if (
                fp.is_file()
                and not any(parent.name in IGNORED_DIRECTORY_NAMES for parent in fp.parents)
                and fp.suffix.lower() not in IGNORED_SUFFIXES
            ):
                files.append(fp)
    return files


def canonical_bytes(content: bytes) -> bytes:
    """Normalize text newlines so a checkout hashes identically on Windows/Linux.

    Skill bundles are predominantly text. Binary files retain their exact bytes,
    while UTF-8 text is normalized before it contributes to the portable lock.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def hash_skill(skill_dir: Path) -> dict:
    """Compute content hash + metadata for one skill."""
    files = _walk_skill(skill_dir)
    if not files:
        return None  # type: ignore[return-value]

    # Deterministic hash: sort by relative path, hash (path, content) pairs.
    hasher = hashlib.sha256()
    total_size = 0
    file_list = []

    for fp in sorted(files, key=lambda p: p.relative_to(skill_dir).as_posix()):
        rel = fp.relative_to(skill_dir).as_posix()
        content = canonical_bytes(fp.read_bytes())
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content)
        hasher.update(b"\0")
        total_size += len(content)
        file_list.append(rel)

    return {
        "content_hash": f"sha256:{hasher.hexdigest()}",
        "size_bytes": total_size,
        "file_count": len(files),
        "files": file_list,
    }


def scan_skills(root: Path) -> dict[str, dict]:
    """Find every SKILL.md under skills/, hash its directory."""
    skills_root = root / "skills"
    entries: dict[str, dict] = {}
    for skill_md in sorted(skills_root.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        rel = skill_dir.relative_to(skills_root).as_posix()
        data = hash_skill(skill_dir)
        if data is not None:
            entries[rel] = data
    return entries


def build_lock(root: Path) -> dict:
    entries = scan_skills(root)
    # Aggregate hash over all skills so top-level drift is trivially detectable.
    agg = hashlib.sha256()
    for key in sorted(entries.keys()):
        agg.update(key.encode("utf-8"))
        agg.update(b"\0")
        agg.update(entries[key]["content_hash"].encode("ascii"))
        agg.update(b"\0")
    return {
        "lockfile_version": 2,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "skill_count": len(entries),
        "aggregate_hash": f"sha256:{agg.hexdigest()}",
        "skills": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Verify skills-lock.json matches current filesystem "
                             "(exit 1 on drift). Intended for CI.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="Repository root (default: parent of scripts/)")
    parser.add_argument("--allow-empty", action="store_true",
                        help="write even when zero skills were found")
    parser.add_argument("--output", type=Path, default=None,
                        help="Lockfile path (default: <root>/skills-lock.json)")
    args = parser.parse_args()

    lock_path = args.output or (args.root / "skills-lock.json")
    current = build_lock(args.root)

    if args.check:
        if not lock_path.exists():
            print(f"[skills-lock] MISSING: {lock_path}")
            print("  Run: python scripts/generate_skills_lock.py")
            return 1
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
        # Compare the substantive parts (ignore generated_at timestamp).
        keys = ("lockfile_version", "skill_count", "aggregate_hash", "skills")
        drift = any(existing.get(k) != current.get(k) for k in keys)
        if drift:
            ex_skills = set(existing.get("skills", {}).keys())
            cu_skills = set(current.get("skills", {}).keys())
            added = cu_skills - ex_skills
            removed = ex_skills - cu_skills
            changed = {
                s for s in (ex_skills & cu_skills)
                if existing["skills"][s]["content_hash"] != current["skills"][s]["content_hash"]
            }
            print("[skills-lock] DRIFT DETECTED")
            if added:
                print(f"  Added:    {sorted(added)}")
            if removed:
                print(f"  Removed:  {sorted(removed)}")
            if changed:
                print(f"  Changed:  {sorted(changed)}")
            print("  Regenerate: python scripts/generate_skills_lock.py")
            return 1
        print(f"[skills-lock] OK: {current['skill_count']} skills, aggregate matches")
        return 0

    # An aggregate hash over zero skills is a real, stable, meaningless value -- the
    # SHA-256 of the empty string -- and committing it would replace the lock that
    # actually pins something. Zero inputs here means the root is wrong, which is the
    # case ESLint made fatal in v5 rather than reporting as success.
    if not current["skill_count"] and not args.allow_empty:
        print(f"[skills-lock] no skills found under {args.root} — refusing to write a "
              f"lock over nothing. Check the root, or pass --allow-empty.",
              file=sys.stderr)
        return 2

    lock_path.write_text(
        json.dumps(current, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[skills-lock] Wrote {lock_path}")
    print(f"  Skills: {current['skill_count']}")
    print(f"  Aggregate: {current['aggregate_hash']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
