#!/usr/bin/env python3
"""Check or repair plugin hook metadata rejected by the Codex desktop loader.

Claude Code accepts a plugin-level ``description`` beside ``hooks``. The Codex
desktop loader currently rejects that field, so a plugin can fail to load before
any of its handlers are available. This script removes only that compatibility
metadata, makes a sibling backup, and never changes unknown fields.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


ALLOWED_TOP_LEVEL = {"hooks"}


@dataclass(frozen=True)
class Finding:
    path: Path
    extras: tuple[str, ...]

    @property
    def repairable(self) -> bool:
        return set(self.extras) == {"description"}


def hook_configs(cache: Path) -> list[Path]:
    return sorted(path for path in cache.rglob("hooks.json") if path.is_file())


def scan(cache: Path) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    errors: list[str] = []
    for path in hook_configs(cache):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: invalid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path}: root must be a JSON object")
            continue
        extras = tuple(sorted(set(data) - ALLOWED_TOP_LEVEL))
        if "hooks" not in data:
            errors.append(f"{path}: missing top-level hooks")
        if extras:
            findings.append(Finding(path, extras))
    return findings, errors


def repair(findings: list[Finding]) -> tuple[list[Path], list[str]]:
    repaired: list[Path] = []
    errors: list[str] = []
    for finding in findings:
        if not finding.repairable:
            errors.append(
                f"{finding.path}: unsupported keys {list(finding.extras)} are not auto-repairable"
            )
            continue
        try:
            data = json.loads(finding.path.read_text(encoding="utf-8-sig"))
            backup = finding.path.with_name(f"{finding.path.name}.bak")
            if not backup.exists():
                shutil.copy2(finding.path, backup)
            data.pop("description", None)
            finding.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            repaired.append(finding.path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{finding.path}: could not repair ({exc})")
    return repaired, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path.home() / ".codex" / "plugins" / "cache",
        help="Codex plugin cache directory",
    )
    parser.add_argument("--fix", action="store_true", help="remove repairable metadata and write backups")
    args = parser.parse_args(argv)

    if not args.cache.exists():
        print(f"[codex-plugin-hooks] cache absent: {args.cache}")
        return 0

    findings, errors = scan(args.cache)
    if args.fix and findings:
        repaired, repair_errors = repair(findings)
        errors.extend(repair_errors)
        if repaired:
            print(f"[codex-plugin-hooks] repaired: {len(repaired)}")
            for path in repaired:
                print(f"  - {path}")
        findings, rescan_errors = scan(args.cache)
        errors.extend(rescan_errors)

    for finding in findings:
        state = "repairable" if finding.repairable else "manual"
        print(f"[codex-plugin-hooks] {state}: {finding.path} -> {list(finding.extras)}")
    for error in errors:
        print(f"[codex-plugin-hooks] ERROR: {error}")

    if findings or errors:
        print("[codex-plugin-hooks] FAIL")
        return 1
    print(f"[codex-plugin-hooks] OK: {len(hook_configs(args.cache))} configs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
