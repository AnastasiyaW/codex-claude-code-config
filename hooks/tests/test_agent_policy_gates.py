"""agent_policy_gates, driven as the harness drives it: JSON on stdin, verdict on stdout."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "agent_policy_gates.py"
POLICY = {
    "human_owned": ["AGENTS.md", "docs/INCIDENTS.md", ".github/agent-policy.json"],
    "pr_max_added_lines": 20,
    "pr_size_ignore": ["*.svg"],
    "pr_required_sections": ["## Зачем", "## Кто за что отвечает", "## Проверка"],
    "widget_test_paths": ["tools/widget-common"],
}
GOOD_BODY = "## Зачем\nx\n## Кто за что отвечает\nx\n## Проверка\nx\n"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                   stdin=subprocess.DEVNULL)  # the harness's stdin may not be inheritable


class Gates(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="policy-gates-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.home = Path(tmp.name) / "home"
        (self.root / ".github").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / "tools" / "widget-common").mkdir(parents=True)
        (self.root / ".github" / "agent-policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        (self.root / "README.md").write_text("# readme\n", encoding="utf-8")
        (self.root / ".github" / "pull_request_template.md").write_text(
            "## Зачем\n\n<!-- why -->\n\n## Кто за что отвечает\n\n| Сущность | Отвечает за |\n"
            "|---|---|\n|  |  |\n\n## Проверка\n\n<!-- what ran -->\n", encoding="utf-8")
        git(self.root, "init", "-q", "-b", "master")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "config", "user.name", "t")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")
        git(self.root, "update-ref", "refs/remotes/origin/master", "HEAD")
        git(self.root, "checkout", "-qb", "feature")

    def hook(self, event: dict) -> str:
        """The verdict: "block: <reason>" or "allow"."""
        env = {**os.environ, "USERPROFILE": str(self.home), "HOME": str(self.home)}
        event = {"session_id": "s1", "cwd": str(self.root), **event}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), env=env,
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        if not out.stdout.strip():
            return "allow"
        verdict = json.loads(out.stdout)
        return f"{verdict['decision']}: {verdict['reason']}"

    def prompt(self, text: str) -> None:
        self.assertEqual(self.hook({"hook_event_name": "UserPromptSubmit", "prompt": text}), "allow")

    def write(self, rel: str) -> str:
        return self.hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                          "tool_input": {"file_path": str(self.root / rel)}})

    def bash(self, command: str) -> str:
        return self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                          "tool_input": {"command": command}})


class HumanOwnedTest(Gates):
    def test_an_agent_edit_of_a_human_owned_doc_is_refused(self) -> None:
        self.prompt("почини тесты")
        self.assertTrue(self.write("AGENTS.md").startswith("block:"))

    def test_other_files_stay_open(self) -> None:
        self.prompt("почини тесты")
        self.assertEqual(self.write("README.md"), "allow")

    def test_the_owner_naming_the_file_unlocks_it_for_that_turn(self) -> None:
        self.prompt("допиши в AGENTS.md раздел про тесты")
        self.assertEqual(self.write("AGENTS.md"), "allow")
        self.assertTrue(self.write("docs/INCIDENTS.md").startswith("block:"), "only the named file")
        self.prompt("спасибо, дальше сама")
        self.assertTrue(self.write("AGENTS.md").startswith("block:"), "the next prompt resets it")

    def test_a_file_named_only_in_pasted_text_stays_locked(self) -> None:
        self.prompt('внедри это <pasted_content id="1">Только люди редактируют AGENTS.md'
                    '</pasted_content id="1">')
        self.assertTrue(self.write("AGENTS.md").startswith("block:"))

    def test_a_shell_write_to_a_human_owned_doc_is_refused_and_a_read_is_not(self) -> None:
        self.prompt("почини тесты")
        self.assertTrue(self.bash("echo x >> AGENTS.md").startswith("block:"))
        self.assertTrue(self.bash("sed -i 's/a/b/' docs/INCIDENTS.md").startswith("block:"))
        self.assertEqual(self.bash("cat AGENTS.md"), "allow")

    def test_a_codex_apply_patch_to_a_human_owned_doc_is_refused(self) -> None:
        # Codex names the files only in the patch headers, relative to its cwd.
        def body_for(*files: str) -> str:
            return "*** Begin Patch\n" + "".join(
                f"*** Update File: {f}\n@@\n-x\n+y\n" for f in files) + "*** End Patch\n"

        def patch(*files: str) -> str:
            return self.hook({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                              "tool_input": {"command": body_for(*files)}})
        self.prompt("почини тесты")
        self.assertEqual(patch("README.md"), "allow")
        self.assertTrue(patch("README.md", "docs/INCIDENTS.md").startswith("block:"))
        rename = ("*** Begin Patch\r\n*** Update File: README.md\r\n*** Move to: docs/INCIDENTS.md\r\n"
                  "@@\r\n-x\r\n+y\r\n*** End Patch\r\n")
        self.assertTrue(self.hook({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                                   "tool_input": {"command": rename}}).startswith("block:"),
                        "renaming a file onto a protected path overwrites it")
        as_string = json.dumps({"command": body_for("docs/INCIDENTS.md")})
        self.assertTrue(self.hook({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                                   "tool_input": as_string}).startswith("block:"),
                        "tool_input sent as a JSON string")
        forged = self.home / ".claude" / "state" / "human-owned-unlocks" / "s1.json"
        move_in = f"*** Begin Patch\n*** Update File: README.md\n*** Move to: {forged}\n*** End Patch\n"
        self.assertTrue(self.hook({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                                   "tool_input": {"command": move_in}}).startswith("block:"),
                        "a rename cannot forge an unlock record")
        self.prompt("допиши в docs/INCIDENTS.md разбор")
        self.assertEqual(patch("docs/INCIDENTS.md"), "allow")

    def test_the_unlock_records_cannot_be_forged_by_the_agent(self) -> None:
        forged = self.home / ".claude" / "state" / "human-owned-unlocks" / "s1.json"
        self.assertTrue(self.hook({"hook_event_name": "PreToolUse", "tool_name": "Write",
                                   "tool_input": {"file_path": str(forged)}}).startswith("block:"))

    def test_a_repo_without_a_policy_is_left_alone(self) -> None:
        (self.root / ".github" / "agent-policy.json").unlink()
        self.assertEqual(self.write("AGENTS.md"), "allow")


class PrCreateTest(Gates):
    def commit_lines(self, n: int) -> None:
        (self.root / "code.py").write_text("x = 1\n" * n, encoding="utf-8")
        git(self.root, "add", "code.py")
        git(self.root, "commit", "-qm", "change")

    def body_file(self, text: str) -> Path:
        path = self.root.parent / "body.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_small_pr_with_the_template_passes(self) -> None:
        self.commit_lines(5)
        self.assertEqual(self.bash(f'gh pr create --title t --body-file "{self.body_file(GOOD_BODY)}"'),
                         "allow")

    def test_a_pr_over_the_cap_is_refused(self) -> None:
        self.commit_lines(30)
        verdict = self.bash(f'gh pr create --title t --body-file "{self.body_file(GOOD_BODY)}"')
        self.assertIn("adds 30 lines, the cap is 20", verdict)

    def test_a_description_without_the_sections_is_refused(self) -> None:
        self.commit_lines(5)
        verdict = self.bash('gh pr create --title t --body "fixes stuff"')
        self.assertIn("## Кто за что отвечает", verdict)

    def test_no_description_at_all_is_refused(self) -> None:
        self.commit_lines(5)
        self.assertIn("no description", self.bash("gh pr create --fill"))

    def test_the_untouched_template_is_refused(self) -> None:
        self.commit_lines(5)
        template = self.root / ".github" / "pull_request_template.md"
        verdict = self.bash(f'gh pr create --title t --body-file "{template}"')
        self.assertIn("(empty)", verdict)

    def test_an_ignored_file_with_a_non_ascii_name_is_not_counted(self) -> None:
        # Quoted by git without -z, "иконка.svg" did not match "*.svg" (review 25.09).
        (self.root / "иконка.svg").write_text("<svg/>\n" * 30, encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "icon")
        self.assertEqual(self.bash(f'gh pr create --title t --body-file "{self.body_file(GOOD_BODY)}"'),
                         "allow")


class OwnerCommandsTest(Gates):
    RESET = "python scripts/ci_local.py --reset-review-rounds"

    def test_the_review_round_reset_is_the_owners_call(self) -> None:
        self.prompt("почини тесты")
        self.assertIn("owner", self.bash(self.RESET))
        self.prompt("нашла причину, сбрось счётчик: --reset-review-rounds")
        self.assertEqual(self.bash(self.RESET), "allow")

    def test_other_spellings_of_the_reset_are_the_owners_call_too(self) -> None:
        # python -c "... q.reset_rounds(...)" reset the rounds past the flag check (review 25.09).
        self.prompt("почини тесты")
        self.assertIn("owner", self.bash('python -c "import quality_gates as q; q.reset_rounds(0)"'))
        self.assertIn("owner", self.bash("gh pr comment 5 --body '<!-- quality-review-reset -->'"))


class WriteShapesTest(Gates):
    """Review 25.09: writes the guard missed, and a read it refused."""

    def test_a_python_write_is_refused_and_a_read_with_stderr_redirect_is_not(self) -> None:
        self.prompt("почини тесты")
        self.assertTrue(self.bash("python -c \"open('AGENTS.md','w').write('')\"").startswith("block:"))
        self.assertEqual(self.bash("grep -n x AGENTS.md 2>/dev/null"), "allow")

    def test_a_patch_that_touches_a_human_owned_doc_is_refused(self) -> None:
        self.prompt("почини тесты")
        patch = self.root / "change.diff"
        patch.write_text("--- a/AGENTS.md\n+++ b/AGENTS.md\n@@ -1 +1 @@\n-# agents\n+# x\n",
                         encoding="utf-8")
        self.assertTrue(self.bash("git apply change.diff").startswith("block:"))


class WidgetTestsTest(Gates):
    def test_a_bare_widget_suite_is_refused_with_the_right_command(self) -> None:
        verdict = self.bash("cd tools/widget-common && .venv/Scripts/python.exe -m unittest discover")
        self.assertIn("hidden_run.py", verdict)

    def test_the_hidden_runners_pass(self) -> None:
        self.assertEqual(self.bash("python scripts/ci_local.py --job widgets"), "allow")
        self.assertEqual(self.bash("python scripts/hidden_run.py --cwd tools/widget-common -- "
                                   "python -m unittest test_desk"), "allow")

    def test_a_test_file_run_directly_is_refused_and_staging_it_is_not(self) -> None:
        # `python test_desk.py` ran unittest.main() on the owner's screen (review 25.09).
        self.assertIn("hidden_run.py", self.bash("cd tools/widget-common && python test_desk.py"))
        self.assertIn("hidden_run.py", self.bash("cd tools/widget-common && python -munittest test_desk"))
        self.assertEqual(self.bash("git add tools/widget-common/test_desk.py"), "allow")

    def test_other_tests_are_not_touched(self) -> None:
        self.assertEqual(self.bash("cd bot && python -m pytest -q"), "allow")


if __name__ == "__main__":
    unittest.main()
