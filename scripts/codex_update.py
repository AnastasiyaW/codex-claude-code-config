#!/usr/bin/env python3
"""Update the harness for Codex in one command: pull, re-register hooks, sync skills.

Codex has no plugin marketplace with auto-update, so a teammate keeps a clone of
this repository (canonical place: ~/.claude/claude-code-config) and runs:

    python ~/.claude/claude-code-config/scripts/codex_update.py [--extras]

Steps, each must succeed or the run stops with exit 1:
  1. refuse when tracked files have local edits (a pull would mix them in);
  2. git pull --ff-only;
  3. python scripts/install_hooks.py --codex [--extras]  -> ~/.codex/hooks.json;
  4. python scripts/sync_skills_to_codex.py --apply       -> ~/.codex/skills.
Exit 2 when the checkout is not a git repository (nothing was checked).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def git(*args: str) -> str:
    result = run(["git", *args])
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def step(name: str, cmd: list[str]) -> None:
    result = run(cmd)
    tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
    print(f"[{'ok' if result.returncode == 0 else 'FAIL'}] {name}")
    for line in tail:
        print(f"    {line}")
    if result.returncode != 0:
        raise RuntimeError(f"{name} exited {result.returncode}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extras", action="store_true", help="also register the opt-in hooks (install_hooks.py --extras)")
    args = parser.parse_args(argv)
    if run(["git", "rev-parse", "--git-dir"]).returncode != 0:
        print(f"not a git checkout: {REPO_ROOT}")
        return 2
    try:
        dirty = git("status", "--porcelain", "--untracked-files=no")
        if dirty:
            print("local edits in tracked files; commit or discard them first:\n" + dirty)
            return 1
        before = git("rev-parse", "--short", "HEAD")
        git("pull", "--ff-only")
        after = git("rev-parse", "--short", "HEAD")
        print(f"[ok] git pull: {before} -> {after}" if before != after else f"[ok] git pull: already at {after}")
        hooks_cmd = [sys.executable, "scripts/install_hooks.py", "--codex"] + (["--extras"] if args.extras else [])
        step("hooks -> ~/.codex/hooks.json", hooks_cmd)
        step("skills -> ~/.codex/skills", [sys.executable, "scripts/sync_skills_to_codex.py", "--apply"])
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("Codex harness is up to date. Restart Codex sessions to load the new hooks and skills.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
