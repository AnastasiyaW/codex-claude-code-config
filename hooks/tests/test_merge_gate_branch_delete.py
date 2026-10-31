"""Owner 2026-10-31: deleting a branch named main that is no longer the remote's default is not a merge."""
from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mgg", Path(__file__).resolve().parents[1] / "merge-gate-guard.py")
mgg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mgg)


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


class DeleteFinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        src, bare, cls.clone = root / "src", root / "bare.git", root / "clone"
        src.mkdir()
        _git(src, "init", "-q", "-b", "main")
        _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        _git(src, "branch", "oss")
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(bare), str(cls.clone)], check=True)
        cls.bare = bare

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def finding(self, *specs: str) -> str | None:
        return mgg._delete_finding(list(specs), "origin", mgg.Ctx(self.clone))

    def test_main_is_protected_while_default(self) -> None:
        _git(self.bare, "symbolic-ref", "HEAD", "refs/heads/main")
        self.assertIsNotNone(self.finding("main"))
        self.assertIsNotNone(self.finding(":main"))

    def test_main_deletable_after_default_moves(self) -> None:
        _git(self.bare, "symbolic-ref", "HEAD", "refs/heads/oss")
        try:
            self.assertIsNone(self.finding("main"))
            self.assertIsNotNone(self.finding("oss"))
        finally:
            _git(self.bare, "symbolic-ref", "HEAD", "refs/heads/main")

    def test_feature_branch_and_unreadable_remote(self) -> None:
        self.assertIsNone(self.finding("ops/org-runner"))
        self.assertIsNotNone(mgg._delete_finding(["main"], "origin", mgg.Ctx(self.clone, remote=True)))
        self.assertIsNotNone(self.finding("$B"))


class NativePath(unittest.TestCase):
    def test_git_bash_drive_paths(self) -> None:
        want = ("D:/tmp/x", "D:/") if mgg.os.name == "nt" else ("/d/tmp/x", "/d")
        self.assertEqual((mgg._native_path("/d/tmp/x"), mgg._native_path("/d")), want)
        self.assertEqual(mgg._native_path("/dev/null"), "/dev/null")
        self.assertEqual(mgg._native_path("rel/p"), "rel/p")


if __name__ == "__main__":
    unittest.main()
