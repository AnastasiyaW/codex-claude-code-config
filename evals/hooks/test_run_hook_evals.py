#!/usr/bin/env python3
"""Tests for run_hook_evals.py: trials, pass@k / pass^k, three exit states.

Each grader rule has a control that must come out red: an allow-all hook in
place of a guard fails the refuse cases, a crashing hook is not read as allow,
and a hook that fails one trial in three breaks pass^k.

Run: python evals/hooks/test_run_hook_evals.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import run_hook_evals as runner  # noqa: E402

ALLOW_ALL = "import sys\nsys.stdin.read()\n"
BLOCK_ALL = 'import json, sys\nsys.stdin.read()\nprint(json.dumps({"decision": "block", "reason": "no"}))\n'
CRASH = "import sys\nsys.stdin.read()\nraise RuntimeError('boom')\n"
# Blocks on trials 1 and 2, allows on trial 3: a guard that holds two times in three.
FLAKY = (
    "import json, os, sys\nsys.stdin.read()\n"
    "p = os.environ['EVAL_TEST_COUNTER']\n"
    "n = int(open(p).read()) + 1 if os.path.exists(p) else 1\n"
    "open(p, 'w').write(str(n))\n"
    "if n % 3:\n    print(json.dumps({'decision': 'block', 'reason': 'no'}))\n"
)


def case(cid: str, hook: str, expect: str, kind: str = "regression") -> dict:
    return {"id": cid, "hook": hook, "expect": expect, "kind": kind,
            "stdin": {"tool_name": "Bash", "tool_input": {"command": "x"}}}


class Runner(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hook-evals-test-"))
        self.hooks = self.work / "hooks"
        self.hooks.mkdir()
        for name, body in (("allow.py", ALLOW_ALL), ("block.py", BLOCK_ALL),
                           ("crash.py", CRASH), ("flaky.py", FLAKY)):
            (self.hooks / name).write_text(body, encoding="utf-8")
        self.saved = (runner.HOOKS_DIR, runner.HERE)
        runner.HOOKS_DIR, runner.HERE = self.hooks, self.work
        os.environ["EVAL_TEST_COUNTER"] = str(self.work / "counter")

    def tearDown(self) -> None:
        runner.HOOKS_DIR, runner.HERE = self.saved
        os.environ.pop("EVAL_TEST_COUNTER", None)
        shutil.rmtree(self.work, ignore_errors=True)

    def run_suite(self, cases: list[dict], trials: int) -> tuple[int, dict]:
        (self.work / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        out = self.work / "out.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = runner.main(["--trials", str(trials), "--json", str(out)])
        return code, json.loads(out.read_text(encoding="utf-8"))

    def test_all_pass_exit_0(self) -> None:
        code, report = self.run_suite([case("a", "block.py", "block"), case("b", "allow.py", "allow"),
                                       case("c", "allow.py", "allow")], 3)
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["regression"]["pass_hat_k"], 1.0)

    def test_allow_all_guard_fails_refuse_case(self) -> None:
        code, report = self.run_suite([case("refuse", "allow.py", "block")], 2)
        self.assertEqual(code, 1)
        self.assertEqual(report["cases"][0]["trials"], ["FAIL", "FAIL"])

    def test_crash_is_not_read_as_allow(self) -> None:
        code, report = self.run_suite([case("act", "crash.py", "allow")], 1)
        self.assertEqual(code, 2)
        self.assertEqual(report["cases"][0]["trials"], ["UNKNOWN"])
        self.assertEqual(report["summary"]["regression"]["not_run"], 1)

    def test_nonzero_exit_without_traceback_is_not_allow(self) -> None:
        (self.hooks / "exit1.py").write_text("import sys\nsys.stdin.read()\nsys.exit(1)\n", encoding="utf-8")
        code, report = self.run_suite([case("act", "exit1.py", "allow")], 1)
        self.assertEqual((code, report["cases"][0]["trials"]), (2, ["UNKNOWN"]))

    def test_exit_2_is_a_block(self) -> None:
        (self.hooks / "exit2.py").write_text(
            "import sys\nsys.stdin.read()\nsys.stderr.write('denied here')\nsys.exit(2)\n", encoding="utf-8")
        refuse = dict(case("refuse", "exit2.py", "block"), reason_contains="denied here")
        code, _ = self.run_suite([refuse, case("act", "exit2.py", "allow", "capability")], 1)
        self.assertEqual(code, 0)
        _, report = self.run_suite([case("act", "exit2.py", "allow")], 1)
        self.assertEqual(report["cases"][0]["trials"], ["FAIL"])

    def test_missing_hook_is_unknown(self) -> None:
        code, _ = self.run_suite([case("gone", "absent.py", "allow")], 1)
        self.assertEqual(code, 2)

    def test_flaky_guard_passes_at_k_but_not_hat_k(self) -> None:
        code, report = self.run_suite([case("f", "flaky.py", "block"), case("b", "block.py", "block")], 3)
        row = report["summary"]["regression"]
        self.assertEqual(report["cases"][0]["trials"], ["PASS", "PASS", "FAIL"])
        self.assertEqual(row["pass_at_k"], 1.0)
        self.assertEqual(row["pass_hat_k"], 0.5)
        self.assertEqual(row["flaky"], ["f"])
        self.assertEqual(code, 1, "one failing trial of a regression case is a failure")

    def test_capability_failure_does_not_fail_exit(self) -> None:
        code, report = self.run_suite([case("cap", "allow.py", "block", "capability"),
                                       case("reg", "block.py", "block")], 2)
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["capability"]["pass_at_k"], 0.0)

    def test_console_names_flaky_balance_and_saturation(self) -> None:
        cases = [case("f", "flaky.py", "block"), case("act", "allow.py", "allow"),
                 case("cap", "block.py", "block", "capability")]
        (self.work / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            runner.main(["--trials", "3"])
        text = buf.getvalue()
        self.assertIn("[FLAKY]", text)
        self.assertIn("(2/3 trials passed)", text)
        self.assertIn("refuse (block) cases: 2, act cases: 1", text)
        self.assertIn("[capability]", text)
        self.assertIn("capability set saturated", text)
        single = io.StringIO()
        (self.work / "cases.json").write_text(json.dumps([case("r", "allow.py", "block")]), encoding="utf-8")
        with contextlib.redirect_stdout(single):
            runner.main(["--trials", "1"])
        self.assertIn("[FAIL]", single.getvalue())
        self.assertNotIn("trials passed)", single.getvalue())
        self.assertNotIn("capability set saturated", single.getvalue())

    def test_default_is_one_trial_and_zero_is_refused(self) -> None:
        (self.work / "cases.json").write_text(json.dumps([case("a", "block.py", "block")]), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main([]), 0)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                runner.main(["--trials", "0"])

    def test_repeated_message_is_printed_once_and_kind_tag_only_on_capability(self) -> None:
        _, report = self.run_suite([case("r", "allow.py", "block")], 3)
        self.assertEqual(len(report["cases"][0]["messages"]), 1)
        (self.work / "cases.json").write_text(json.dumps([case("r", "allow.py", "block")]), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            runner.main(["--trials", "1"])
        self.assertNotIn("[capability]", buf.getvalue())

    def test_unknown_kind_is_not_run(self) -> None:
        code, _ = self.run_suite([case("x", "block.py", "block", "smoke")], 1)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
