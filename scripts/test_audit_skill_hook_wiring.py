#!/usr/bin/env python3
"""Tests for the skill/hook wiring audit."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from audit_skill_hook_wiring import audit


SKILL = "---\nname: {name}\ndescription: Use when testing {name}. Do not use for unrelated work.\n---\n# Skill\n"


class AuditSkillHookWiringTests(unittest.TestCase):
    def make_fixture(self, *, missing_route: bool = False) -> tuple[tempfile.TemporaryDirectory, dict[str, Path]]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        active = root / "active"
        source = root / "source"
        router = root / "keyword-skill-router.py"
        hook = root / "hook.py"
        hooks_config = root / "hooks.json"
        (active / "observability-monitoring").mkdir(parents=True)
        (source / "lean-code").mkdir(parents=True)
        (active / "observability-monitoring" / "SKILL.md").write_text(
            SKILL.format(name="observability-monitoring"), encoding="utf-8"
        )
        (source / "lean-code" / "SKILL.md").write_text(
            SKILL.format(name="lean-code"), encoding="utf-8"
        )
        route_target = "missing-skill" if missing_route else "observability-monitoring"
        router.write_text(
            f"ROUTES = [{{'skill': '{route_target}'}}]\n", encoding="utf-8"
        )
        hook.write_text("# fixture\n", encoding="utf-8")
        hooks_config.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {"hooks": [{"command": f'python "{router}"'}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        return temp, {
            "active": active,
            "source": source,
            "router": router,
            "hooks": hooks_config,
        }

    def test_clean_fixture_passes(self) -> None:
        temp, paths = self.make_fixture()
        with temp:
            report = audit(
                active_skills_root=paths["active"],
                source_skills_root=paths["source"],
                hooks_config=paths["hooks"],
                router_path=paths["router"],
            )
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["skills"]["active"]["files"], 1)
        self.assertEqual(report["hooks"]["user_prompt_skill_router_count"], 1)

    def test_unavailable_route_is_a_failure(self) -> None:
        temp, paths = self.make_fixture(missing_route=True)
        with temp:
            report = audit(
                active_skills_root=paths["active"],
                source_skills_root=paths["source"],
                hooks_config=paths["hooks"],
                router_path=paths["router"],
            )
        self.assertIn("curated_route_targets_available", report["failures"])
        self.assertEqual(report["router"]["missing_skill_targets"], ["missing-skill"])

    def test_executable_hook_target_is_checked(self) -> None:
        temp, paths = self.make_fixture()
        with temp:
            executable = paths["hooks"].parent / "tool.exe"
            executable.write_bytes(b"fixture")
            data = json.loads(paths["hooks"].read_text(encoding="utf-8"))
            data["hooks"]["Stop"] = [
                {"hooks": [{"command": f'{executable} hook'}]}
            ]
            paths["hooks"].write_text(json.dumps(data), encoding="utf-8")
            report = audit(
                active_skills_root=paths["active"],
                source_skills_root=paths["source"],
                hooks_config=paths["hooks"],
                router_path=paths["router"],
            )
        self.assertTrue(report["checks"]["all_hook_targets_exist"])


if __name__ == "__main__":
    unittest.main()
