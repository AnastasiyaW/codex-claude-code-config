"""Owner 2026-11-08 («поправь хук, чтобы ему можно было дать текстовый файл со ссылками на удаление»):
several hundred guest folders had to be pasted in four messages, and only the last one counted. Now
«удали по списку <file.txt>» counts as pasting the file's path lines. Refused: no list wording (that
deletes the file itself), a list edited after her message, a missing file, a path not in the list, a
question, a non-path line used as approval text, and a database named only in the file.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_HOOKS))
_SPEC = importlib.util.spec_from_file_location("hcg", _HOOKS / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

A, B = r"D:\work\build-a", r"D:\work\proof-b"


def rm(*paths: str) -> str:
    quoted = ",".join(f"'{p}'" for p in paths)
    return 'ssh vm "powershell -Command Remove-' + f'Item -Recurse -Force {quoted}"'


class ListFile(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-list-file-"))
        hcg.APPROVAL_LOG = self.work / "audit.jsonl"
        self.list = self.write("guest_delete.txt", f"# guest\n{A}\n{B}\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def write(self, name: str, text: str) -> Path:
        p = self.work / name
        p.write_text(text, encoding="utf-8")
        old = dt.datetime.now().timestamp() - 60
        os.utime(p, (old, old))
        return p

    def event(self, prompt: str, sent: dt.datetime | None = None) -> dict:
        sent = sent or dt.datetime.now(dt.timezone.utc)
        row = {"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt},
               "timestamp": sent.isoformat().replace("+00:00", "Z")}
        path = self.work / f"t{len(list(self.work.iterdir()))}.jsonl"
        path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return {"transcript_path": str(path), "tool_name": "Bash", "session_id": "test"}

    def go(self, cmd: str, prompt: str, **kw) -> tuple[bool, str]:
        return hcg.approved_by_owner(cmd, self.event(prompt, **kw))

    def ok(self, cmd: str, prompt: str, **kw) -> bool:
        return self.go(cmd, prompt, **kw)[0]

    def test_list_file_names_its_lines(self) -> None:
        self.assertTrue(self.ok(rm(A, B), f"удали по списку {self.list}"))
        self.assertTrue(self.ok(rm(B), f"удали всё из файла {self.list}"))

    def test_refused(self) -> None:
        self.assertFalse(self.ok(rm(A), f"удали {self.list}"))                       # no list wording
        self.assertFalse(self.ok(rm(A, r"D:\work\other"), f"удали по списку {self.list}"))
        self.assertFalse(self.ok(rm(A), f"удалить по списку {self.list}?"))           # a question
        self.assertFalse(self.ok(rm(A), f"удали по списку {self.work / 'missing.txt'}"))
        self.assertFalse(self.ok(rm(A), f"покажи список {self.list}"))                # no delete request
        before = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)          # list newer than message
        self.assertFalse(self.ok(rm(A), f"удали по списку {self.list}", sent=before))
        self.assertIn("changed after her message", self.go(rm(A), f"удали по списку {self.list}", sent=before)[1])

    def test_lines_are_paths_only(self) -> None:
        bad = self.write("bad.txt", f"{A}\nдa, перезапусти\nD:/work/x; rm -rf /\n")
        self.assertTrue(self.ok(rm(A), f"удали по списку {bad}"))                     # the path line still counts
        self.assertFalse(self.ok("ssh vm 'sudo reboot'", f"удали по списку {bad}"))     # text never approves a restart
        self.assertIn("not an absolute path", self.go(rm(r"D:\work\zz"), f"удали по списку {bad}")[1])
        word = self.write("word.txt", "D:\\work\\перезапусти сервер\n")                # a path that reads as a request
        self.assertFalse(self.ok("ssh vm 'sudo reboot'", f"удали по списку {word}"))

    def test_irreplaceable_needs_her_words(self) -> None:
        db = self.write("db.txt", "D:\\work\\shop.sqlite\n")
        self.assertFalse(self.ok(rm(r"D:\work\shop.sqlite"), f"удали по списку {db}"))
        self.assertTrue(self.ok(rm(r"D:\work\shop.sqlite"), f"удали по списку {db}\nD:\\work\\shop.sqlite"))


if __name__ == "__main__":
    unittest.main()
