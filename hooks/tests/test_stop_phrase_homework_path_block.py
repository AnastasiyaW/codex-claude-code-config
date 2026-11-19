"""A deletion proposal is not user homework (measured 2026-11-19).

The owner's deletion format (rule deletion-confirm-and-verify, «Единый формат
предложения удаления») is a line «Удаление» and a plain fenced block with one
absolute path per line. The Stop guard read "launch" in `….launch.txt` and "user"
in `…\\user-tasks\\…` as a verb and an addressee, blocked the Stop, and a session
could not show its pending deletion list. Words inside a path are not
verbs or addressees; a real command in a fence, and a path block that the prose
around it hands over, still block.

Accepted limit (independent review 2026-11-19): a fence holding only a bare
script path under a neutral lead-in ("Дальше:" + `/opt/app/install.sh`) passes,
like `/opt/app/deploy.sh` already did; before, such a block was caught only when
a listed verb happened to be part of the file name.

Runs the hook as the Stop event does: a transcript with the owner's action
request and the final answer, the verdict read from the hook's stdout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(os.environ.get("HOOKS_DIR", Path(__file__).resolve().parents[1])).resolve()
GUARD = HOOKS / "stop-phrase-guard.py"
FENCE = "`" * 3
PROMPT = "Почисти временные файлы прогона exp-01 и доведи задачу до конца."
LAUNCH = "/srv/project/runs/exp-01-sizes/copy-rewrite/brush-ways-4k.launch.txt"
USER = r"D:\work\.agent\user-tasks\REQ-0000\copy-rewrite\run_brush_ways_4k.sh"
REMOTE = "builder@buildhost:/srv/runs/open.set.launch"


def proposal(*lines: str, info: str = "") -> str:
    body = "\n".join(lines)
    return (
        "Прогон закончен, итог в отчёте.\n\n"
        f"**Удаление** — {len(lines)} пути, ответь «да»:\n{FENCE}{info}\n{body}\n{FENCE}\n"
    )


def blocks(answer: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="spg-path-block-") as tmp:
        (Path(tmp) / ".claude").mkdir()
        transcript = Path(tmp) / "transcript.jsonl"
        rows = [
            {"message": {"role": "user", "content": PROMPT}},
            {"message": {"role": "assistant", "content": answer}},
        ]
        transcript.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, "-B", str(GUARD)],
            input=json.dumps({"transcript_path": str(transcript), "session_id": "path-block"}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=tmp,
            check=False,
        )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    if not result.stdout.strip():
        return False
    payload = json.loads(result.stdout)
    return payload.get("decision") == "block" and "Agent-owned work was handed back" in payload.get(
        "reason", ""
    )


class PathListIsNotHomework(unittest.TestCase):
    def test_posix_path_with_launch(self) -> None:
        self.assertFalse(blocks(proposal(LAUNCH)))

    def test_windows_path_with_user(self) -> None:
        self.assertFalse(blocks(proposal(USER)))

    def test_remote_path_and_text_label(self) -> None:
        self.assertFalse(blocks(proposal(REMOTE, LAUNCH, info="text")))

    def test_the_measured_two_path_proposal(self) -> None:
        self.assertFalse(blocks(proposal(LAUNCH, "", USER)))


class CommandsStillBlock(unittest.TestCase):
    """Must-fail controls: each blocked before the fix and must block after it."""

    def test_command_with_its_own_verb(self) -> None:
        self.assertTrue(blocks(f"Осталось:\n{FENCE}\nclaude auth login --claudeai\n{FENCE}\n"))

    def test_shell_state_then_command(self) -> None:
        self.assertTrue(blocks(f"Дальше:\n{FENCE}\n$env:X=1; psql -c 'select 1'\n{FENCE}\n"))

    def test_path_list_handed_over_by_a_verb(self) -> None:
        self.assertTrue(blocks(f"Run these:\n{FENCE}\n/opt/tools/fix.sh\n{FENCE}\n"))

    def test_path_list_handed_over_to_the_user(self) -> None:
        self.assertTrue(blocks(f"The user has to clear:\n{FENCE}\n{LAUNCH}\n{FENCE}\n"))

    def test_path_with_an_argument(self) -> None:
        self.assertTrue(blocks(f"Дальше:\n{FENCE}\n/opt/tools/launch.sh --now\n{FENCE}\n"))

    def test_shell_labelled_fence(self) -> None:
        self.assertTrue(blocks(f"Дальше:\n{FENCE}bash\n/opt/tools/launch.sh\n{FENCE}\n"))

    def test_path_then_a_command_line(self) -> None:
        self.assertTrue(blocks(proposal(LAUNCH, "npm run build")))

    def test_chained_paths_without_spaces(self) -> None:
        self.assertTrue(blocks(proposal("/opt/tools/a.sh&&/opt/tools/launch.sh")))

    def test_url_is_not_a_path(self) -> None:
        self.assertTrue(blocks(proposal("https://example.invalid/login")))

    def test_url_with_one_slash_is_not_a_path(self) -> None:
        self.assertTrue(blocks(proposal("https:/example.invalid/login")))

    def test_fence_closed_mid_line_keeps_the_command_after_it(self) -> None:
        answer = f"Осталось:\n{FENCE}\n/opt/run{FENCE}\nclaude auth login --claudeai\n{FENCE}\n"
        self.assertTrue(blocks(answer))


if __name__ == "__main__":
    unittest.main()
