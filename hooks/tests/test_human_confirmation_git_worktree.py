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
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True, capture_output=True,
                       stdin=subprocess.DEVNULL)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.main)], check=True, capture_output=True,
                       stdin=subprocess.DEVNULL)
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

    def test_gitdir_outside_worktrees_is_not_trusted(self) -> None:
        fake = self.main / ".git"  # a working gitdir, but not one of .git/worktrees
        with open(self.wt / ".git", "r+", encoding="utf-8") as fh:  # hidden on Windows: "w" is refused
            fh.write(f"gitdir: {fake}\n")
            fh.truncate()
        self.assertEqual(self.info(self.wt), ("too many databases/backups inside", None))

    def test_gitdir_inside_target_is_not_trusted(self) -> None:
        inner = self.wt / "evil" / ".git" / "worktrees" / "x"
        inner.mkdir(parents=True)
        (inner / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (inner / "gitdir").write_text(str(self.wt / ".git") + "\n", encoding="utf-8")
        with open(self.wt / ".git", "r+", encoding="utf-8") as fh:
            fh.write(f"gitdir: {inner}\n")
            fh.truncate()
        self.assertEqual(self.info(self.wt), ("too many databases/backups inside", None))

    def test_worktree_not_listed_by_its_repository(self) -> None:
        gitdir = self.main / ".git" / "worktrees" / "wt" / "gitdir"
        with open(gitdir, "r+", encoding="utf-8") as fh:
            fh.write(str(self.work / "elsewhere" / ".git") + "\n")
            fh.truncate()
        self.assertEqual(self.info(self.wt), ("too many databases/backups inside", None))

    def test_repo_fsmonitor_is_not_run(self) -> None:
        marker = self.work / "ran.txt"
        script = self.work / "monitor.py"
        script.write_text(f"open({str(marker)!r}, 'w').write('x')\n", encoding="utf-8")
        git(self.main, "config", "core.fsmonitor", f'python "{script}"')
        self.assertEqual(self.info(self.wt), (None, []))
        self.assertFalse(marker.exists(), "hook ran a command from the repository config")

    def test_broken_git_means_no_exemption(self) -> None:
        hcg.GIT = str(self.work / "no-such-git")
        self.assertEqual(self.info(self.wt), ("too many databases/backups inside", None))


if __name__ == "__main__":
    unittest.main()
