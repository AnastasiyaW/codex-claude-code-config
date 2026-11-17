"""read_event decodes the payload as UTF-8, whatever the text layer's encoding is.

Why this suite exists. Hook events arrive as UTF-8 JSON on stdin, but Python's
text layer uses the locale encoding; on this Windows machine that is cp1251.
`sys.stdin.read()` therefore turned a path like `D:\\Проекты\\сайт` into
`D:\\Проекты\\СЃР°Р№С‚`, and every guard judged a directory that does not exist. On 2026-11-16 publish-bypass-guard could not resolve the
repository behind a push from such a worktree and blocked it (`unknown-repo`);
the same stall hit two other worktrees on 2026-11-14. A guard that cannot read
the path it is guarding is not a guard, so the decoding is pinned here.

The locale is emulated with PYTHONIOENCODING in the child, so the suite proves
the same thing on Windows and on CI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HOOKS = Path(os.environ.get("HOOKS_DIR", Path(__file__).resolve().parents[1]))

CYRILLIC_CWD = "D:\\Проекты\\сайт\\репозиторий"
CHILD = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("safety_common", sys.argv[1])
sc = importlib.util.module_from_spec(spec)
sys.modules["safety_common"] = sc
spec.loader.exec_module(sc)
event = sc.read_event()
print("CWD-OK" if event.get("cwd") == sys.argv[2] else "CWD-BAD")
print("CMD-OK" if event.get("tool_input", {}).get("command") == sys.argv[3] else "CMD-BAD")
print("EMPTY" if not event else "FILLED")
"""


def run_child(payload: bytes, expect_cwd: str, expect_command: str, io_encoding: str) -> list[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = io_encoding
    result = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(HOOKS / "safety_common.py"), expect_cwd, expect_command],
        input=payload, capture_output=True, env=env, check=False,
    )
    return result.stdout.decode("utf-8", "replace").split()


class ReadEventEncoding(unittest.TestCase):
    def payload(self) -> bytes:
        event = {"tool_name": "Bash", "cwd": CYRILLIC_CWD,
                 "tool_input": {"command": "git push -u origin ветка"}}
        return json.dumps(event, ensure_ascii=False).encode("utf-8")

    def test_cyrillic_path_survives_a_cp1251_text_layer(self) -> None:
        lines = run_child(self.payload(), CYRILLIC_CWD, "git push -u origin ветка", "cp1251")
        self.assertIn("CWD-OK", lines)
        self.assertIn("CMD-OK", lines)

    def test_cyrillic_path_survives_a_utf8_text_layer(self) -> None:
        lines = run_child(self.payload(), CYRILLIC_CWD, "git push -u origin ветка", "utf-8")
        self.assertIn("CWD-OK", lines)
        self.assertIn("CMD-OK", lines)

    def test_empty_stdin_stays_silent(self) -> None:
        self.assertIn("EMPTY", run_child(b"", CYRILLIC_CWD, "", "cp1251"))

    def test_malformed_payload_does_not_raise(self) -> None:
        self.assertIn("EMPTY", run_child(b"{not json", CYRILLIC_CWD, "", "cp1251"))

    def test_byte_order_mark_is_still_stripped(self) -> None:
        lines = run_child(b"\xef\xbb\xbf" + self.payload(), CYRILLIC_CWD,
                          "git push -u origin ветка", "cp1251")
        self.assertIn("CWD-OK", lines)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    if outcome.wasSuccessful():
        print(f"all {outcome.testsRun} checks correct")
    sys.exit(0 if outcome.wasSuccessful() else 1)
