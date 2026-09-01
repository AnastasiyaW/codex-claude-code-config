#!/usr/bin/env python3
"""install_hooks.py - register the always-on safety hooks into Claude Code settings.

Copies hook scripts from this repo's `hooks/` directory into the target
hooks directory (global or project-local) and merges a recommended hook
set into `settings.json`. When this repository itself is the canonical global
source at `~/.claude/claude-code-config`, it registers that source directly so
the installer does not revive a second active `~/.claude/hooks` tree.
Idempotent - re-running updates paths and skips already-installed hooks.

Safety-critical hooks installed by default (--safe-defaults):

  - destructive-command-guard    PreToolUse    blocks rm -rf, DROP TABLE, etc.
  - git-destructive-guard        PreToolUse    blocks destructive git history/branch operations
  - git-auto-backup              PreToolUse    creates branch snapshot before rewrites
  - session-drift-validator      SessionStart  reports broken file paths in CLAUDE.md
  - command-injection-guard      PreToolUse    blocks `cmd $(evil)` shell substitution
  - powershell-dynamic-execution-guard PreToolUse blocks untrusted data-to-code bridges in PowerShell
  - directory-creation-guard     PreToolUse    keeps new folders in project hierarchy
  - self-harm-guard              PreToolUse    stops agent from killing its own process
  - dependency-currency-guard    PreToolUse    checks package names and release age
  - dependency-provenance-guard  PreToolUse    protects registry and artifact provenance
  - transfer-contract-guard      Pre/Post/Stop requires a durable transfer record and verification

Opt-in extras (use --extras):
  - api-key-leak-detector        PostToolUse   scans tool output for leaked keys
  - test-muting-guard            PreToolUse    blocks adding @skip to existing tests
  - telegram-mass-send-guard     PreToolUse    blocks unrecallable Telegram bulk sends on either harness
  - stop-phrase-guard            Stop          catches regression phrases
  - backup-retention-cleanup     Stop          trims old claude-backup branches
  - session-handoff-reminder     Stop          reminds to write handoff
  - session-handoff-check        SessionStart  surfaces recent handoffs
  - keyword-skill-router         UserPromptSubmit  suggests matching skills
  - agent-skill-contract         Claude PreToolUse(Task): validates a rendered skill/evidence contract
  - subagent-skill-context       Codex SubagentStart: injects skill/evidence context into every child
  - subagent-evidence-receipt    Codex SubagentStop: requires a decision-source receipt
  - task-inbox-show              SessionStart  surfaces .claude/task-inbox/ pending tasks
  - claude-attribution-guard     PreToolUse    blocks Co-Authored-By: Claude footers
  - human-confirmation-guard     PreToolUse    blocks destructive actions until a host-verifiable approval API exists
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
  - outward-claim-evidence-guard Stop          blocks unmeasured hash/version/deploy claims in final reports
  - problems-md-validator        Stop          blocks closing with unresolved OPEN problems
  - plan-gate                    UserPromptSubmit  plan-artifact discipline for risky asks
  - user-task-completion-guard   Prompt/Start/Stop records every actionable user task and requires evidence-bound closure
  - conversation-history-capture Stop          archives and indexes local Codex session JSONL histories
  - session-feedback-capture    Stop          queues Claude/Codex sessions for human-gated correction distillation
  - feedback-pending-show       SessionStart  surfaces the bounded distillation backlog
  - shared-branch-guard          PreToolUse    protects marked checkouts shared by several workers

Usage
-----
    # Preview what would be installed (no files written)
    python scripts/install_hooks.py --dry-run

    # Install the 7 safety-critical hooks globally
    python scripts/install_hooks.py --global

    # Same but under the current project's .claude/
    python scripts/install_hooks.py --local

    # Install supported shared scripts into Codex desktop's user hook config
    python scripts/install_hooks.py --codex --extras

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
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Safe-defaults: hooks that should be on in any project. Each entry:
#   (script filename in hooks/, hook event, optional "matcher" for fine-grained events)
SAFE_DEFAULTS: list[tuple[str, str, str | None]] = [
    ("destructive-command-guard.py", "PreToolUse", "Bash"),
    ("git-destructive-guard.py",     "PreToolUse", "Bash"),
    ("git-auto-backup.py",           "PreToolUse", "Bash"),
    ("command-injection-guard.py",   "PreToolUse", "Bash"),
    ("powershell-dynamic-execution-guard.py", "PreToolUse", "PowerShell"),
    ("directory-creation-guard.py",  "PreToolUse", "Bash"),
    ("dependency-currency-guard.py", "PreToolUse", "Write|Edit|MultiEdit"),
    ("dependency-provenance-guard.py", "PreToolUse", "Bash|PowerShell"),
    ("directory-creation-guard.py",  "PreToolUse", "PowerShell"),
    ("transfer-contract-guard.py",    "PreToolUse", "Bash"),
    ("transfer-contract-guard.py",    "PreToolUse", "PowerShell"),
    ("transfer-contract-guard.py",    "PostToolUse", "Bash"),
    ("transfer-contract-guard.py",    "PostToolUse", "PowerShell"),
    ("transfer-contract-guard.py",    "Stop", None),
    ("self-harm-guard.py",           "PreToolUse", "Bash"),
    ("session-drift-validator.py",   "SessionStart", None),
    ("continuity-contract-guard.py", "PreToolUse", "Write|Edit|MultiEdit|NotebookEdit"),
    ("continuity-session-check.py",  "SessionStart", None),
]

EXTRAS: list[tuple[str, str, str | None]] = [
    ("api-key-leak-detector.py",     "PostToolUse", None),
    ("test-muting-guard.py",         "PreToolUse", "Edit|Write"),
    ("telegram-mass-send-guard.py",  "PreToolUse", "Bash|PowerShell"),
    ("stop-phrase-guard.py",         "Stop", None),
    ("backup-retention-cleanup.py",  "Stop", None),
    ("session-handoff-reminder.py",  "Stop", None),
    ("session-handoff-check.py",     "SessionStart", None),
    ("handoff-resume-gate.py",       "SessionStart", None),
    ("keyword-skill-router.py",      "UserPromptSubmit", None),
    ("agent-skill-contract.py",      "PreToolUse", "Task"),
    ("subagent-skill-context.py",    "SubagentStart", None),
    ("subagent-evidence-receipt.py", "SubagentStop", None),
    ("task-inbox-show.py",           "SessionStart", None),
    ("claude-attribution-guard.py",  "PreToolUse", "Bash"),
    ("human-confirmation-guard.py",  "PreToolUse", "Bash|PowerShell"),
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
    ("outward-claim-evidence-guard.py", "Stop", None),
    ("problems-md-validator.py",     "Stop", None),
    ("plan-gate.py",                 "UserPromptSubmit", None),
    ("user-task-completion-guard.py", "UserPromptSubmit", None),
    ("user-task-completion-guard.py", "SessionStart", None),
    ("user-task-completion-guard.py", "Stop", None),
    ("conversation-history-capture.py", "Stop", None),
    ("session-feedback-capture.py", "Stop", None),
    ("feedback-pending-show.py", "SessionStart", None),
    ("shared-branch-guard.py", "PreToolUse", "Bash|PowerShell"),
]

# Claude Code exposes a Task hook event; Codex desktop's native delegation API
# does not. Registering that matcher in Codex would create a silent dead
# control. Codex instead has SubagentStart, which can inject context but cannot
# inspect the parent task or cancel the launch.
CLAUDE_ONLY_EXTRAS = {"agent-skill-contract.py"}
CODEX_ONLY_EXTRAS = {"subagent-skill-context.py", "subagent-evidence-receipt.py"}

# Shared utility (not a hook itself - but needed by hooks)
SHARED = ["safety_common.py"]

# One local, unpushed implementation used a narrow batch-only name.  Retire its
# registrations when the generic task guard is installed, while settings.json
# is already backed up by _save_settings.  The source rename remains in Git.
REPLACED_HOOKS = {"batch-completion-guard.py": "user-task-completion-guard.py"}
COMMAND_SUFFIXES = {("user-task-completion-guard.py", "SessionStart"): " --session-start"}
GIT_HOOKS_SOURCE_DIR = REPO_ROOT / "scripts" / "git-hooks"


def _git_hooks_dir(home: Path) -> Path:
    """The live global ``core.hooksPath``; its contents are installed artifacts."""
    return home / ".claude" / "scripts" / "git-hooks"


def _install_git_pre_push(home: Path, dry_run: bool) -> tuple[Path, Path | None]:
    """Install the tracked pre-push wrapper, preserving a recoverable backup."""
    source = GIT_HOOKS_SOURCE_DIR / "pre-push"
    if not source.is_file():
        raise RuntimeError(f"tracked Git hook source is missing: {source}")
    destination = _git_hooks_dir(home) / "pre-push"
    if dry_run:
        print(f"  [dry-run] would install {source} -> {destination}")
        return destination, None
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if destination.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        backup = destination.with_name(f"pre-push.bak-{stamp}")
        serial = 1
        while backup.exists():
            backup = destination.with_name(f"pre-push.bak-{stamp}-{serial}")
            serial += 1
        shutil.copy2(destination, backup)
    shutil.copy2(source, destination)
    if os.name != "nt":
        destination.chmod(destination.stat().st_mode | 0o755)
    return destination, backup


def _resolve_targets(args: argparse.Namespace) -> tuple[Path, Path]:
    """Return (hooks_dir, settings_path)."""
    if args.codex:
        # The configuration is client-specific; global handlers are sourced
        # directly from the canonical tracked checkout.
        return _global_hooks_dir(REPO_ROOT, Path.home()), Path.home() / ".codex" / "hooks.json"
    if args.local:
        base = Path.cwd() / ".claude"
        return base / "hooks", base / "settings.json"
    # default: global
    return _global_hooks_dir(REPO_ROOT, Path.home()), Path.home() / ".claude" / "settings.json"


def _global_hooks_dir(repo_root: Path, home: Path) -> Path:
    """Return the one global hook tree without recreating a legacy copy."""
    canonical = home / ".claude" / "claude-code-config"
    if not canonical.exists():
        return repo_root / "hooks"
    try:
        is_canonical = repo_root.resolve() == canonical.resolve()
    except OSError:
        is_canonical = repo_root.absolute() == canonical.absolute()
    if not is_canonical:
        raise RuntimeError(
            "refusing global install from a non-canonical checkout; merge or "
            f"fast-forward it into {canonical} first"
        )
    return canonical / "hooks"


def _copy_script(src: Path, dst_dir: Path, dry_run: bool) -> Path:
    dst = dst_dir / src.name
    try:
        if src.resolve() == dst.resolve():
            return dst
    except OSError:
        pass
    if dry_run:
        print(f"  [dry-run] would copy {src.name} -> {dst}")
        return dst
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    # Preserve executable bit on Unix
    if os.name != "nt":
        dst.chmod(dst.stat().st_mode | 0o755)
    return dst


def _selection(args: argparse.Namespace) -> list[tuple[str, str, str | None]]:
    """Select hooks supported by the requested client without dead matchers."""
    selection = list(SAFE_DEFAULTS)
    if args.extras:
        selection += EXTRAS
    excluded = CLAUDE_ONLY_EXTRAS if args.codex else CODEX_ONLY_EXTRAS
    return [entry for entry in selection if entry[0] not in excluded]


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


def _command_for(script_path: Path, event: str, client_profile: str | None = None) -> str:
    """Return the cross-harness command form used by the Codex hook runner.

    Codex interprets an unquoted backslash path as a workspace-relative
    argument (dropping ``C:``). Existing healthy registrations use a quoted
    forward-slash Windows path, which both Claude and Codex pass to Python
    unchanged.
    """
    suffix = COMMAND_SUFFIXES.get((script_path.name, event), "")
    if script_path.name == "keyword-skill-router.py" and event == "UserPromptSubmit":
        profile = client_profile if client_profile in {"claude", "codex"} else "shared"
        suffix = f" --profile {profile}"
    return f'python "{script_path.as_posix()}"{suffix}'


def _merge_hook(settings: dict, event: str, script_path: Path,
                matcher: str | None, client_profile: str | None = None) -> str:
    """Register one hook and return its added/repaired/deduplicated state.

    A hook identity is ``event + matcher + script``.  The same script can
    deliberately serve Bash and PowerShell through separate matcher groups;
    collapsing only by basename loses coverage.  Conversely, a duplicate in
    the same event and matcher fires twice and must be collapsed while this
    installer already owns a backed-up configuration write.
    """
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault(event, [])

    command = _command_for(script_path, event, client_profile)
    script_name = script_path.name.lower()
    groups = settings["hooks"][event]
    matches: list[dict] = []
    for entry in groups:
        if (entry.get("matcher") or None) != matcher:
            continue
        for hook in entry.get("hooks", []):
            if _script_name_from_command(str(hook.get("command", ""))) == script_name:
                matches.append(hook)

    if matches:
        # Keep the earliest registration and its status message; subsequent
        # same-trigger copies are not independent behavior.
        winner = matches[0]
        repaired = winner.get("command", "").strip() != command
        winner["command"] = command
        if len(matches) == 1:
            return "repaired" if repaired else "present"

        retained_groups = []
        for entry in groups:
            if (entry.get("matcher") or None) != matcher:
                retained_groups.append(entry)
                continue
            retained_hooks = [
                hook for hook in entry.get("hooks", [])
                if hook is winner
                or _script_name_from_command(str(hook.get("command", ""))) != script_name
            ]
            if retained_hooks:
                retained_groups.append({**entry, "hooks": retained_hooks})
        settings["hooks"][event] = retained_groups
        return "deduplicated"

    hook: dict = {"type": "command", "command": command}
    if script_name == "outward-claim-evidence-guard.py":
        hook["statusMessage"] = "Checking evidence for reported facts..."
    new_entry: dict = {"hooks": [hook]}
    if matcher:
        new_entry["matcher"] = matcher
    settings["hooks"][event].append(new_entry)
    return "added"


def _remove_replaced_hooks(settings: dict) -> int:
    """Remove registrations superseded by a selected generic hook.

    Only command entries naming the old basename are removed.  Empty matcher
    groups disappear too, so the resulting config has no inert hook groups.
    """
    removed = 0
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return removed
    obsolete = {name.lower() for name in REPLACED_HOOKS}
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        retained_groups = []
        for group in groups:
            if not isinstance(group, dict):
                retained_groups.append(group)
                continue
            raw_hooks = group.get("hooks")
            if not isinstance(raw_hooks, list):
                retained_groups.append(group)
                continue
            retained_hooks = [
                hook for hook in raw_hooks
                if not (isinstance(hook, dict)
                        and _script_name_from_command(str(hook.get("command", ""))) in obsolete)
            ]
            removed += len(raw_hooks) - len(retained_hooks)
            if retained_hooks:
                retained_groups.append({**group, "hooks": retained_hooks})
        hooks[event] = retained_groups
    return removed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--global", dest="global_install", action="store_true",
                        help="Install to ~/.claude/ (available in all projects)")
    target.add_argument("--local", action="store_true",
                        help="Install to ./.claude/ (this project only)")
    target.add_argument("--codex", action="store_true",
                        help="Install to ~/.codex/hooks.json using canonical tracked hook scripts")
    target.add_argument("--git-hooks", action="store_true",
                        help="Install tracked pre-push wrapper to global core.hooksPath (backs up old wrapper)")
    p.add_argument("--extras", action="store_true",
                   help="Also install opt-in hooks (session-handoff, skill-router, ...)")
    p.add_argument("--skip-copy", action="store_true",
                   help="Do not copy .py files; only update settings.json "
                        "(use when scripts are already in target dir)")
    p.add_argument("--dry-run", action="store_true",
                        help="Preview changes, write nothing")
    args = p.parse_args()

    if args.git_hooks:
        try:
            destination, backup = _install_git_pre_push(Path.home(), args.dry_run)
        except RuntimeError as exc:
            sys.exit(f"ERROR: {exc}")
        if args.dry_run:
            print("Dry-run complete. Re-run without --dry-run to apply.")
        else:
            print(f"Installed tracked pre-push wrapper: {destination}")
            if backup is not None:
                print(f"Previous wrapper backed up to: {backup}")
        return 0

    try:
        hooks_dir, settings_path = _resolve_targets(args)
    except RuntimeError as exc:
        sys.exit(f"ERROR: {exc}")
    src_hooks_dir = REPO_ROOT / "hooks"

    if not src_hooks_dir.is_dir():
        sys.exit(f"ERROR: hooks source not found at {src_hooks_dir}")

    selection = _selection(args)

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
    removed = _remove_replaced_hooks(settings) if args.extras else 0
    added = 0
    repaired = 0
    deduplicated = 0
    for name, event, matcher in selection:
        script_path = hooks_dir / name
        result = _merge_hook(
            settings,
            event,
            script_path,
            matcher,
            "codex" if args.codex else "claude",
        )
        if result == "added":
            added += 1
            print(f"  registered: {event:18} {name}{f'  ({matcher})' if matcher else ''}")
        elif result == "repaired":
            repaired += 1
            print(f"  repaired:   {event:18} {name}")
        elif result == "deduplicated":
            deduplicated += 1
            print(f"  deduplicated: {event:15} {name}")
        else:
            print(f"  already present: {event:18} {name}")

    if added or repaired or deduplicated or removed or args.dry_run:
        _save_settings(settings_path, settings, args.dry_run)

    print()
    if args.dry_run:
        print("Dry-run complete. Re-run without --dry-run to apply.")
    else:
        print(f"Done. {added} hook(s) added; {repaired} command(s) repaired; {deduplicated} duplicate registration(s) removed; {removed} obsolete registration(s) removed from {settings_path}")
        if settings_path.with_suffix(".json.bak").exists():
            print(f"Previous settings backed up to {settings_path.with_suffix('.json.bak')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
