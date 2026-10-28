#!/usr/bin/env python3
"""Every path a shipped SKILL.md points at must exist inside the plugin.

A skill installed from the plugin lives in the plugin cache, so a path that works
only on the author's machine silently breaks it for everyone else (Vikunja #1251:
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
SKILL_DIR = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/([^\s`\"')\]]+)")
PLUGIN_ROOT = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s`\"')\]]+)")
# A file under the folder: a runtime path. `copy this directory to ~/.claude/skills/x/` is install advice.
USER_COPY = re.compile(r"~/\.claude/skills/([\w.-]+)/[\w.-]")
RELATIVE = re.compile(r"(?:`|\]\()((?:references|scripts|assets|templates)/[^\s`)<>*]+)")


def skill_folders(root: Path) -> list[Path]:
    return sorted(p.parent for p in (root / "skills").rglob("SKILL.md"))


def _clean(path: str) -> str:
    return path.rstrip(".,;:").split("#", 1)[0]


def broken_references(root: Path = REPO_ROOT) -> list[str]:
    folders = skill_folders(root)
    shipped = {folder.name for folder in folders}
    problems = []
    for folder in folders:
        text = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        where = (folder / "SKILL.md").relative_to(root).as_posix()
        for match in SKILL_DIR.finditer(text):
            if not (folder / _clean(match.group(1))).exists():
                problems.append(f"{where}: ${{CLAUDE_SKILL_DIR}}/{match.group(1)} does not exist")
        for match in PLUGIN_ROOT.finditer(text):
            if not (root / _clean(match.group(1))).exists():
                problems.append(f"{where}: ${{CLAUDE_PLUGIN_ROOT}}/{match.group(1)} does not exist in the plugin")
        for match in USER_COPY.finditer(text):
            if match.group(1) in shipped:
                problems.append(f"{where}: ~/.claude/skills/{match.group(1)}/ exists only where a local copy is "
                                "installed; use ${CLAUDE_SKILL_DIR}")
        for match in RELATIVE.finditer(text):
            if not (folder / _clean(match.group(1))).exists():
                problems.append(f"{where}: {match.group(1)} does not exist in the skill folder")
    return problems


def main() -> int:
    problems = broken_references()
    for problem in problems:
        print(problem)
    print(f"{len(problems)} broken skill reference(s)" if problems else "every skill reference resolves inside the plugin")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
