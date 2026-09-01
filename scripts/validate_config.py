#!/usr/bin/env python3
"""
Config Drift Validator for Claude Code.

Scans CLAUDE.md and .claude/rules/*.md for file path references,
checks which ones still exist, and reports drift.

Philosophy: structurally prevent drift like Rust's type system prevents
memory errors - validate references at session start, not after failure.

Runs on SessionStart hook. Fast (should complete in <500ms).

Customization (env vars):
    CLAUDE_WORKSPACE_ROOTS - colon-sep (Unix) or semicolon-sep (Windows)
        list of EXTRA roots to search for unresolved relative paths.
        Useful when your monorepo lives outside ~/Desktop.
        Example (bash): export CLAUDE_WORKSPACE_ROOTS=~/code:/d/projects

Exit codes:
    0 = clean, or drift in advisory mode
    1 = drift when --strict is supplied

Output: writes report to ~/.claude/drift-report.md (always - even when clean,
        so stale reports from prior dirty runs don't mislead readers),
        prints summary to stdout for hook to show in session context.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Patterns that look like REAL file path references in markdown.
# We only check paths that are structurally unambiguous:
#   - Windows absolute:  C:\Users\...  or  C:/Users/...
#   - Unix absolute:     /home/..., /etc/...
#   - Home-relative:     ~/.claude/...
#   - Explicit relative: ./foo, ../foo
#   - Multi-segment:     foo/bar/baz.ext  (has at least one slash)
#
# We DO NOT check bare filenames (e.g. `README.md`, `foo.py`) because
# they are almost always used as concepts/examples, not as verifiable refs.
PATH_PATTERN = re.compile(
    r"`("
    r"[A-Za-z]:[\\/][^\s`]+?"          # C:\... or C:/...
    r"|~[/\\][^\s`]+?"                  # ~/...
    r"|/[A-Za-z][^\s`]*?/[^\s`]+?"      # /usr/bin/... (avoid lone /)
    r"|\.{1,2}[/\\][^\s`]+?"            # ./foo, ../foo
    r"|[\w\-]+[/\\][\w\-/\\\.]+?"       # foo/bar/baz.ext (must have /)
    r")`"
)

# Skip these even if they match the pattern (known placeholders/examples).
# Substring match - if the path *contains* any of these, skip.
SKIP_PATTERNS = [
    "path/to/",
    "foo/",
    "bar/",
    "example.",
    "your-",
    "my-",
    "<",   # <placeholder>
    "$",   # $VAR
    "{",   # {template}
    "ds_",  # ds_id in SQL examples
    "0N",   # placeholder like 0N-name.md
    "...",  # placeholder like foo/.../bar
    "{{",   # template variable
    "*",   # glob pattern (e.g. id_*, block_*.py, ~/.secrets/*, /proc/*/environ)
    "/api/",   # URL endpoints (e.g. /api/v1/projects/7/tasks)
    "docker/login-action",  # GitHub Actions ref, not a file path
    "github.com/",
    "gitlab.com/",
    "huggingface.co/",
    "ghcr.io/",
    "docker.io/",
    "AnastasiyaW/",  # GitHub owner/repo shorthand, not a local path
    "walkinglabs/",  # GitHub owner/repo shorthand, not a local path
    "./script.sh",  # generic script placeholder
    "./init.sh",  # generic project bootstrap convention
    "./init-full.sh",  # generic project bootstrap convention
    "./drop.sh",  # destructive script example in hook docs
    "cat/less/",    # tool list (cat/less/head/tail/grep/bat/xxd)
    "ssh/scp/rsync",  # tool list
    "Edit/Write",  # Claude tool list
    "AKIA/ASIA",  # credential prefix family, not a path
    "YYYY-",        # date placeholder in template paths
    "docs/_graph",  # project-local generated directory convention
    "docs/layers/",  # project-local convention, not this config repo
    "docs/layers.md",  # historical project artifact reference
    "mailbox/all/",  # mailbox convention, may not exist until enabled
    "mailbox/all",  # mailbox convention, may not exist until enabled
    "~/.claude-restructure-backup-",  # historical backup path
    "~/.claude/launch.json",  # optional launcher path, may not exist
    "~/.claude/logs/decisions.jsonl",  # optional append-only runtime decision log
]

# Linux/macOS-only system paths - skip on Windows (validator can't resolve them
# locally but rule files reference them as concepts for SSH/system config docs).
LINUX_SYSTEM_PREFIXES = ("/etc/", "/proc/", "/opt/", "/var/", "/usr/", "/dev/", "/root/")

# Cross-machine references - paths that live on a *different host* than this
# Claude session (Hyper-V VMs, remote build hosts, container mount points).
#
# Default: empty. Extend in your fork if rule files mention paths on remote
# hosts. Example:
#   CROSS_MACHINE_PREFIXES = ("C:\\BuildVM\\", "/mnt/buildbot/")
CROSS_MACHINE_PREFIXES: tuple[str, ...] = ()

# A ``.skip-*`` file is an opt-out switch that may deliberately not exist until
# a user creates it. It is a capability reference, not a stale documentation link.
OPTIONAL_RUNTIME_FILE_RE = re.compile(r"^~[\\/]\.claude[\\/]\.skip-[^\\/`]+$")


def extract_paths(content: str) -> set[str]:
    """Extract file path references from markdown text.

    Filters out:
      - SKIP_PATTERNS substrings (placeholders, glob `*`, URL paths)
      - LINUX_SYSTEM_PREFIXES on Windows (we can't resolve /etc/, /proc/ here)
      - CROSS_MACHINE_PREFIXES (remote-only refs, opt-in via fork)
    """
    is_windows = sys.platform == "win32"
    matches = PATH_PATTERN.findall(content)
    paths = set()
    for match in matches:
        path = match[0] if isinstance(match, tuple) else match
        if any(skip in path for skip in SKIP_PATTERNS):
            continue
        if is_windows and path.startswith(LINUX_SYSTEM_PREFIXES):
            continue
        if CROSS_MACHINE_PREFIXES and path.startswith(CROSS_MACHINE_PREFIXES):
            continue
        if OPTIONAL_RUNTIME_FILE_RE.match(path):
            continue
        paths.add(path)
    return paths


def _build_workspace_roots() -> list[Path]:
    """Compose ordered list of candidate roots for contextual lookup.

    Order:
      1. CLAUDE_WORKSPACE_ROOTS env var entries (user-specified primary
         monorepo paths - most likely to hit, checked first).
      2. ~/Desktop, ~ (legacy fallbacks for refs without explicit prefix).
      3. ~/.claude/projects/*/  (Claude Code memory dirs - for `memory/<file>`
         refs that target the session-scoped memory store).

    Perf: claude_projects iteration is filtered to dirs with a `memory/`
    subdir (skips empty project records that wouldn't match anyway).
    """
    roots: list[Path] = []

    # 1. User-specified roots via env var (colon-sep on Unix, semicolon on Win)
    env_roots = os.environ.get("CLAUDE_WORKSPACE_ROOTS", "")
    if env_roots:
        sep = ";" if sys.platform == "win32" else ":"
        for entry in env_roots.split(sep):
            entry = entry.strip()
            if entry:
                roots.append(Path(entry).expanduser())

    # 2. Generic fallbacks
    roots.append(Path.cwd())
    roots.append(Path.home() / ".claude")
    roots.append(Path.home() / ".claude" / "claude-code-config")
    roots.append(Path.home() / ".claude" / "skills" / "agents-best-practices")
    roots.append(Path.home() / ".claude" / "templates" / "kb-skeleton")
    roots.append(Path.home() / "Desktop" / "Claude_code")
    roots.append(Path.home() / "Desktop")
    roots.append(Path.home())

    # 3. Claude Code project memory dirs (filtered by has-memory-subdir)
    claude_projects = Path.home() / ".claude" / "projects"
    if claude_projects.exists():
        for proj in claude_projects.iterdir():
            if proj.is_dir() and (proj / "memory").is_dir():
                roots.append(proj)

    return roots


def check_path(path_str: str, base: Path) -> tuple[bool, str]:
    """Check if a path exists. Returns (exists, resolved_path_str).

    Tries (in order): expand ~, absolute, relative to base, relative to cwd,
    then contextual lookup under workspace roots (see _build_workspace_roots).
    """
    # Expand home directory (~/foo)
    if path_str.startswith("~"):
        expanded = Path(path_str).expanduser()
        return expanded.exists(), str(expanded)

    p = Path(path_str)

    if p.is_absolute():
        return p.exists(), str(p)

    # Relative to base (the file containing the reference)
    rel_to_base = base / path_str
    if rel_to_base.exists():
        return True, str(rel_to_base)

    # Relative to cwd
    if Path(path_str).exists():
        return True, path_str

    # Contextual lookup under workspace roots
    for root in _build_workspace_roots():
        if not root.exists():
            continue
        candidate = root / path_str
        if candidate.exists():
            return True, str(candidate)

    return False, path_str


def validate_file(md_file: Path) -> list[str]:
    """Validate all path references in a markdown file. Returns list of drift issues."""
    if not md_file.exists():
        return [f"MISSING FILE: {md_file}"]

    content = md_file.read_text(encoding="utf-8", errors="replace")
    paths = extract_paths(content)
    issues = []

    for path_ref in paths:
        exists, _ = check_path(path_ref, md_file.parent)
        if not exists:
            issues.append(f"{md_file.name}: broken ref -> {path_ref}")

    return issues


COMPLETION_AUTOMATION_MARKERS = (
    "100% completion",
    "terminal receipt",
    "terminal marker",
    "до механически подтверждённого завершения",
    "довести ровно один",
)
LONG_RUNNING_AUTOMATION_MARKERS = (
    "watchdog",
    "heartbeat",
    " pid",
    "process",
    "процесс",
    "launcher log",
)
RECOVERY_IDENTITY_MARKERS = (
    "idempot",
    "append-resume",
    "auto_resume",
    "retryable",
    "идемпотент",
)
RECOVERY_BUDGET_MARKERS = (
    "attempt",
    "retry budget",
    "попыт",
    "бюджет",
)
OBSERVE_ONLY_MARKERS = (
    "user explicitly requested observation-only",
    "пользователь явно попросил только наблюдение",
    "mode=observe-only",
)
FAILED_MARKER_EXTERNAL_RE = re.compile(
    r"(?:explicit\s+|current\s+root\s+|root\s+)?"
    r"(?:\.?failed\s+marker|failed\s+receipt|маркер\s+(?:\.?failed|ошибк\w*))"
    r".{0,240}(?:blocked_external|terminal\s+blocker|терминальн\w*\s+блокер)",
    re.DOTALL,
)


def validate_completion_automations(automations_root: Path) -> list[str]:
    """Reject active completion jobs that are only passive status monitors.

    This deliberately checks a narrow, high-signal contract. It does not try to
    understand every automation prompt; it catches the proven failure mode where
    a long-running completion request has neither durable recovery identity nor
    an attempt budget.
    """
    if not automations_root.exists():
        return []

    issues: list[str] = []
    for automation_file in automations_root.glob("*/automation.toml"):
        content = automation_file.read_text(encoding="utf-8", errors="replace").lower()
        if 'status = "active"' not in content:
            continue
        completion_owned = any(marker in content for marker in COMPLETION_AUTOMATION_MARKERS)
        long_running = any(marker in content for marker in LONG_RUNNING_AUTOMATION_MARKERS)
        observe_only = any(marker in content for marker in OBSERVE_ONLY_MARKERS)
        has_recovery_identity = any(marker in content for marker in RECOVERY_IDENTITY_MARKERS)
        has_recovery_budget = any(marker in content for marker in RECOVERY_BUDGET_MARKERS)
        failed_marker_claims_external = bool(FAILED_MARKER_EXTERNAL_RE.search(content))
        if completion_owned and long_running and not observe_only and not (
            has_recovery_identity and has_recovery_budget
        ):
            issues.append(
                f"{automation_file}: completion supervisor lacks durable "
                "idempotency/recovery identity plus attempt limit"
            )
        if completion_owned and long_running and not observe_only and failed_marker_claims_external:
            issues.append(
                f"{automation_file}: failed marker/receipt is treated as "
                "BLOCKED_EXTERNAL without causal classification"
            )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return exit code 1 when documented paths drift; use in CI and release checks",
    )
    args = parser.parse_args(argv)

    # Force UTF-8 output on Windows - broken refs may contain Cyrillic /
    # non-ASCII path components, default cp1252 stdout crashes on print.
    if (
        sys.platform == "win32"
        and sys.stdout.encoding
        and sys.stdout.encoding.lower() != "utf-8"
    ):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass  # Older Python or non-tty stdout - best effort

    claude_dir = Path.home() / ".claude"
    cwd = Path.cwd()

    # Files to validate
    targets = []

    # Global config
    global_claude_md = claude_dir / "CLAUDE.md"
    if global_claude_md.exists():
        targets.append(global_claude_md)

    # Global rules
    global_rules = claude_dir / "rules"
    if global_rules.exists():
        targets.extend(global_rules.glob("*.md"))

    # Project config
    project_claude_md = cwd / "CLAUDE.md"
    if project_claude_md.exists():
        targets.append(project_claude_md)

    project_rules = cwd / ".claude" / "rules"
    if project_rules.exists():
        targets.extend(project_rules.glob("*.md"))

    # Validate
    all_issues = []
    for target in targets:
        issues = validate_file(target)
        all_issues.extend(issues)
    all_issues.extend(
        validate_completion_automations(Path.home() / ".codex" / "automations")
    )

    # Report - always write report (even on clean run) so file-based readers
    # (incl. verifier agents) consistently see current state. Without this, a
    # stale drifted report from a prior session persists and misleads anyone
    # who reads the file directly.
    report_path = claude_dir / "drift-report.md"
    if not all_issues:
        print(f"[config-validator] OK: {len(targets)} files, no drift detected")
        report_path.write_text(
            "# Config Drift Report\n\n"
            f"Last run: clean - scanned {len(targets)} files, "
            "no broken references.\n",
            encoding="utf-8",
        )
        return 0

    print(f"[config-validator] DRIFT DETECTED: {len(all_issues)} broken references")
    print(f"[config-validator] Files scanned: {len(targets)}")
    for issue in all_issues[:10]:
        print(f"  - {issue}")
    if len(all_issues) > 10:
        print(f"  ... and {len(all_issues) - 10} more")

    report_path.write_text(
        "# Config Drift Report\n\n"
        f"Scanned {len(targets)} files, found {len(all_issues)} broken references.\n\n"
        + "\n".join(f"- {i}" for i in all_issues)
        + "\n",
        encoding="utf-8",
    )
    print(f"[config-validator] Full report: {report_path}")

    # SessionStart stays advisory by default. CI and explicit verification use
    # --strict, so documentation drift cannot silently pass a release gate.
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
