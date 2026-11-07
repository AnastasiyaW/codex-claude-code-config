"""Owner 2026-11-07 («Да, поправь хук»): her pasted list of four linked worktrees was refused as
"too many databases/backups inside": every copy holds 92 schema migrations ops/migrations/*.sql.
Inside a linked worktree a file git tracks, unchanged from a pushed HEAD, is restorable now. The
main repository, an unpushed HEAD, a modified or untracked .sql and a broken git stay refused.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_HOOKS = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("hcg", _HOOKS / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

MIGRATIONS = 60  # above INNER_NAME_CAP (50), like the 92 files that tripped the cap


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t",
                    "-c", f"core.hooksPath={cwd}/.no-hooks", *args],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL)


class GitWorktree(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-git-wt-"))
        self.remote = self.work / "remote.git"
        self.main = self.work / "main"
        self.wt = self.work / "wt"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True, stdin=subprocess.DEVNULL)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.main)], check=True, stdin=subprocess.DEVNULL)
        mig = self.main / "migrations"
        mig.mkdir()
        for i in range(MIGRATIONS):
            (mig / f"{i:05d}_step.sql").write_text(f"select {i};\n", encoding="utf-8")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "init")
        git(self.main, "remote", "add", "origin", str(self.remote))
        git(self.main, "push", "-q", "origin", "main")
        git(self.main, "fetch", "-q", "origin")
        git(self.main, "worktree", "add", "-q", "--detach", str(self.wt), "origin/main")

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)
        hcg.GIT = "git"

    def info(self, p: Path):
        return hcg.irreplaceable_info(str(p), True)

    def test_pushed_linked_worktree_is_restorable(self) -> None:
        self.assertEqual(self.info(self.wt), (None, []))

    def test_main_repository_stays_refused(self) -> None:
        self.assertEqual(self.info(self.main), ("too many databases/backups inside", None))

    def test_unpushed_head_stays_refused(self) -> None:
        git(self.wt, "checkout", "-q", "-b", "local")
        (self.wt / "note.txt").write_text("x", encoding="utf-8")
        git(self.wt, "add", "note.txt")
        git(self.wt, "commit", "-q", "-m", "local only")
        self.assertEqual(self.info(self.wt), ("too many databases/backups inside", None))

    def test_modified_and_untracked_sql_are_named(self) -> None:
        (self.wt / "migrations" / "00003_step.sql").write_text("changed;\n", encoding="utf-8")
        (self.wt / "fresh.sql").write_text("new;\n", encoding="utf-8")
        why, inner = self.info(self.wt)
        self.assertEqual(inner, ["00003_step.sql", "fresh.sql"])
        self.assertIn("fresh.sql", why)

    def test_staged_change_is_named(self) -> None:
        (self.wt / "migrations" / "00007_step.sql").write_text("staged;\n", encoding="utf-8")
        git(self.wt, "add", "migrations/00007_step.sql")
        self.assertEqual(self.info(self.wt)[1], ["00007_step.sql"])

    def test_subfolder_of_worktree_is_not_exempt(self) -> None:
        self.assertEqual(self.info(self.wt / "migrations"), ("too many databases/backups inside", None))

    def test_broken_git_means_no_exemption(self) -> None:
        hcg.GIT = str(self.work / "no-such-git")
        self.assertEqual(self.info(self.wt), ("too many databases/backups inside", None))


if __name__ == "__main__":
    unittest.main()
