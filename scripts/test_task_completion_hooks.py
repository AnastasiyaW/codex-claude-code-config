#!/usr/bin/env python3
"""Tests for task-completion hook discipline.

These tests make the hook expectations executable:
- Stop hooks must include the guards that prevent unfinished work from being
  silently closed.
- PreCompact must preserve handoff state.
- The stop-phrase guard must block defer/ask endings.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOKS_JSON = Path.home() / ".codex" / "hooks.json"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
SOURCE_HOOKS = Path(__file__).resolve().parent.parent / "hooks"
STOP_GUARD = SOURCE_HOOKS / "stop-phrase-guard.py"
OUTWARD_CLAIM_GUARD = SOURCE_HOOKS / "outward-claim-evidence-guard.py"
PLUGIN_CACHE = Path.home() / ".codex" / "plugins" / "cache"

REQUIRED_STOP_HOOKS = (
    "stop-phrase-guard.py",
    "outward-claim-evidence-guard.py",
    "test-gate-stop-hook.py",
    "harness-load-advisor.py",
    "problems-md-validator.py",
    "feature-list-validator.py",
    "session-handoff-reminder.py",
    "kb-validate-gate.py",
    "git-source-gate.py",
    "transfer-contract-guard.py",
)

REQUIRED_PRECOMPACT_HOOKS = (
    "precompact-handoff-guard.py",
)

REQUIRED_SESSIONSTART_HOOKS = (
    "session-handoff-check.py",
    "review_handoff_memory_loop.py",
    "docs-staleness-guard.py",
    "continuity-session-check.py",
)

REQUIRED_PRETOOLUSE_HOOKS = (
    "handoff-closure-audit-guard.py",
    "github-workflow-security.py",
    "continuity-contract-guard.py",
)

REQUIRED_POSTTOOLUSE_HOOKS = (
    "over-engineering-advisor.py",
    "module-shape-advisor.py",
)


def hook_commands_from(config_path: Path, event_name: str) -> list[str]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    commands: list[str] = []
    for group in config["hooks"].get(event_name, []):
        for hook in group.get("hooks", []):
            command = hook.get("command")
            if isinstance(command, str):
                commands.append(command)
    return commands


def hook_commands(event_name: str) -> list[str]:
    return hook_commands_from(HOOKS_JSON, event_name)


def all_hook_commands_from(config_path: Path) -> list[str]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    commands: list[str] = []
    for groups in config["hooks"].values():
        for group in groups:
            for hook in group.get("hooks", []):
                command = hook.get("command")
                if isinstance(command, str):
                    commands.append(command)
    return commands


def all_hook_commands() -> list[str]:
    return all_hook_commands_from(HOOKS_JSON)


class TaskCompletionHookTests(unittest.TestCase):
    def test_codex_hook_config_uses_the_supported_wrapper_only(self) -> None:
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(set(config), {"hooks"})
        self.assertIsInstance(config["hooks"], dict)

    def test_plugin_hook_configs_have_supported_top_level_schema(self) -> None:
        if not PLUGIN_CACHE.exists():
            self.skipTest("plugin cache is absent")
        offenders: list[str] = []
        for path in PLUGIN_CACHE.rglob("hooks.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            extra = sorted(set(data) - {"hooks"})
            if extra:
                offenders.append(f"{path}: unsupported top-level keys {extra}")
            if "hooks" not in data:
                offenders.append(f"{path}: missing top-level hooks")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_hook_command_targets_exist(self) -> None:
        missing: list[str] = []
        for config_path in (HOOKS_JSON, CLAUDE_SETTINGS):
            for command in all_hook_commands_from(config_path):
                for raw_path in re.findall(r"[\"']([A-Za-z]:[\\/][^\"']+?\.py)[\"']", command):
                    path = Path(raw_path)
                    if not path.exists():
                        missing.append(f"{config_path}: {path} <- {command}")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_stop_hooks_include_completion_guards(self) -> None:
        commands = "\n".join(hook_commands("Stop"))
        for required in REQUIRED_STOP_HOOKS:
            self.assertIn(required, commands)

    def test_precompact_hooks_include_handoff_guard(self) -> None:
        commands = "\n".join(hook_commands("PreCompact"))
        for required in REQUIRED_PRECOMPACT_HOOKS:
            self.assertIn(required, commands)

    def test_sessionstart_hooks_include_handoff_memory_review(self) -> None:
        commands = "\n".join(hook_commands("SessionStart"))
        for required in REQUIRED_SESSIONSTART_HOOKS:
            self.assertIn(required, commands)

    def test_handoff_reports_use_runtime_directory(self) -> None:
        for config_path in (HOOKS_JSON, CLAUDE_SETTINGS):
            commands = [
                command
                for command in hook_commands_from(config_path, "SessionStart")
                if "review_handoff_memory_loop.py" in command
            ]
            self.assertEqual(len(commands), 1, f"{config_path}: expected one handoff-memory reviewer")
            self.assertIn("--report-dir", commands[0], f"{config_path}: report writes must stay outside project roots")

    def test_pretooluse_hooks_guard_handoff_writes(self) -> None:
        commands = "\n".join(hook_commands("PreToolUse"))
        for required in REQUIRED_PRETOOLUSE_HOOKS:
            self.assertIn(required, commands)

    def test_posttooluse_hooks_guard_code_shape(self) -> None:
        for config_path in (HOOKS_JSON, CLAUDE_SETTINGS):
            commands = "\n".join(hook_commands_from(config_path, "PostToolUse"))
            for required in REQUIRED_POSTTOOLUSE_HOOKS:
                self.assertIn(required, commands, f"{config_path}: {required}")

    def test_secrets_as_data_does_not_wire_secret_leak_guard(self) -> None:
        for config_path in (HOOKS_JSON, CLAUDE_SETTINGS):
            commands = "\n".join(all_hook_commands_from(config_path))
            self.assertNotIn("secret-leak-guard.py", commands, f"{config_path}: forbidden hook wiring")

    def test_claude_runtime_has_the_same_core_lifecycle_guards(self) -> None:
        self.assertTrue(CLAUDE_SETTINGS.exists(), f"missing live Claude settings: {CLAUDE_SETTINGS}")
        required_by_event = {
            "Stop": REQUIRED_STOP_HOOKS,
            "PreCompact": REQUIRED_PRECOMPACT_HOOKS,
            "SessionStart": REQUIRED_SESSIONSTART_HOOKS,
            "PreToolUse": REQUIRED_PRETOOLUSE_HOOKS,
            "PostToolUse": REQUIRED_POSTTOOLUSE_HOOKS,
        }
        for event_name, required_hooks in required_by_event.items():
            commands = "\n".join(hook_commands_from(CLAUDE_SETTINGS, event_name))
            for required in required_hooks:
                self.assertIn(required, commands, f"{event_name}: {required}")

    def test_stop_phrase_guard_blocks_defer_ending(self) -> None:
        with tempfile.TemporaryDirectory(prefix="task-completion-hook-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".claude").mkdir()
            transcript = tmp_path / "transcript.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Осталось доделать проверку; хочешь, сделаю следующим шагом.",
                        }
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            event = json.dumps({"transcript_path": str(transcript)}, ensure_ascii=False)
            result = subprocess.run(
                [sys.executable, str(STOP_GUARD)],
                input=event,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload.get("decision"), "block")
            self.assertIn("actually finish the work", payload.get("reason", ""))

    def test_outward_claim_guard_requires_measurement_for_hash_equality(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-evidence-hook-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".claude").mkdir()
            transcript = tmp_path / "transcript.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "message": {
                            "role": "assistant",
                            "content": "The filename is the SHA-256 of the emitted bytes.",
                        }
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            event = json.dumps({"transcript_path": str(transcript)}, ensure_ascii=False)
            result = subprocess.run(
                [sys.executable, str(OUTWARD_CLAIM_GUARD)],
                input=event,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload.get("decision"), "block")
            self.assertIn("measurement", payload.get("reason", ""))

    def test_outward_claim_guard_allows_measured_hash_and_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-evidence-hook-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".claude").mkdir()
            digest = "b" * 64
            for content in (
                f"Claim: SHA-256 equals {digest}.\nEvidence: Get-FileHash payload.bin -> {digest}\nScope: payload.bin now.",
                f"HYPOTHESIS: code appears to name an output after SHA-256 {digest}; not measured.",
            ):
                transcript = tmp_path / "transcript.jsonl"
                transcript.write_text(
                    json.dumps({"message": {"role": "assistant", "content": content}}, ensure_ascii=False)
                    + "\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [sys.executable, str(OUTWARD_CLAIM_GUARD)],
                    input=json.dumps({"transcript_path": str(transcript)}, ensure_ascii=False),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=tmp,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), "", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
