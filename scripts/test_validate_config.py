#!/usr/bin/env python3
"""Focused tests for strict documentation-drift validation."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("validate_config.py")
SPEC = importlib.util.spec_from_file_location("validate_config", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValidateConfigTests(unittest.TestCase):
    def test_runtime_opt_out_file_is_not_treated_as_broken_link(self) -> None:
        self.assertEqual(MODULE.extract_paths("Use `~/.claude/.skip-feedback-capture`."), set())

    def test_strict_mode_fails_but_advisory_mode_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            claude_dir = home / ".claude"
            claude_dir.mkdir(parents=True)
            (claude_dir / "CLAUDE.md").write_text("See `./missing/reference.md`.\n", encoding="utf-8")
            project = Path(tmp) / "project"
            project.mkdir()
            with patch.object(MODULE.Path, "home", return_value=home), patch.object(MODULE.Path, "cwd", return_value=project):
                self.assertEqual(MODULE.main([]), 0)
                self.assertEqual(MODULE.main(["--strict"]), 1)

    def write_automation(self, root: Path, prompt: str) -> Path:
        target = root / "job" / "automation.toml"
        target.parent.mkdir(parents=True)
        target.write_text(
            'version = 1\nstatus = "ACTIVE"\nkind = "heartbeat"\n'
            f'prompt = "{prompt}"\n',
            encoding="utf-8",
        )
        return target

    def test_completion_watchdog_without_recovery_contract_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_automation(
                root,
                "watchdog PID until terminal marker and 100% completion; "
                "if PID exits, report blocker and stop",
            )
            issues = MODULE.validate_completion_automations(root)
            self.assertEqual(len(issues), 1)
            self.assertIn("lacks durable idempotency", issues[0])

    def test_completion_supervisor_with_bounded_resume_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_automation(
                root,
                "heartbeat PID until terminal marker and 100% completion; "
                "append-resume with idempotency key, attempt counter, and retry budget",
            )
            self.assertEqual(MODULE.validate_completion_automations(root), [])

    def test_failed_marker_cannot_be_declared_external_by_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_automation(
                root,
                "heartbeat PID until terminal marker and 100% completion; "
                "append-resume with idempotency key, attempt counter, and retry budget; "
                "an explicit failed marker is BLOCKED_EXTERNAL/terminal blocker",
            )
            issues = MODULE.validate_completion_automations(root)
            self.assertEqual(len(issues), 1)
            self.assertIn("without causal classification", issues[0])

    def test_failed_marker_with_internal_causal_repair_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_automation(
                root,
                "heartbeat PID until terminal marker and 100% completion; "
                "append-resume with idempotency key, attempt counter, and retry budget; "
                "a failed marker is not automatically external: classify the cause; "
                "a local source or input defect is INTERNAL_FIXABLE and requires a "
                "Git-backed causal repair, successor contract, and verified resume",
            )
            self.assertEqual(MODULE.validate_completion_automations(root), [])

    def test_explicit_user_observation_only_monitor_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_automation(
                root,
                "watchdog PID until terminal marker and 100% completion; "
                "user explicitly requested observation-only",
            )
            self.assertEqual(MODULE.validate_completion_automations(root), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
