#!/usr/bin/env python3
"""Deterministic wiring and safety checks for the adopted Cursor workflows."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "development"
ROUTER = ROOT / "hooks" / "keyword-skill-router.py"


def load_router():
    spec = importlib.util.spec_from_file_location("keyword_skill_router", ROUTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load router: {ROUTER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frontmatter(text: str) -> tuple[str, str]:
    match = re.match(r"\A\ufeff?---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not match:
        raise AssertionError("missing YAML frontmatter")
    body = match.group(1)
    name = re.search(r"^name:\s*([^\n]+)$", body, re.M)
    description = re.search(r"^description:\s*(.+)$", body, re.M)
    if not name or not description:
        raise AssertionError("frontmatter needs name and description")
    return name.group(1).strip(), description.group(1).strip()


def main() -> int:
    adopted = {
        "verify-this",
        "control-cli",
        "control-ui",
        "deslop",
        "thermo-nuclear-code-quality-review",
    }
    required_sections = ("## Gotchas", "## Troubleshooting", "## Source")
    for name in sorted(adopted):
        path = SKILL_ROOT / name / "SKILL.md"
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        fm_name, description = frontmatter(text)
        assert fm_name == name, (path, fm_name)
        assert len(description) >= 40, path
        for section in required_sections:
            assert section in text, (path, section)
        private_path = "Users" + "\\" + "AiD"
        assert private_path not in text and ("C:" + "\\" + "Users") not in text, path

    for name in ("ci-watcher", "thermo-nuclear-code-quality-review"):
        path = ROOT / "agents" / f"{name}.md"
        assert path.is_file(), path
        assert "Source" in path.read_text(encoding="utf-8"), path

    router = load_router()
    cases = {
        "verify this fix with baseline and treatment evidence": "verify-this",
        "проверь UI скриншотом и accessibility snapshot": "control-ui",
        "reproduce the interactive TUI prompt flow": "control-cli",
        "deslop this AI-generated diff": "deslop",
        "thermonuclear code quality review for spaghetti": "thermo-nuclear-code-quality-review",
    }
    for prompt, expected in cases.items():
        names = {row.get("skill") for row in router.detect_keywords(prompt)}
        assert expected in names, (prompt, expected, names)

    print(f"cursor team kit adoption self-test: PASS ({len(adopted)} skills, 2 agents, {len(cases)} routes)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"cursor team kit adoption self-test: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
