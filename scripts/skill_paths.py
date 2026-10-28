#!/usr/bin/env python3
"""Every path a shipped SKILL.md points at must exist inside the plugin.

A skill installed from the plugin lives in the plugin cache, so a path that works
only on the author's machine silently breaks it for everyone else (teammate report 2026-10-28:
`${CLAUDE_PLUGIN_ROOT}/.claude/skills/...`, `~/.claude/skills/<name>/...`, a missing
`references/` file). Checked forms:

  ${CLAUDE_SKILL_DIR}/<path>     must exist under the skill folder
  ${CLAUDE_PLUGIN_ROOT}/<path>   must exist under the repository root
  ~/.claude/skills/<shipped>/    forbidden: a user-local copy, use ${CLAUDE_SKILL_DIR}
  references/... scripts/...     (relative, in backticks or a Markdown link) must exist under the skill folder

    python scripts/skill_paths.py      # exit 1 and list every broken reference
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATH_CHARS = r"[^\s`\"')\]]+"
SKILL_DIR = re.compile(r"\$\{?CLAUDE_SKILL_DIR\}?[/\\](" + PATH_CHARS + ")")
PLUGIN_ROOT = re.compile(r"\$\{?CLAUDE_PLUGIN_ROOT\}?[/\\](" + PATH_CHARS + ")")
# A file under the folder: a runtime path. `copy this directory to ~/.claude/skills/x/` is install advice.
USER_COPY = re.compile(r"(?:~|\$\{?HOME\}?|%USERPROFILE%)[/\\]\.claude[/\\]skills[/\\]([\w.-]+)[/\\][\w.-]")
USER_ABSOLUTE = re.compile(r"\b[A-Za-z]:[/\\]Users[/\\][\w.-]+|/home/[a-z][\w.-]*/|/Users/[A-Za-z][\w.-]*/")
RELATIVE = re.compile(r"(?:`|\]\()((?:references|scripts|assets|templates)/[^\s`)<>*]+)")
# `python scripts/x.py` with no quotes runs from the user's project, where the skill's script is not.
RUN_RELATIVE = re.compile(r"\bpython3?\s+((?:references|scripts|assets|templates)/[\w./-]+\.py)\b")


def skill_folders(root: Path) -> list[Path]:
    return sorted(p.parent for p in (root / "skills").rglob("SKILL.md"))


def _clean(path: str) -> str:
    return path.rstrip(".,;:").split("#", 1)[0].replace("\\", "/")


def _placeholder(path: str) -> bool:
    return "<" in path or "*" in path


def broken_references(root: Path = REPO_ROOT) -> list[str]:
    folders = skill_folders(root)
    shipped = {folder.name for folder in folders}
    problems = []
    for folder in folders:
        text = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        where = (folder / "SKILL.md").relative_to(root).as_posix()
        for match in SKILL_DIR.finditer(text):
            if not _placeholder(match.group(1)) and not (folder / _clean(match.group(1))).exists():
                problems.append(f"{where}: ${{CLAUDE_SKILL_DIR}}/{match.group(1)} does not exist")
        for match in PLUGIN_ROOT.finditer(text):
            if not _placeholder(match.group(1)) and not (root / _clean(match.group(1))).exists():
                problems.append(f"{where}: ${{CLAUDE_PLUGIN_ROOT}}/{match.group(1)} does not exist in the plugin")
        for match in USER_COPY.finditer(text):
            if match.group(1) in shipped:
                problems.append(f"{where}: {match.group(0)} exists only where a local copy is "
                                "installed; use ${CLAUDE_SKILL_DIR}")
        for match in USER_ABSOLUTE.finditer(text):
            problems.append(f"{where}: {match.group(0)} is one user's home; use ${{CLAUDE_SKILL_DIR}} or ~")
        for match in RELATIVE.finditer(text):
            if not _placeholder(match.group(1)) and not (folder / _clean(match.group(1))).exists():
                problems.append(f"{where}: {match.group(1)} does not exist in the skill folder")
        for match in RUN_RELATIVE.finditer(text):
            # A script the plugin does not ship is the user's own (e.g. copied from kb-skeleton): fine.
            if not ((folder / match.group(1)).exists() or (root / match.group(1)).exists()):
                continue
            problems.append(f"{where}: `{match.group(0)}` runs from the user's project; name the file through "
                            "${CLAUDE_SKILL_DIR} or ${CLAUDE_PLUGIN_ROOT}")
    return list(dict.fromkeys(problems))


def main() -> int:
    problems = broken_references()
    for problem in problems:
        print(problem)
    print(f"{len(problems)} broken skill reference(s)" if problems else "every skill reference resolves inside the plugin")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
