#!/usr/bin/env python3
"""Regression tests for portable skills-lock generation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from generate_skills_lock import hash_skill


class GenerateSkillsLockTests(unittest.TestCase):
    def make_skill(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="skills-lock-test-"))
        skill = root / "skills" / "demo"
        (skill / "references").mkdir(parents=True)
        return skill

    def test_text_newlines_do_not_change_portable_identity(self) -> None:
        skill = self.make_skill()
        (skill / "SKILL.md").write_bytes(b"---\r\ndescription: demo\r\n---\r\nline one\r\n")
        (skill / "references" / "guide.md").write_bytes(b"alpha\r\nbeta\r\n")
        windows = hash_skill(skill)

        (skill / "SKILL.md").write_bytes(b"---\ndescription: demo\n---\nline one\n")
        (skill / "references" / "guide.md").write_bytes(b"alpha\nbeta\n")
        linux = hash_skill(skill)

        self.assertEqual(windows, linux)
        self.assertNotIn("last_modified", windows)

    def test_substantive_text_change_changes_identity(self) -> None:
        skill = self.make_skill()
        entry = skill / "SKILL.md"
        entry.write_text("---\ndescription: demo\n---\nfirst\n", encoding="utf-8")
        before = hash_skill(skill)
        entry.write_text("---\ndescription: demo\n---\nsecond\n", encoding="utf-8")
        after = hash_skill(skill)
        self.assertNotEqual(before["content_hash"], after["content_hash"])

    def test_python_cache_does_not_change_identity(self) -> None:
        skill = self.make_skill()
        entry = skill / "SKILL.md"
        entry.write_text("---\ndescription: demo\n---\nsource\n", encoding="utf-8")
        before = hash_skill(skill)

        cache = skill / "scripts" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "demo.cpython-314.pyc").write_bytes(b"machine-specific cache")
        after = hash_skill(skill)

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
