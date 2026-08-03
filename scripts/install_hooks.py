#!/usr/bin/env python3
"""install_hooks.py - register the always-on safety hooks into Claude Code settings.

Copies hook scripts from this repo's `hooks/` directory into the target
hooks directory (global or project-local) and merges a recommended hook
set into `settings.json`. Idempotent - re-running updates paths and
skips already-installed hooks.

Safety-critical hooks installed by default (--safe-defaults):

  - destructive-command-guard    PreToolUse    blocks rm -rf, DROP TABLE, etc.
  - secret-leak-guard            PreToolUse    blocks writes containing API keys
  - git-destructive-guard        PreToolUse    blocks git reset --hard, push --force
  - git-auto-backup              PreToolUse    creates branch snapshot before rewrites
  - session-drift-validator      SessionStart  reports broken file paths in CLAUDE.md
  - command-injection-guard      PreToolUse    blocks `cmd $(evil)` shell substitution
  - directory-creation-guard     PreToolUse    keeps new folders in project hierarchy
  - self-harm-guard              PreToolUse    stops agent from killing its own process

Opt-in extras (use --extras):
  - api-key-leak-detector        PostToolUse   scans tool output for leaked keys
  - test-muting-guard            PreToolUse    blocks adding @skip to existing tests
  - stop-phrase-guard            Stop          catches regression phrases
  - backup-retention-cleanup     Stop          trims old claude-backup branches
  - session-handoff-reminder     Stop          reminds to write handoff
  - session-handoff-check        SessionStart  surfaces recent handoffs
  - keyword-skill-router         UserPromptSubmit  suggests matching skills
  - task-inbox-show              SessionStart  surfaces .claude/task-inbox/ pending tasks
  - claude-attribution-guard     PreToolUse    blocks Co-Authored-By: Claude footers
  - human-confirmation-guard     PreToolUse    requires explicit user OK for deletions
  - db-snapshot-guard            PreToolUse    auto-snapshot before destructive SQL
  - verify-deleted-guard         PostToolUse   verifies destructive ops actually completed
  - file-cohesion-guard          PreToolUse    advisory: durable files belong in project structure
  - ask-question-guard           PreToolUse    blocks deferral/menu AskUserQuestion on reversible work
  - over-engineering-advisor     PostToolUse   advisory nudge on large/dependency-adding code changes
  - module-shape-advisor         PostToolUse   advisory nudge when one source file crosses shape thresholds
  - precompact-handoff-guard     PreCompact    demands a fresh handoff before context compaction
  - handoff-closure-audit-guard  PreToolUse    blocks handoff writes without closure audit
  - continuity-contract-guard    PreToolUse    protects incremental edits across Claude/Codex
  - continuity-session-check     SessionStart  surfaces the shared continuation contract
  - test-gate-stop-hook          Stop          selects fast/integration tests by Git-visible risk and blocks red/unproven evidence
  - harness-load-advisor         Stop          reports overloaded or mis-scoped test/release profiles
  - problems-md-validator        Stop          blocks closing with unresolved OPEN problems
  - plan-gate                    UserPromptSubmit  plan-artifact discipline for risky asks
  - conversation-history-capture Stop          archives and indexes local Codex session JSONL histories

Usage
-----
    # Preview what would be installed (no files written)
    python scripts/install_hooks.py --dry-run

    # Install the 7 safety-critical hooks globally
    python scripts/install_hooks.py --global

    # Same but under the current project's .claude/
    python scripts/install_hooks.py --local

    # Install everything (safe defaults + extras)
    python scripts/install_hooks.py --global --extras

    # Only update settings.json, skip copying scripts (if you already
    # have the repo linked)
    python scripts/install_hooks.py --global --skip-copy
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Safe-defaults: hooks that should be on in any project. Each entry:
#   (script filename in hooks/, hook event, optional "matcher" for fine-grained events)
SAFE_DEFAULTS: list[tuple[str, str, str | None]] = [
    ("destructive-command-guard.py", "PreToolUse", "Bash"),
    ("secret-leak-guard.py",         "PreToolUse", None),
    ("git-destructive-guard.py",     "PreToolUse", "Bash"),
    ("git-auto-backup.py",           "PreToolUse", "Bash"),
    ("command-injection-guard.py",   "PreToolUse", "Bash"),
    ("directory-creation-guard.py",  "PreToolUse", "Bash"),
    ("directory-creation-guard.py",  "PreToolUse", "PowerShell"),
    ("self-harm-guard.py",           "PreToolUse", "Bash"),
    ("session-drift-validator.py",   "SessionStart", None),
    ("continuity-contract-guard.py", "PreToolUse", "Write|Edit|MultiEdit|NotebookEdit"),
    ("continuity-session-check.py",  "SessionStart", None),
]

EXTRAS: list[tuple[str, str, str | None]] = [
    ("api-key-leak-detector.py",     "PostToolUse", None),
    ("test-muting-guard.py",         "PreToolUse", "Edit|Write"),
    ("stop-phrase-guard.py",         "Stop", None),
    ("backup-retention-cleanup.py",  "Stop", None),
    ("session-handoff-reminder.py",  "Stop", None),
    ("session-handoff-check.py",     "SessionStart", None),
    ("keyword-skill-router.py",      "UserPromptSubmit", None),
    ("task-inbox-show.py",           "SessionStart", None),
    ("claude-attribution-guard.py",  "PreToolUse", "Bash"),
    ("human-confirmation-guard.py",  "PreToolUse", "Bash"),
    ("db-snapshot-guard.py",         "PreToolUse", "Bash"),
    ("verify-deleted-guard.py",      "PostToolUse", "Bash"),
    ("file-cohesion-guard.py",       "PreToolUse", "Write|Edit"),
    ("ask-question-guard.py",        "PreToolUse", "AskUserQuestion"),
    ("over-engineering-advisor.py",   "PostToolUse", "Write|Edit|MultiEdit"),
    ("module-shape-advisor.py",        "PostToolUse", "Write|Edit|MultiEdit"),
    ("precompact-handoff-guard.py",  "PreCompact", None),
    ("handoff-closure-audit-guard.py", "PreToolUse", "Write|Edit|MultiEdit"),
    ("test-gate-stop-hook.py",       "Stop", None),
    ("harness-load-advisor.py",       "Stop", None),
    ("problems-md-validator.py",     "Stop", None),
    ("plan-gate.py",                 "UserPromptSubmit", None),
    ("conversation-history-capture.py", "Stop", None),
]

# Shared utility (not a hook itself - but needed by hooks)
SHARED = ["safety_common.py"]


def _resolve_targets(args: argparse.Namespace) -> tuple[Path, Path]:
    """Return (hooks_dir, settings_path)."""
    if args.global_install and args.local:
        sys.exit("ERROR: pick --global OR --local, not both")
    if args.local:
        base = Path.cwd() / ".claude"
    else:
        # default: global
        base = Path.home() / ".claude"
    return base / "hooks", base / "settings.json"


def _copy_script(src: Path, dst_dir: Path, dry_run: bool) -> Path:
    dst = dst_dir / src.name
    if dry_run:
        print(f"  [dry-run] would copy {src.name} -> {dst}")
        return dst
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    # Preserve executable bit on Unix
    if os.name != "nt":
        dst.chmod(dst.stat().st_mode | 0o755)
    return dst


def _load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        sys.exit(f"ERROR: {path} is not valid JSON - fix it manually before "
                 f"running this script (backup saved to {path}.bak)")


def _save_settings(path: Path, data: dict, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Backup existing
    if path.exists():
        backup = path.with_suffix(".json.bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(str(tmp), str(path))


def _script_name_from_command(command: str) -> str:
    """Best-effort script basename extraction from a hook command."""
    matches = re.findall(r"([^\\/\"'\s]+\.py)\b", command)
    return matches[-1].lower() if matches else ""


def _merge_hook(settings: dict, event: str, script_path: Path,
                matcher: str | None) -> bool:
    """Register one hook in settings. Returns True if added (False if duplicate)."""
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault(event, [])

    command = f"python {script_path}"
    script_name = script_path.name.lower()

    # Existing installs may point at a linked config repo instead of ~/.claude/hooks.
    # Treat the same script basename in the same event as installed to avoid duplicate
    # hooks firing on every matching tool call.
    for entry in settings["hooks"][event]:
        for h in entry.get("hooks", []):
            existing = h.get("command", "").strip()
            if existing == command or _script_name_from_command(existing) == script_name:
                return False  # already present

    new_entry: dict = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        new_entry["matcher"] = matcher
    settings["hooks"][event].append(new_entry)
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--global", dest="global_install", action="store_true",
                        help="Install to ~/.claude/ (available in all projects)")
    target.add_argument("--local", action="store_true",
                        help="Install to ./.claude/ (this project only)")
    p.add_argument("--extras", action="store_true",
                   help="Also install opt-in hooks (session-handoff, skill-router, ...)")
    p.add_argument("--skip-copy", action="store_true",
                   help="Do not copy .py files; only update settings.json "
                        "(use when scripts are already in target dir)")
    p.add_argument("--dry-run", action="store_true",
                   help="Preview changes, write nothing")
    args = p.parse_args()

    hooks_dir, settings_path = _resolve_targets(args)
    src_hooks_dir = REPO_ROOT / "hooks"

    if not src_hooks_dir.is_dir():
        sys.exit(f"ERROR: hooks source not found at {src_hooks_dir}")

    selection = list(SAFE_DEFAULTS)
    if args.extras:
        selection += EXTRAS

    print(f"Target hooks dir:   {hooks_dir}")
    print(f"Target settings:    {settings_path}")
    print(f"Hooks to install:   {len(selection)}")
    print()

    # 1. Copy hook scripts + shared utility
    if not args.skip_copy:
        # Shared utility first (hooks import from it)
        for name in SHARED:
            src = src_hooks_dir / name
            if src.exists():
                _copy_script(src, hooks_dir, args.dry_run)

        for name, _, _ in selection:
            src = src_hooks_dir / name
            if not src.exists():
                print(f"  SKIP (not found in repo): {name}")
                continue
            _copy_script(src, hooks_dir, args.dry_run)

    # 2. Update settings.json
    settings = _load_settings(settings_path)
    added = 0
    for name, event, matcher in selection:
        script_path = hooks_dir / name
        if _merge_hook(settings, event, script_path, matcher):
            added += 1
            print(f"  registered: {event:18} {name}{f'  ({matcher})' if matcher else ''}")
        else:
            print(f"  already present: {event:18} {name}")

    if added or args.dry_run:
        _save_settings(settings_path, settings, args.dry_run)

    print()
    if args.dry_run:
        print("Dry-run complete. Re-run without --dry-run to apply.")
    else:
        print(f"Done. {added} hook(s) added to {settings_path}")
        if settings_path.with_suffix(".json.bak").exists():
            print(f"Previous settings backed up to {settings_path.with_suffix('.json.bak')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
