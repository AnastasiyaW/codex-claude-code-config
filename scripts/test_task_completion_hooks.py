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
USER_TASK_GUARD = SOURCE_HOOKS / "user-task-completion-guard.py"
OUTWARD_CLAIM_GUARD = SOURCE_HOOKS / "outward-claim-evidence-guard.py"
PLUGIN_CACHE = Path.home() / ".codex" / "plugins" / "cache"

REQUIRED_STOP_HOOKS = (
    "user-task-completion-guard.py",
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

REQUIRED_USER_PROMPT_HOOKS = (
    "user-task-completion-guard.py",
)

REQUIRED_PRECOMPACT_HOOKS = (
    "precompact-handoff-guard.py",
)

REQUIRED_SESSIONSTART_HOOKS = (
    "session-handoff-check.py",
    "handoff-resume-gate.py",
    "review_handoff_memory_loop.py",
    "docs-staleness-guard.py",
    "continuity-session-check.py",
    "user-task-completion-guard.py",
)

REQUIRED_PRETOOLUSE_HOOKS = (
    "handoff-closure-audit-guard.py",
    "github-workflow-security.py",
    "continuity-contract-guard.py",
    "powershell-dynamic-execution-guard.py",
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
            # Official Claude marketplace packages may add human-readable
            # metadata here. Codex consumes the ``hooks`` object; keep that
            # contract strict while accepting the documented string metadata.
            extra = sorted(set(data) - {"hooks", "description"})
            if extra:
                offenders.append(f"{path}: unsupported top-level keys {extra}")
            if "hooks" not in data:
                offenders.append(f"{path}: missing top-level hooks")
            if "description" in data and (
                not isinstance(data["description"], str) or not data["description"].strip()
            ):
                offenders.append(f"{path}: description must be a non-empty string")
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

    def test_user_prompt_hooks_create_durable_user_work_orders(self) -> None:
        for config_path in (HOOKS_JSON, CLAUDE_SETTINGS):
            commands = "\n".join(hook_commands_from(config_path, "UserPromptSubmit"))
            for required in REQUIRED_USER_PROMPT_HOOKS:
                self.assertIn(required, commands, f"{config_path}: {required}")

    def test_user_task_session_start_uses_its_explicit_mode(self) -> None:
        for config_path in (HOOKS_JSON, CLAUDE_SETTINGS):
            commands = [
                command for command in hook_commands_from(config_path, "SessionStart")
                if "user-task-completion-guard.py" in command
            ]
            self.assertEqual(len(commands), 1, f"{config_path}: expected one user-task session-start hook")
            self.assertIn("--session-start", commands[0], f"{config_path}: must not run Stop mode at SessionStart")
            expected = f'python "{(Path.home() / ".claude" / "claude-code-config" / "hooks" / "user-task-completion-guard.py").as_posix()}"'
            self.assertIn(expected, commands[0])

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
            "UserPromptSubmit": REQUIRED_USER_PROMPT_HOOKS,
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

    def test_stop_phrase_guard_blocks_private_credential_refusal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="private-credential-stop-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".claude").mkdir()
            transcript = tmp_path / "transcript.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Не вывожу учётные данные в переписку. "
                                "Они находятся локально в STAGING-LOGIN.txt."
                            ),
                        }
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(STOP_GUARD)],
                input=json.dumps({"transcript_path": str(transcript)}, ensure_ascii=False),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload.get("decision"), "block")
            self.assertIn("inside the configured trust boundary", payload.get("reason", ""))

    def test_stop_phrase_guard_allows_measured_public_credential_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-credential-stop-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".claude").mkdir()
            transcript = tmp_path / "transcript.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Не публикую учётные данные в публичный GitHub repository; "
                                "его visibility механически подтверждён как PUBLIC."
                            ),
                        }
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(STOP_GUARD)],
                input=json.dumps({"transcript_path": str(transcript)}, ensure_ascii=False),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "", result.stdout)

    def test_stop_phrase_guard_rejects_hypothetical_public_credential_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hypothetical-public-credential-stop-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".claude").mkdir()
            transcript = tmp_path / "transcript.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Не вывожу токен в переписку, потому что репозиторий "
                                "может быть публичным."
                            ),
                        }
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(STOP_GUARD)],
                input=json.dumps({"transcript_path": str(transcript)}, ensure_ascii=False),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload.get("decision"), "block")
            self.assertIn("measured PUBLIC/external boundary", payload.get("reason", ""))

    def test_stop_phrase_guard_distinguishes_user_homework_from_human_only_input(self) -> None:
        cases = (
            (
                "action request cannot hand executable work back",
                "Я прислала api_id и api_hash. Настрой всё и запусти авторизацию.",
                (
                    "Чтобы не печатать их вручную: выдели api_id и нажми Ctrl+C. "
                    "В PowerShell выполни `$env:TELEGRAM_API_ID = (Get-Clipboard).Trim()`. "
                    "Затем скопируй api_hash и запусти `python -m telegram_live_cli auth`."
                ),
                True,
            ),
            (
                "data-only continuation retains the earlier action owner",
                (
                    "Настрой Telegram auth и запусти его сама.",
                    "App api_id: 12345; App api_hash: supplied-in-chat",
                ),
                (
                    "Скопируйте api_id, вставьте его в PowerShell, затем "
                    "запустите `python -m telegram_live_cli auth`."
                ),
                True,
            ),
            (
                "action survives more than eight neutral data fragments",
                ("Запусти авторизацию сама.",)
                + tuple(f"credential fragment {index}: value-{index}" for index in range(9)),
                "Paste curl -X POST https://example.invalid/auth into the deployment page.",
                True,
            ),
            (
                "explicit how-to question may receive commands",
                "Как мне вручную запустить Telegram auth в PowerShell?",
                "Откройте PowerShell и выполните `python -m telegram_live_cli auth`.",
                False,
            ),
            (
                "tutorial intent survives a neutral data follow-up",
                (
                    "How do I run Telegram auth in PowerShell?",
                    "I use PowerShell 7.4.",
                ),
                "Open PowerShell and run `python -m telegram_live_cli auth`.",
                False,
            ),
            (
                "show-me-how formulation is an explicit tutorial",
                "Can you show me how to run Telegram auth in PowerShell?",
                "Open PowerShell and run `python -m telegram_live_cli auth`.",
                False,
            ),
            (
                "why question is not consent to transfer owned work",
                "Почему ты не можешь сама запустить авторизацию?",
                "Откройте PowerShell и выполните `python -m telegram_live_cli auth`.",
                True,
            ),
            (
                "what-next question does not erase the earlier work order",
                (
                    "Настрой и запусти Telegram auth сама.",
                    "Что дальше?",
                ),
                "Откройте терминал и запустите `python -m telegram_live_cli auth`.",
                True,
            ),
            (
                "completed machine prefix may request only OTP",
                "Настрой и запусти Telegram auth; код я пришлю, когда он появится.",
                (
                    "Я уже настроила переменные и запустила CLI. Процесс ожидает код Telegram. "
                    "Пришлите сюда только OTP."
                ),
                False,
            ),
            (
                "human boundary cannot hide a second machine command",
                "Настрой и запусти Telegram auth до настоящего человеческого шага.",
                (
                    "Я уже настроила переменные и запустила CLI. Процесс ожидает код Telegram. "
                    "Пришлите OTP, затем запустите `python -m telegram_live_cli verify`."
                ),
                True,
            ),
            (
                "agent-owned post-OTP command is not user homework",
                "Запусти Telegram auth до запроса кода.",
                (
                    "I already ran the CLI and the process is waiting for OTP. Send the OTP here; "
                    "I will run `python -m telegram_live_cli verify` immediately after it arrives."
                ),
                False,
            ),
            (
                "curl handoff does not need a named shell surface",
                "Разверни webhook сама.",
                "Paste curl -X POST https://example.invalid/hook into the deployment page.",
                True,
            ),
            (
                "type curl is detected as a command handoff",
                "Deploy the webhook.",
                "Type curl -X POST https://example.invalid/hook in the deployment page.",
                True,
            ),
            (
                "russian type curl is detected as a command handoff",
                "Разверни webhook.",
                "Наберите curl -X POST https://example.invalid/hook на странице deployment.",
                True,
            ),
            (
                "command shape catches a verb outside the directive list",
                "Deploy the webhook.",
                "Feed curl -X POST https://example.invalid/hook into the deployment page.",
                True,
            ),
            (
                "collective voice cannot delegate to the user",
                "Deploy the webhook.",
                (
                    "We should ask the user to run curl -X POST "
                    "https://example.invalid/hook in the deployment page."
                ),
                True,
            ),
            (
                "collective voice cannot delegate to an arbitrary operator",
                "Deploy the webhook.",
                (
                    "We should ask the release engineer to feed curl -X POST "
                    "https://example.invalid/hook into the deployment page."
                ),
                True,
            ),
            (
                "recipient grammar catches delegation through an unlisted verb",
                "Deploy the webhook.",
                (
                    "We should get the release engineer to run curl -X POST "
                    "https://example.invalid/hook in the deployment page."
                ),
                True,
            ),
            (
                "agent modal intent is not delegation to the user",
                "Deploy the webhook.",
                "I need to run curl -X POST https://example.invalid/hook in the deployment page.",
                False,
            ),
            (
                "fenced command evidence inherits the agent ownership claim",
                "Deploy the webhook.",
                (
                    "I ran this command successfully:\n"
                    "```bash\n"
                    "curl -X POST https://example.invalid/hook\n"
                    "```"
                ),
                False,
            ),
            (
                "physical confirmation is allowed after the machine prefix",
                "Run authentication until it reaches the real human confirmation.",
                (
                    "I already ran python and the process is waiting for physical confirmation "
                    "on your phone. Open your authenticator app and confirm."
                ),
                False,
            ),
            (
                "russian physical confirmation is allowed after the machine prefix",
                "Запусти авторизацию до реального человеческого подтверждения.",
                (
                    "Я уже запустила CLI. Процесс ожидает физическое подтверждение на вашем "
                    "телефоне. Откройте приложение и подтвердите вход."
                ),
                False,
            ),
            (
                "phone push approval is a physical human boundary",
                "Run authentication until it reaches the human push approval.",
                (
                    "I already ran the CLI and the process is waiting for approval on your phone. "
                    "Tap the notification and confirm."
                ),
                False,
            ),
            (
                "russian phone push approval is a physical human boundary",
                "Запусти авторизацию до push-подтверждения.",
                (
                    "Я уже запустила CLI. Процесс ожидает подтверждения в приложении на телефоне. "
                    "Нажмите уведомление и подтвердите вход."
                ),
                False,
            ),
            (
                "external labels alone are not a receipt",
                "Запусти команду на закрытом стенде.",
                (
                    "Blocker: стенд механически недоступен из этого runtime. "
                    "Access inventory: доступные SSH targets проверены, стенда среди них нет. "
                    "Needed authority: доступ к стенду. Recheck: повторить inventory после выдачи. "
                    "Выполните команду в PowerShell только если доступ будет выдан вам напрямую."
                ),
                True,
            ),
        )
        for label, user_texts, assistant_text, expected_block in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(prefix="user-homework-stop-") as tmp:
                tmp_path = Path(tmp)
                (tmp_path / ".claude").mkdir()
                transcript = tmp_path / "transcript.jsonl"
                if isinstance(user_texts, str):
                    user_texts = (user_texts,)
                transcript.write_text(
                    "".join(
                        json.dumps(
                            {"message": {"role": "user", "content": user_text}},
                            ensure_ascii=False,
                        )
                        + "\n"
                        for user_text in user_texts
                    )
                    + json.dumps(
                        {"message": {"role": "assistant", "content": assistant_text}},
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [sys.executable, str(STOP_GUARD)],
                    input=json.dumps(
                        {"transcript_path": str(transcript), "session_id": "session-a"},
                        ensure_ascii=False,
                    ),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=tmp,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if expected_block:
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload.get("decision"), "block")
                    self.assertIn("Agent-owned work was handed back", payload.get("reason", ""))
                else:
                    self.assertEqual(result.stdout.strip(), "", result.stdout + result.stderr)

    def test_stop_phrase_guard_allows_evidence_bound_external_handoff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="user-homework-external-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".git").mkdir()
            (tmp_path / ".claude").mkdir()
            prompt = "Запусти команду на закрытом стенде."
            session = "session-a"
            recorded = subprocess.run(
                [sys.executable, str(USER_TASK_GUARD)],
                input=json.dumps({"prompt": prompt, "session_id": session}, ensure_ascii=False),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            request_files = list((tmp_path / ".agent" / "user-tasks").glob("*/request.json"))
            self.assertEqual(len(request_files), 1)
            task_dir = request_files[0].parent
            evidence = task_dir / "evidence" / "access-inventory.txt"
            evidence.parent.mkdir()
            evidence.write_text("verified target is absent\n", encoding="utf-8")
            state_path = task_dir / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.update(
                status="BLOCKED_EXTERNAL",
                evidence=["evidence/access-inventory.txt"],
                blocker="target is absent from the verified access inventory",
                recheck="repeat inventory after access is granted",
            )
            state_path.write_text(json.dumps(state), encoding="utf-8")
            transcript = tmp_path / "transcript.jsonl"
            assistant = (
                "Blocker: target is absent from the verified access inventory. "
                "Needed authority: target access. Recheck: repeat the inventory after access. "
                "Run curl -X POST https://example.invalid/hook on the target after access is granted."
            )
            transcript.write_text(
                json.dumps({"message": {"role": "user", "content": prompt}}, ensure_ascii=False)
                + "\n"
                + json.dumps(
                    {"message": {"role": "assistant", "content": assistant}},
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(STOP_GUARD)],
                input=json.dumps(
                    {"transcript_path": str(transcript), "session_id": session},
                    ensure_ascii=False,
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "", result.stdout + result.stderr)

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

    def test_outward_claim_guard_requires_access_inventory_for_auth_blocker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-evidence-hook-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".claude").mkdir()
            for content, expected_block in (
                ("Blocker: publishing needs interactive Claude OAuth authorization.", True),
                (
                    "Blocker: publishing needs interactive Claude OAuth authorization.\n"
                    "Access inventory: python ~/.claude/scripts/access_inventory.py claude "
                    "-> nothing matched ['claude'].",
                    False,
                ),
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
                if expected_block:
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload.get("decision"), "block")
                    self.assertIn("Access inventory", payload.get("reason", ""))
                else:
                    self.assertEqual(result.stdout.strip(), "", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
