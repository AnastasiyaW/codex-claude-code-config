#!/usr/bin/env python3
"""Tests for skill_paths.py: every path a shipped skill references resolves inside the plugin."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("skill_paths", Path(__file__).with_name("skill_paths.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_skill(root: Path, body: str, files: tuple[str, ...] = ()) -> None:
    folder = root / "skills" / "cat" / "demo"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(body, encoding="utf-8")
    for rel in files:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text("x", encoding="utf-8")


class SkillPathsTests(unittest.TestCase):
    def test_repository_skills_resolve(self) -> None:
        self.assertEqual(MODULE.broken_references(), [])

    def test_each_broken_form_is_reported(self) -> None:
        cases = {
            "python ${CLAUDE_PLUGIN_ROOT}/.claude/skills/demo/scripts/run.py": "does not exist in the plugin",
            "python ~/.claude/skills/demo/scripts/run.py": "local copy",
            "See `references/missing.md`.": "does not exist in the skill folder",
            "Run ${CLAUDE_SKILL_DIR}/scripts/absent.py": "does not exist",
            "Run $CLAUDE_SKILL_DIR/scripts/absent.py": "does not exist",
            "python $HOME/.claude/skills/demo/scripts/run.py": "local copy",
            r"python %USERPROFILE%\.claude\skills\demo\scripts\run.py": "local copy",
            # Built at run time: the public leak scan reads a literal user-home fixture as a real path.
            "Open " + "C:/" + "Users/" + "example/notes.md": "one user's home",
        }
        for body, needle in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                make_skill(Path(tmp), body)
                problems = MODULE.broken_references(Path(tmp))
                self.assertEqual(len(problems), 1, body)
                self.assertIn(needle, problems[0], body)

    def test_shipped_script_run_from_project_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            make_skill(Path(tmp), "Run:\n\n    python scripts/tool.py --x\n", ("scripts/tool.py",))
            problems = MODULE.broken_references(Path(tmp))
            self.assertEqual(len(problems), 1)
            self.assertIn("runs from the user's project", problems[0])

    def test_project_script_and_placeholders_pass(self) -> None:
        body = ("From the project root run python scripts/build_graph.py.\n"
                "Use ${CLAUDE_SKILL_DIR}/scripts/<name>.py and ${CLAUDE_PLUGIN_ROOT}/templates/*/x.\n")
        with tempfile.TemporaryDirectory() as tmp:
            make_skill(Path(tmp), body)
            self.assertEqual(MODULE.broken_references(Path(tmp)), [])

    def test_valid_forms_pass(self) -> None:
        body = ("python \"${CLAUDE_SKILL_DIR}/scripts/run.py\" x\nSee [ref](references/a.md).\n"
                "Install: copy this directory to `~/.claude/skills/demo/`.\n")
        with tempfile.TemporaryDirectory() as tmp:
            make_skill(Path(tmp), body, ("scripts/run.py", "references/a.md"))
            self.assertEqual(MODULE.broken_references(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
