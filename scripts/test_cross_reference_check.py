"""Regression tests for cross_reference_check's freshness signal."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).with_name("cross_reference_check.py")
SPEC = importlib.util.spec_from_file_location("cross_reference_check", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class AlternativeFreshnessTests(unittest.TestCase):
    def test_clean_file_uses_git_date_and_dirty_file_uses_worktree_date(self) -> None:
        original_root = MODULE.ROOT
        with tempfile.TemporaryDirectory(prefix="cross-reference-") as raw:
            root = Path(raw)
            path = root / "principles" / "01-example.md"
            path.parent.mkdir()
            path.write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"],
                cwd=root,
                check=True,
            )
            future = 1_893_456_000  # 2030-01-01 UTC; distinct from the commit day.
            os.utime(path, (future, future))
            MODULE.ROOT = root
            self.assertNotEqual(MODULE.principle_revision_date(path), date.fromtimestamp(future))

            path.write_text("changed\n", encoding="utf-8")
            os.utime(path, (future, future))
            self.assertEqual(MODULE.principle_revision_date(path), date.fromtimestamp(future))
        MODULE.ROOT = original_root


if __name__ == "__main__":
    unittest.main(verbosity=2)
