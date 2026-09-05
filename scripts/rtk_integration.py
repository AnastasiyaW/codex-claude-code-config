#!/usr/bin/env python3
"""Verify and wire the optional RTK native Claude hook.

The public config repo stores the release pin and deterministic settings merger.
The executable remains an external, locally verified artifact; it is never
committed to this public repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PINNED_VERSION = "0.43.0"
WINDOWS_ASSET_SHA256 = "7c5e4a2ef816a4d4ed947ddd74ca3df851fc39ea87d49a3ca2bf3abc515a016b"
# Hash of rtk.exe extracted from the verified Windows ZIP above.
PINNED_BINARY_SHA256 = "a715e989bcebfc208f388cf5adaaa9953cbf1127b081bc09c4ef02e7d7fea39f"
WINDOWS_ASSET = (
    "https://github.com/rtk-ai/rtk/releases/download/v0.43.0/"
    "rtk-x86_64-pc-windows-msvc.zip"
)
HOOK_MATCHER = "Bash|PowerShell"
HOOK_STATUS = "Compact safe shell output with verified RTK; raw fallback stays available"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_version(binary: Path) -> str:
    result = subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{binary} --version failed with exit {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    parts = result.stdout.strip().split()
    if len(parts) < 2 or parts[0] != "rtk":
        raise RuntimeError(f"unexpected RTK version output: {result.stdout!r}")
    return parts[1]


def verify_binary(binary: Path) -> dict[str, str]:
    binary = binary.expanduser().resolve()
    if not binary.is_file():
        raise FileNotFoundError(f"RTK binary not found: {binary}")
    actual_version = read_version(binary)
    actual_sha256 = sha256_file(binary)
    if actual_version != PINNED_VERSION:
        raise RuntimeError(
            f"RTK version mismatch: expected {PINNED_VERSION}, got {actual_version}"
        )
    if actual_sha256 != PINNED_BINARY_SHA256:
        raise RuntimeError(
            "RTK executable SHA-256 mismatch: "
            f"expected {PINNED_BINARY_SHA256}, got {actual_sha256}"
        )
    return {
        "binary": str(binary),
        "version": actual_version,
        "sha256": actual_sha256,
    }


def verify_archive(archive: Path) -> dict[str, str]:
    archive = archive.expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"RTK release archive not found: {archive}")
    actual_sha256 = sha256_file(archive)
    if actual_sha256 != WINDOWS_ASSET_SHA256:
        raise RuntimeError(
            "RTK release ZIP SHA-256 mismatch: "
            f"expected {WINDOWS_ASSET_SHA256}, got {actual_sha256}"
        )
    return {"archive": str(archive), "sha256": actual_sha256}


def hook_command(binary: Path) -> str:
    """Return a settings command accepted by Claude's shell on Windows/POSIX."""
    resolved = binary.expanduser().resolve()
    executable = resolved.as_posix() if os.name == "nt" else str(resolved)
    args = [executable, "hook", "claude"]
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def build_hook_entry(binary: Path) -> dict[str, Any]:
    return {
        "matcher": HOOK_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": hook_command(binary),
                "statusMessage": HOOK_STATUS,
            }
        ],
    }


def merge_hook(settings: dict[str, Any], binary: Path) -> bool:
    hooks = settings.setdefault("hooks", {})
    pre_tool_use = hooks.setdefault("PreToolUse", [])
    command = hook_command(binary)
    for entry in pre_tool_use:
        for hook in entry.get("hooks", []):
            if hook.get("command") == command:
                return False
            existing = str(hook.get("command") or "").lower()
            if "rtk.exe" in existing and "hook claude" in existing:
                entry["matcher"] = HOOK_MATCHER
                hook["command"] = command
                hook["statusMessage"] = HOOK_STATUS
                return True
    pre_tool_use.append(build_hook_entry(binary))
    return True


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"settings file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"settings root must be an object: {path}")
    return data


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        shutil.copy2(path, backup)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            Path(temp_name).unlink()
        except OSError:
            pass
        raise


def install_claude_hook(settings_path: Path, binary: Path, apply: bool) -> dict[str, Any]:
    verification = verify_binary(binary)
    settings_path = settings_path.expanduser().resolve()
    settings = load_json(settings_path)
    changed = merge_hook(settings, binary)
    if changed and apply:
        write_json_atomic(settings_path, settings)
    return {
        **verification,
        "settings": str(settings_path),
        "changed": changed,
        "applied": bool(changed and apply),
        "hook_command": hook_command(binary),
    }


def print_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for key, value in result.items():
        print(f"{key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="verify a pinned RTK executable")
    verify.add_argument("--binary", type=Path, required=True)
    verify.add_argument("--json", action="store_true")

    archive = sub.add_parser("verify-archive", help="verify the pinned Windows release ZIP")
    archive.add_argument("--archive", type=Path, required=True)
    archive.add_argument("--json", action="store_true")

    install = sub.add_parser("install-claude-hook", help="merge the native hook into settings.json")
    install.add_argument("--binary", type=Path, required=True)
    install.add_argument("--settings", type=Path, required=True)
    install.add_argument("--apply", action="store_true", help="write settings; default is dry-run")
    install.add_argument("--json", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "verify":
            result = verify_binary(args.binary)
        elif args.command == "verify-archive":
            result = verify_archive(args.archive)
        else:
            result = install_claude_hook(args.settings, args.binary, args.apply)
        print_result(result, args.json)
        return 0
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"rtk-integration: ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
