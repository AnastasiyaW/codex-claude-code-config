"""Owner 2026-10-31: «удали C:\\...\\profiles\\local~2» (full paths) was refused because any "~digit"
was taken for an 8.3 short name. A name Windows confirms as its own long name is allowed; a real 8.3
alias, a missing path and a trailing dot stay refused.
"""
from __future__ import annotations

import ctypes
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

AMBIGUOUS = "ambiguous Windows name (trailing dot/space or 8.3 short name)"


def _short(path: Path) -> str | None:
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    return buf.value if n and buf.value.lower() != str(path).lower() else None


@unittest.skipUnless(sys.platform == "win32", "Windows names")
class TildeName(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hcg-tilde-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_real_long_name_with_tilde_digit_is_allowed(self):
        d = self.root / "local~2"
        d.mkdir()
        self.assertNotEqual(hcg.target_hard_limit(str(d), recursive=True), AMBIGUOUS)

    def test_missing_path_with_tilde_digit_stays_refused(self):
        self.assertEqual(hcg.target_hard_limit(str(self.root / "gone~3"), recursive=True), AMBIGUOUS)

    def test_trailing_dot_stays_refused(self):
        self.assertEqual(hcg.target_hard_limit(str(self.root) + "/x.", recursive=True), AMBIGUOUS)

    def test_program_files_alias_stays_refused(self):
        if not Path("C:/PROGRA~1").exists():
            self.skipTest("no 8.3 alias on C:")
        self.assertEqual(hcg.target_hard_limit("C:/PROGRA~1", recursive=True), AMBIGUOUS)

    def test_real_short_alias_stays_refused(self):
        d = self.root / "a rather long folder name for an alias"
        d.mkdir()
        alias = _short(d)
        if not alias or "~" not in Path(alias).name:
            self.skipTest("8.3 names are not generated on this volume")
        self.assertEqual(hcg.target_hard_limit(alias, recursive=True), AMBIGUOUS)


if __name__ == "__main__":
    unittest.main()
