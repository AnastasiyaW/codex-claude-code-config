"""delete_from_list.py: deletes exactly the listed paths, verifies them, refuses a changed list
and protected paths. Runs main() in-process against a temporary list folder and fixtures only."""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "delete_from_list.py"


def load():
    spec = importlib.util.spec_from_file_location("delete_from_list", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeleteFromListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dfl-test-")
        root = Path(self.tmp.name)
        self.mod = load()
        self.mod.LIST_DIR = root / "lists"
        self.mod.LIST_DIR.mkdir()
        self.mod.APPROVAL_LOG = root / "approvals.jsonl"
        self.mod.CONSUMED = self.mod.LIST_DIR / ".consumed-approvals.jsonl"
        self.data = root / "work" / "proj" / "run"
        (self.data / "sub").mkdir(parents=True)
        (self.data / "a.txt").write_text("x")
        (self.data / "sub" / "b.txt").write_text("y")
        self.keep = self.data / "keep.txt"
        self.keep.write_text("z")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_main(self, *argv: str) -> int:
        saved = sys.argv
        sys.argv = ["delete_from_list.py", *argv]
        try:
            return self.mod.main()
        finally:
            sys.argv = saved

    def make_list(self, lines: list[str], approve: bool = True) -> tuple[Path, str]:
        lst = self.mod.LIST_DIR / "l.txt"
        lst.write_text("# test\n" + "\n".join(lines) + "\n", encoding="utf-8")
        sha = hashlib.sha256(lst.read_bytes()).hexdigest()[:16]
        if approve:  # what the guard writes after the owner's go-ahead
            rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                   "list": self.mod.list_key(str(lst)), "sha": sha}
            with self.mod.APPROVAL_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        return lst, sha

    def test_without_guard_approval_nothing_is_deleted(self) -> None:
        lst, sha = self.make_list([(self.data / "a.txt").as_posix()], approve=False)
        self.assertEqual(1, self.run_main(str(lst), "--sha", sha))
        self.assertTrue((self.data / "a.txt").exists())

    def test_approval_is_one_shot(self) -> None:
        lst, sha = self.make_list([(self.data / "a.txt").as_posix()])
        self.assertEqual(0, self.run_main(str(lst), "--sha", sha))
        (self.data / "a.txt").write_text("again")
        self.assertEqual(1, self.run_main(str(lst), "--sha", sha))
        self.assertTrue((self.data / "a.txt").exists())

    def test_deletes_listed_and_keeps_the_rest(self) -> None:
        lst, sha = self.make_list([(self.data / "a.txt").as_posix(), (self.data / "sub").as_posix()])
        self.assertEqual(0, self.run_main(str(lst), "--sha", sha))
        self.assertFalse((self.data / "a.txt").exists())
        self.assertFalse((self.data / "sub").exists())
        self.assertTrue(self.keep.exists())
        report = json.loads(lst.with_suffix(".result.json").read_text(encoding="utf-8"))
        self.assertEqual(0, report["failed"])

    def test_changed_list_deletes_nothing(self) -> None:
        lst, sha = self.make_list([(self.data / "a.txt").as_posix()])
        lst.write_text(lst.read_text(encoding="utf-8") + self.keep.as_posix() + "\n", encoding="utf-8")
        self.assertEqual(2, self.run_main(str(lst), "--sha", sha))
        self.assertTrue((self.data / "a.txt").exists())
        self.assertTrue(self.keep.exists())

    def test_list_outside_folder_is_refused(self) -> None:
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text((self.data / "a.txt").as_posix() + "\n", encoding="utf-8")
        sha = hashlib.sha256(outside.read_bytes()).hexdigest()[:16]
        self.assertEqual(2, self.run_main(str(outside), "--sha", sha))
        self.assertTrue((self.data / "a.txt").exists())

    def test_protected_path_is_refused_others_proceed(self) -> None:
        protected = (self.data / ".git").as_posix()
        Path(protected).mkdir()
        lst, sha = self.make_list([protected, (self.data / "a.txt").as_posix()])
        self.assertEqual(1, self.run_main(str(lst), "--sha", sha))
        self.assertTrue(Path(protected).exists())
        self.assertFalse((self.data / "a.txt").exists())

    def test_show_deletes_nothing(self) -> None:
        lst, _ = self.make_list([(self.data / "a.txt").as_posix()])
        self.assertEqual(0, self.run_main(str(lst), "--show"))
        self.assertTrue((self.data / "a.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
