#!/usr/bin/env python3
"""SessionStart hook: validate file path references in CLAUDE.md and rules/.

Scans CLAUDE.md and .claude/rules/*.md for file path references, checks if
they exist on disk. Reports drift (stale paths) so the agent sees warnings
at the start of every session.

Register in ~/.claude/settings.json:
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "python path/to/session-drift-validator.py",
        "statusMessage": "Checking config drift..."
      }]
    }]
  }
}
"""

import os
import re
import sys
from pathlib import Path


def find_config_files(root: str) -> list[str]:
    """Find CLAUDE.md and .claude/rules/*.md files."""
    files = []
    claude_md = os.path.join(root, "CLAUDE.md")
    if os.path.isfile(claude_md):
        files.append(claude_md)

    rules_dir = os.path.join(root, ".claude", "rules")
    if os.path.isdir(rules_dir):
        for f in os.listdir(rules_dir):
            if f.endswith(".md"):
                files.append(os.path.join(rules_dir, f))

    return files


# Patterns that look like real file paths (not concepts or examples)
PATH_PATTERN = re.compile(
    r'(?:'
    r'[A-Za-z]:[/\\][^\s`"\')>]+'       # Windows absolute: C:/foo or C:\foo
    r'|~/[^\s`"\')>]+'                    # Home-relative: ~/foo
    r'|(?:\./|\.\./)[\w./-]+'             # Relative: ./foo or ../foo
    r'|[\w.-]+(?:/[\w.-]+){2,}'           # Multi-segment: foo/bar/baz
    r')'
)

# Skip patterns (template placeholders, URLs, etc.)
SKIP_PATTERNS = [
    r'\{\{',           # Template: {{path}}
    r'://',            # URLs (also partial matches like s://github.com/...)
    r'example\.com',   # Example domains
    r'<[^>]+>',        # Angle-bracket placeholders
    r'\$\{',           # Variable expansion
]

# Bare multi-segment matches ("foo/bar/baz") are the noisiest alternative:
# prose word-lists ("GPU/port/container"), domains without scheme
# ("code.claude.com/docs/..."). Only treat them as paths when the last
# segment has a file extension and the first segment is not domain-like.
EXT_RE = re.compile(r'\.[A-Za-z0-9]{1,5}$')
DOMAIN_RE = re.compile(r'^[\w-]+(\.[\w-]+)*\.(com|org|net|io|dev|app|ai|ru|club|space|work|md)$', re.I)


def extract_paths(text: str) -> list[str]:
    """Extract file path references from markdown text."""
    paths = []
    for match in PATH_PATTERN.finditer(text):
        path = match.group(0).rstrip('.,;:)')
        if any(re.search(skip, path) for skip in SKIP_PATTERNS):
            continue
        # Cyrillic/other non-ASCII "paths" are prose word-lists, not files
        # ("\w" matches Unicode, so "код/probe/доки" slips through otherwise)
        if not path.isascii():
            continue
        anchored = path.startswith(('./', '../', '~')) or re.match(r'^[A-Za-z]:[/\\]', path)
        if not anchored:
            first_seg = path.split('/')[0]
            if DOMAIN_RE.match(first_seg):
                continue
            if not EXT_RE.search(path):
                continue
        paths.append(path)
    return paths


def resolve_path(path: str, source_file: str, cwd: str) -> str | None:
    """Try multiple strategies to resolve a path reference."""
    # Expand ~ to home
    expanded = os.path.expanduser(path)

    # Strategy 1: absolute path
    if os.path.isabs(expanded) and os.path.exists(expanded):
        return expanded

    # Strategy 2: relative to the file containing the reference
    source_dir = os.path.dirname(source_file)
    candidate = os.path.join(source_dir, path)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)

    # Strategy 3: relative to cwd
    candidate = os.path.join(cwd, path)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)

    return None


def main():
    cwd = os.getcwd()
    config_files = find_config_files(cwd)

    # Also check global CLAUDE.md
    global_claude = os.path.expanduser("~/.claude/CLAUDE.md")
    if os.path.isfile(global_claude):
        config_files.append(global_claude)

    if not config_files:
        return

    drift_found = []

    def _display_path(config_file: str, cwd: str) -> str:
        """Label a config file relative to cwd, absolute when that is impossible.

        On Windows `os.path.relpath` RAISES when the two sit on different
        drives (project on D:, global config under C:\\Users). That is not a
        rare corner: it is every session whose project lives off the system
        drive. An uncaught raise here kills the hook before it prints a
        single finding — it stays listed in settings.json and silently
        validates nothing.
        """
        try:
            return os.path.relpath(config_file, cwd)
        except ValueError:
            return config_file

    for config_file in config_files:
        try:
            text = Path(config_file).read_text(encoding="utf-8", errors="ignore")
        except (OSError, IOError):
            continue

        paths = extract_paths(text)
        for path in paths:
            if resolve_path(path, config_file, cwd) is None:
                drift_found.append(f"  {_display_path(config_file, cwd)}: {path}")

    if drift_found:
        print("[config-drift] Found stale references:")
        for d in drift_found[:20]:  # Cap output to avoid noise
            print(d)
        if len(drift_found) > 20:
            print(f"  ... and {len(drift_found) - 20} more")
    else:
        print(f"[config-drift] OK: {len(config_files)} files, no drift detected")


if __name__ == "__main__":
    main()
