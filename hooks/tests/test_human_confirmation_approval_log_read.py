"""Owner 2026-11-16 («проверь хук чот с ним не то»): `tail ... deletion-approvals.jsonl | cut` and a grep for
the name were refused as «list script run», a delete. Reading the log writes nothing; any form that can
write it, or that runs the list scripts, stays refused.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_HOOKS = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("hcg_log_read", _HOOKS / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

LOG = "~/.claude/logs/deletion-approvals.jsonl"


class ApprovalLogRead(unittest.TestCase):
    def test_reading_the_log_passes(self) -> None:
        for cmd in (
            f"tail -c 4000 {LOG} | tail -4 | cut -c1-400",
            f"cd ~/.claude/logs && tail -n 5 deletion-approvals.jsonl; grep -a be29be44 safety.log | tail -8",
            "grep -n deletion-approvals hooks/tests/*.py | head -10",
            f"wc -l {LOG}",
            f"jq -c .action {LOG} | tail -3",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(hcg.decide(cmd), (True, None))

    def test_writing_the_log_or_running_the_list_script_is_refused(self) -> None:
        for cmd in (
            f"echo '{{}}' >> {LOG}",
            f"cat x | tee -a {LOG}",
            f"sed -i 1d {LOG}",
            f"cp forged.jsonl {LOG}",
            f"sort -o {LOG} forged.jsonl",
            f"awk '{{print > \"{LOG}\"}}' forged.jsonl",
            f"cat $(echo {LOG})",
            f"tail {LOG} & python x.py",
            f"tail {LOG}; python ~/.claude/claude-code-config/scripts/delete_from_list.py l.txt --sha abc",
            f"tail {LOG}\npython x.py",
            f"./cat {LOG}",
            f"/tmp/evil/cat {LOG}",
            f"C:/Windows/System32/cat {LOG}",
            f"cat {LOG} | ./wc -l",
        ):
            with self.subTest(cmd=cmd):
                allowed, hit = hcg.decide(cmd)
                self.assertFalse(allowed)
                self.assertIsNotNone(hit)


class GlobScriptLauncher(unittest.TestCase):
    """The same day: `pytest a.py b_*.py` was refused, `.py b_*.py` read as the `py` launcher with a glob."""

    def test_a_py_ending_is_not_the_launcher(self) -> None:
        cmd = "python -m pytest -q hooks/tests/test_relocate_list.py hooks/tests/test_human_confirmation_*.py"
        self.assertEqual(hcg.decide(cmd), (True, None))

    def test_a_script_given_by_a_glob_stays_refused(self) -> None:
        for cmd in ("python scripts/del*.py x", "py scripts/d?.py", "python3 'scripts/r*.py'", "cd x && py s*.py"):
            with self.subTest(cmd=cmd):
                self.assertEqual(hcg.decide(cmd), (False, "python script given by a glob"))


if __name__ == "__main__":
    unittest.main()
