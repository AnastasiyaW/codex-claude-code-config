from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "harness-load-advisor.py"


def run_hook(root: Path, assistant_text: str) -> tuple[dict | None, str]:
    transcript = root / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {"message": {"role": "assistant", "content": assistant_text}},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    home = root / "home"
    home.mkdir(exist_ok=True)
    feedback = root / "feedback"
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PYTHONIOENCODING": "utf-8",
        "HARNESS_FEEDBACK_DIR": str(feedback),
    }
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=root,
        input=json.dumps({
            "transcript_path": str(transcript),
            "session_id": "harness-test",
            "cwd": str(root),
        }),
        text=True,
        capture_output=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    payload = None
    for line in result.stdout.splitlines():
        if line.startswith("{"):
            payload = json.loads(line)
            break
    return payload, result.stdout + result.stderr


class HarnessLoadAdvisorTests(unittest.TestCase):
    def test_mis_scoped_release_gate_blocks_staging_close_and_records_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harness-overload-") as raw:
            root = Path(raw)
            (root / ".claude").mkdir()
            payload, output = run_hook(
                root,
                "The VM-harness is overloaded with production-signing and blocks the ordinary staging smoke.",
            )
            self.assertEqual(payload and payload.get("decision"), "block", output)
            self.assertIn("HARNESS_OVERLOAD", payload["reason"])
            self.assertIn("staging-smoke", payload["reason"])
            event = json.loads((root / "feedback" / "events.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(event["event"], "harness-overload")
            self.assertEqual(event["profile"], "staging-smoke")
            self.assertTrue(event["mentions_release_gate"])
            self.assertTrue(event["mentions_staging_smoke"])

    def test_mis_scoped_compatibility_gate_blocks_staging_close(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harness-compatibility-") as raw:
            root = Path(raw)
            payload, output = run_hook(
                root,
                "The GPU compatibility runner is overloaded and blocks the ordinary staging smoke.",
            )
            self.assertEqual(payload and payload.get("decision"), "block", output)
            event = json.loads((root / "feedback" / "events.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(event["profile"], "staging-smoke")
            self.assertFalse(event["mentions_release_gate"])
            self.assertTrue(event["mentions_specialized_gate"])

    def test_unrelated_release_report_is_silent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harness-clear-") as raw:
            root = Path(raw)
            payload, output = run_hook(
                root,
                "Release attestation passed: Authenticode and signing evidence are complete.",
            )
            self.assertIsNone(payload, output)
            self.assertFalse((root / "feedback" / "events.jsonl").exists())

    def test_resolved_profile_split_is_not_retriggered(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harness-resolved-") as raw:
            root = Path(raw)
            payload, output = run_hook(
                root,
                "Fixed: staging smoke is separate from release-attestation; signing remains release-only.",
            )
            self.assertIsNone(payload, output)

    def test_quoted_ui_string_is_not_overload_feedback(self) -> None:
        # 2026-10-02 false positive: a screen title in a design-bug report
        # matched the explicit-feedback pattern "слишком много".
        title = "слишком много попыток"
        for quoted in (f"«{title}»", f'"{title}"', f"“{title}”", f"`{title}`"):
            with self.subTest(quoted=quoted), tempfile.TemporaryDirectory(prefix="harness-quoted-") as raw:
                root = Path(raw)
                payload, output = run_hook(
                    root,
                    f"Экран 9 {quoted} (rate-limited): кнопка уезжает за край, "
                    "исправлено в release-сборке.",
                )
                self.assertIsNone(payload, output)
                self.assertFalse((root / "feedback" / "events.jsonl").exists())

    def test_blanked_quote_keeps_its_sentence_end(self) -> None:
        # Blanking "merge." must not join two sentences into a block->staging match.
        with tempfile.TemporaryDirectory(prefix="harness-sentence-") as raw:
            payload, output = run_hook(Path(raw), 'CI блокирует "merge." staging smoke прошёл')
            self.assertIsNone(payload, output)

    def test_unquoted_complaint_still_blocks(self) -> None:
        complaint = "харнесс слишком жёсткий, блокирует smoke"
        # A stray mark on the same line must not pair with a later quote and hide it.
        for text in (
            complaint,
            f'Монитор 27" — {complaint} на "VM-2".',
            f"Экран «Повтор без закрытия; {complaint}; экран «Готово» ок.",
            f"Экран „Повтор; {complaint}; экран “Готово” ок.",
            f'Монитор "LG; {complaint}; диагональ 27" ок.',
        ):
            with self.subTest(text=text), tempfile.TemporaryDirectory(prefix="harness-complaint-") as raw:
                payload, output = run_hook(Path(raw), text)
                self.assertEqual(payload and payload.get("decision"), "block", output)

    def test_yo_spelling_matches_declared_overload(self) -> None:
        # "жёсткий" must meet the same pattern as "жесткий".
        with tempfile.TemporaryDirectory(prefix="harness-yo-") as raw:
            root = Path(raw)
            payload, output = run_hook(root, "Харнесс слишком жёсткий для обычной проверки.")
            self.assertEqual(payload and payload.get("decision"), "block", output)
            self.assertIn("declared-overload", payload["reason"])

    def test_staging_policy_cannot_embed_release_only_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="harness-policy-") as raw:
            root = Path(raw)
            (root / ".claude").mkdir()
            (root / ".claude" / "test-policy.json").write_text(
                json.dumps(
                    {
                        "profiles": {
                            "staging-smoke": {
                                "commands": [["python", "scripts/verify-signing.py"]],
                                "forbidden_tokens": ["sign", "authenticode"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload, output = run_hook(root, "ordinary staging check complete")
            self.assertEqual(payload and payload.get("decision"), "block", output)
            self.assertIn("policy-staging-smoke-forbidden", payload["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
