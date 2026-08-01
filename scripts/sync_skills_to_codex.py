#!/usr/bin/env python3
"""Synchronize this repo's shareable skills into Codex's active skills directory.

The repository is the source of truth. The sync is additive: it updates every
source file and backs up an existing target skill before writing, but never
deletes target-only files without a separate, explicit cleanup decision.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path


SKIP_PARTS = {".git", "__pycache__"}


def source_skills(skills_root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for skill_md in sorted(skills_root.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        if any(part in SKIP_PARTS for part in skill_dir.parts):
            continue
        name = skill_dir.name
        previous = result.get(name)
        if previous and previous != skill_dir:
            raise ValueError(f"duplicate skill name {name}: {previous} and {skill_dir}")
        result[name] = skill_dir
    return result


def files_in(skill_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file() and not any(part in SKIP_PARTS for part in path.relative_to(skill_dir).parts)
    ]


def differences(source: Path, target: Path) -> list[Path]:
    missing_or_changed: list[Path] = []
    for source_file in files_in(source):
        relative = source_file.relative_to(source)
        target_file = target / relative
        if not target_file.is_file() or source_file.read_bytes() != target_file.read_bytes():
            missing_or_changed.append(relative)
    return missing_or_changed


def copy_source_files(source: Path, target: Path) -> None:
    for source_file in files_in(source):
        target_file = target / source_file.relative_to(source)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


def sync(source_root: Path, target_root: Path, backup_root: Path, apply: bool) -> tuple[dict[str, list[Path]], list[str]]:
    try:
        skills = source_skills(source_root)
    except ValueError as exc:
        return {}, [str(exc)]
    changes = {name: differences(source, target_root / name) for name, source in skills.items()}
    changes = {name: items for name, items in changes.items() if items}
    if not apply or not changes:
        return changes, []

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    for name in changes:
        source = skills[name]
        target = target_root / name
        if target.exists():
            backup = backup_root / stamp / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target, backup, dirs_exist_ok=True)
        copy_source_files(source, target)

    residual = {name: differences(skills[name], target_root / name) for name in changes}
    residual = {name: items for name, items in residual.items() if items}
    return residual, []


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=repo_root / "skills", help="repository skills directory")
    # Codex reads two roots: user-level ~/.codex/skills, and project-level .agents/skills
    # found by walking up from the cwd to the repository root. A home-level ~/.agents/skills
    # is neither, so syncing there reported "synchronized: N skill(s)" while Codex saw none
    # of them. Measured 2026-08-01 on two machines independently. Pass --target for the
    # project-level root of a specific repo.
    parser.add_argument("--target", type=Path, default=Path.home() / ".codex" / "skills",
                        help="active Codex skills directory (default: user-level ~/.codex/skills)")
    parser.add_argument("--backup-root", type=Path, default=Path.home() / ".codex" / "skill-backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report drift without writing (default)")
    mode.add_argument("--apply", action="store_true", help="copy source files and back up changed targets")
    args = parser.parse_args(argv)

    if not args.source.is_dir():
        print(f"[skill-sync] source missing: {args.source}")
        return 2
    changes, errors = sync(args.source, args.target, args.backup_root, args.apply)
    for error in errors:
        print(f"[skill-sync] ERROR: {error}")
    if errors:
        return 2
    if changes:
        action = "remaining drift" if args.apply else "needs sync"
        print(f"[skill-sync] {action}: {len(changes)} skill(s)")
        for name, paths in sorted(changes.items()):
            print(f"  - {name}: {len(paths)} file(s)")
        return 1
    state = "synchronized" if args.apply else "OK"
    print(f"[skill-sync] {state}: {len(source_skills(args.source))} skill(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
