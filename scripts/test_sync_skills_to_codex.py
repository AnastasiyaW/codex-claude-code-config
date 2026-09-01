#!/usr/bin/env python3
"""Unit tests for sync_skills_to_codex.py."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync_skills_to_codex.py")
SPEC = importlib.util.spec_from_file_location("sync_skills_to_codex", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SyncSkillsToCodexTests(unittest.TestCase):
    def test_apply_updates_source_files_and_preserves_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            skill = source / "development" / "demo-skill"
            (skill / "references").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n", encoding="utf-8")
            (skill / "references" / "guide.md").write_text("fresh", encoding="utf-8")

            target = base / "active"
            old = target / "demo-skill"
            old.mkdir(parents=True)
            (old / "SKILL.md").write_text("old", encoding="utf-8")
            backups = base / "backups"

            changes, errors = MODULE.sync(source, target, backups, apply=False)
            self.assertEqual(errors, [])
            self.assertIn("demo-skill", changes)

            residual, errors = MODULE.sync(source, target, backups, apply=True)
            self.assertEqual(errors, [])
            self.assertEqual(residual, {})
            self.assertEqual((target / "demo-skill" / "references" / "guide.md").read_text(encoding="utf-8"), "fresh")
            backup_files = list(backups.rglob("SKILL.md"))
            self.assertEqual(len(backup_files), 1)
            self.assertEqual(backup_files[0].read_text(encoding="utf-8"), "old")

    def test_duplicate_names_fail_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            for category in ("a", "b"):
                path = source / category / "same" / "SKILL.md"
                path.parent.mkdir(parents=True)
                path.write_text("x", encoding="utf-8")
            changes, errors = MODULE.sync(source, Path(tmp) / "target", Path(tmp) / "backups", apply=True)
            self.assertEqual(changes, {})
            self.assertEqual(len(errors), 1)

    def test_three_target_check_and_apply_preserves_target_only_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            source_skill = source / "development" / "demo-skill"
            source_skill.mkdir(parents=True)
            (source_skill / "SKILL.md").write_text("fresh", encoding="utf-8")

            codex_target = base / "codex" / "skills"
            claude_target = base / "claude" / "skills"
            agents_target = base / "agents" / "skills"
            backups = {
                codex_target: base / "codex" / "backups",
                claude_target: base / "claude" / "backups",
                agents_target: base / "agents" / "backups",
            }
            for target in backups:
                (target / "demo-skill").mkdir(parents=True)
                (target / "demo-skill" / "SKILL.md").write_text("old", encoding="utf-8")
                (target / "target-only" / "SKILL.md").parent.mkdir(parents=True)
                (target / "target-only" / "SKILL.md").write_text("keep", encoding="utf-8")

            targets = MODULE.deployment_targets(
                codex_target,
                backups[codex_target],
                also_claude=True,
                also_agents=True,
                claude_target=claude_target,
                claude_backup_root=backups[claude_target],
                agents_target=agents_target,
                agents_backup_root=backups[agents_target],
            )
            self.assertEqual(targets, [(target, backups[target]) for target in backups])

            for target, backup_root in targets:
                changes, errors = MODULE.sync(source, target, backup_root, apply=False)
                self.assertEqual(errors, [])
                self.assertIn("demo-skill", changes)

            for target, backup_root in targets:
                residual, errors = MODULE.sync(source, target, backup_root, apply=True)
                self.assertEqual(errors, [])
                self.assertEqual(residual, {})
                self.assertEqual((target / "demo-skill" / "SKILL.md").read_text(encoding="utf-8"), "fresh")
                self.assertEqual((target / "target-only" / "SKILL.md").read_text(encoding="utf-8"), "keep")
                self.assertEqual(len(list(backup_root.rglob("SKILL.md"))), 1)

    def test_runtime_docs_show_explicit_three_target_command(self) -> None:
        repo_root = SCRIPT.parent.parent
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        runtime_wiring = (repo_root / "docs" / "runtime-wiring.md").read_text(encoding="utf-8")

        self.assertIn("sync_skills_to_codex.py --apply --also-claude --also-agents", readme)
        self.assertIn("sync_skills_to_codex.py --check --also-claude --also-agents", runtime_wiring)


if __name__ == "__main__":
    unittest.main(verbosity=2)
