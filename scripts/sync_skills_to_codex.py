#!/usr/bin/env python3
"""Synchronize this repo's shareable skills into active Codex and Claude directories.

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


def deployment_targets(
    codex_target: Path,
    codex_backup_root: Path,
    *,
    also_claude: bool,
    also_agents: bool,
    claude_target: Path,
    claude_backup_root: Path,
    agents_target: Path,
    agents_backup_root: Path,
) -> list[tuple[Path, Path]]:
    """Return distinct deployment roots with their independently recoverable backups."""
    targets = [(codex_target, codex_backup_root)]
    for enabled, target, backup_root in (
        (also_claude, claude_target, claude_backup_root),
        (also_agents, agents_target, agents_backup_root),
    ):
        if enabled and all(target != existing_target for existing_target, _ in targets):
            targets.append((target, backup_root))
    return targets


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=repo_root / "skills", help="repository skills directory")
    # Codex exposes both its user-level ~/.codex/skills and the shared
    # ~/.agents/skills runtime root. Deploy the latter only when --also-agents
    # is explicit: it can carry target-only skills owned outside this repository.
    # A project-local .agents/skills root is still deployed by passing --target.
    parser.add_argument("--target", type=Path, default=Path.home() / ".codex" / "skills",
                        help="active Codex skills directory (default: user-level ~/.codex/skills)")
    parser.add_argument("--backup-root", type=Path, default=Path.home() / ".codex" / "skill-backups")
    parser.add_argument(
        "--also-claude",
        action="store_true",
        help="also synchronize the same source into ~/.claude/skills",
    )
    parser.add_argument(
        "--also-agents",
        action="store_true",
        help="also synchronize the same source into the shared ~/.agents/skills Codex root",
    )
    parser.add_argument(
        "--agents-target",
        type=Path,
        default=Path.home() / ".agents" / "skills",
        help="shared Codex skills directory used with --also-agents",
    )
    parser.add_argument(
        "--agents-backup-root",
        type=Path,
        default=Path.home() / ".agents" / "skill-backups",
        help="backup root for changed ~/.agents/skills copies",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report drift without writing (default)")
    mode.add_argument("--apply", action="store_true", help="copy source files and back up changed targets")
    args = parser.parse_args(argv)

    if not args.source.is_dir():
        print(f"[skill-sync] source missing: {args.source}")
        return 2
    claude_target = Path.home() / ".claude" / "skills"
    claude_backup_root = Path.home() / ".claude" / "skill-backups"
    targets = deployment_targets(
        args.target,
        args.backup_root,
        also_claude=args.also_claude,
        also_agents=args.also_agents,
        claude_target=claude_target,
        claude_backup_root=claude_backup_root,
        agents_target=args.agents_target,
        agents_backup_root=args.agents_backup_root,
    )

    had_drift = False
    for target, backup_root in targets:
        changes, errors = sync(args.source, target, backup_root, args.apply)
        for error in errors:
            print(f"[skill-sync] ERROR {target}: {error}")
        if errors:
            return 2
        if changes:
            had_drift = True
            action = "remaining drift" if args.apply else "needs sync"
            print(f"[skill-sync] {action}: {target} ({len(changes)} skill(s))")
            for name, paths in sorted(changes.items()):
                print(f"  - {name}: {len(paths)} file(s)")
        else:
            state = "synchronized" if args.apply else "OK"
            print(f"[skill-sync] {state}: {target} ({len(source_skills(args.source))} skill(s))")
    return 1 if had_drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
