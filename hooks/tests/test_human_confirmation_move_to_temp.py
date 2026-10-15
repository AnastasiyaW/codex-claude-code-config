"""Owner 2026-10-15: files the agent may not delete go into a temp folder on her request (`mv -n` into temp)."""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)


class MoveToTemp(unittest.TestCase):
    def setUp(self) -> None:
        # sources in their own folder (next to this test would be inside ~/.claude, a protected location that
        # the rule rightly refuses); the destination is another folder inside the OS temp root
        self.src = Path(tempfile.gettempdir()) / "hcg-move-temp-src"
        self.src.mkdir(exist_ok=True)
        for n in ("a.log", "b.py"):
            (self.src / n).write_text("x", encoding="utf-8")
        (self.src / "base.sqlite").write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)
        (self.src / "sub").mkdir(exist_ok=True)
        self.dest = Path(tempfile.gettempdir()) / "hcg-move-temp-dest"
        self.dest.mkdir(exist_ok=True)
        hcg.APPROVAL_LOG = Path(__file__).with_name("_move_temp_audit.jsonl")

    def tearDown(self) -> None:
        shutil.rmtree(self.src, ignore_errors=True)
        shutil.rmtree(self.dest, ignore_errors=True)
        hcg.APPROVAL_LOG.unlink(missing_ok=True)

    def p(self, name: str) -> str:
        return (self.src / name).as_posix()

    def go(self, cmd: str, prompt: str, answer: str = "", tool: str = "Bash") -> bool:
        if not hcg.move_to_temp_parts(cmd):
            return False
        return hcg._move_temp_approval(cmd, prompt, answer, {"tool_name": tool})[0]

    def test_shape(self) -> None:
        d = self.dest.as_posix()
        self.assertTrue(hcg.move_to_temp_parts(f"mv -n {self.p('a.log')} {d}/"))
        self.assertTrue(hcg.move_to_temp_parts(f"cd {self.src.as_posix()} && mv -n a.log b.py {d}/"))
        for cmd in (f"mv {self.p('a.log')} {d}/", f"mv -f {self.p('a.log')} {d}/", f"mv -n {self.p('a.log')}",
                    f"mv -n {self.p('a.log')} {d}/; rm -rf /x", f"mv -n $HOME/a {d}/", f"mv -n `ls` {d}/",
                    f"mv -n {self.p('a.log')} {d}/ | sh", f"rm {self.p('a.log')}"):
            self.assertFalse(hcg.move_to_temp_parts(cmd), cmd)

    def test_owner_request_moves_files(self) -> None:
        d = self.dest.as_posix()
        ask = "наведи порядок, а файлы, которые нельзя удалить, надо переносить внутрь темп"
        self.assertTrue(self.go(f"mv -n {self.p('a.log')} {self.p('b.py')} {d}/", ask))
        self.assertTrue(self.go(f"cd {self.src.as_posix()} && mv -n a.log b.py {d}/", ask))
        self.assertTrue(self.go(f"mv -n {self.p('a.log')} {d}/", "да", f"Перенесу 2 файла в {d}, подтверди"))
        self.assertTrue(self.go(f"mv -n {self.p('a.log')} {d}/", "наведи опрядок а файлы октоыре нельзя удалить анадо переноси внутрь темп"))

    def test_refusals(self) -> None:
        d = self.dest.as_posix()
        ask = "перенеси файлы в темп"
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", "перенеси файлы в папку проекта"))  # no temp
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", "не переноси в темп"))
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", "перенести в темп?"))
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", "да", "Удалю a.log"))  # proposal was no move
        # review 2026-10-15: negations after the verb, "нельзя переносить", English, my own negated answer
        for no in ("нельзя переносить в темп", "переносить в темп не надо", "don't move them to temp",
                   "never move files to temp"):
            self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", no), no)
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", "да", f"Не перенесу в темп {d}, удалю по списку"))
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", "да", "Перенесу файлы в темп, подтверди"))  # dest unnamed
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", "да", f"Перенесу файлы в темп {d}2, подтверди"))  # other folder
        self.assertTrue(self.go(f"mv -n {self.p('a.log')} {d}/", "да", f"Перенесу 2 файла в темп {d}?\nПодтверди."))
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/../", ask))  # .. out of the destination
        self.assertFalse(self.go(f"mv -n ~/a.log {d}/", ask))
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {Path(__file__).parent.as_posix()}/", ask))  # dest not in temp
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {tempfile.gettempdir()}/", ask))  # temp root itself
        self.assertFalse(self.go(f"mv -n {self.p('sub')} {d}/", ask))  # a folder, not a file
        self.assertFalse(self.go(f"mv -n {self.p('missing.txt')} {d}/", ask))
        self.assertFalse(self.go(f"mv -n {self.p('base.sqlite')} {d}/", ask))  # irreplaceable
        self.assertFalse(self.go(f"mv -n a.log {d}/", ask))  # relative without cd
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", ask, tool="PowerShell"))
        (self.dest / "a.log").write_text("old", encoding="utf-8")
        self.assertFalse(self.go(f"mv -n {self.p('a.log')} {d}/", ask))  # name taken in dest


if __name__ == "__main__":
    unittest.main()
