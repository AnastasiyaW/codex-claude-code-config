"""Owner 2026-11-08 («поправь хук, чтобы можно было назвать папку просто и все файлы внутри удалились»):
a folder full of files that look like databases (vcpkg ports, installed) was refused even when she
named its full path. Now a folder whose full path she typed herself goes whole. Still refused: a
bare yes to my answer, a folder that only a list file names, and another folder she did not name.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

_HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_HOOKS))
_SPEC = importlib.util.spec_from_file_location("hcg", _HOOKS / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)


def rm(*paths: str) -> str:
    quoted = ",".join(f"'{p}'" for p in paths)
    return 'ssh vm "powershell -Command Remove-' + f'Item -Recurse -Force {quoted}"'


class NamedFolderWhole(unittest.TestCase):
    def setUp(self) -> None:
        # outside TEMP (a TEMP folder passes without any request) and outside .claude (a hard limit)
        self.parent = Path(Path.cwd().anchor) / "hcg-named-whole-tests"
        self.work = self.parent / uuid.uuid4().hex[:8]
        self.dbs = self.work / "ports"
        self.dbs.mkdir(parents=True)
        for i in range(hcg.INNER_NAME_CAP + 5):
            (self.dbs / f"lib{i}.sql").write_text("x", encoding="utf-8")
        self.few = self.work / "buildtrees"
        self.few.mkdir()
        (self.few / "docSet.sql").write_text("x", encoding="utf-8")
        self.audit = self.work / "audit.jsonl"
        hcg.APPROVAL_LOG = self.audit

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)
        try:
            self.parent.rmdir()
        except OSError:
            pass

    def event(self, prompt: str, answer: str = "") -> dict:
        rows = []
        if answer:
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
        rows.append({"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt}})
        path = self.work / f"t{uuid.uuid4().hex[:6]}.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return {"transcript_path": str(path), "tool_name": "Bash", "session_id": "test"}

    def ok(self, cmd: str, prompt: str, answer: str = "") -> bool:
        return hcg.approved_by_owner(cmd, self.event(prompt, answer))[0]

    def test_named_folder_goes_whole(self) -> None:
        verdict = hcg.approved_by_owner(rm(str(self.dbs)), self.event(f"удали {self.dbs}"))
        self.assertTrue(verdict[0], verdict[1])                                       # cap exceeded inside
        self.assertTrue(self.ok(rm(str(self.few)), f"удали {self.few}"))           # one database inside
        self.assertIn("owner-named-folder-whole", self.audit.read_text(encoding="utf-8"))

    def test_refused(self) -> None:
        answer = f"**Удаление** — 1 путь, ответь «да»:\n```\n{self.dbs}\n```"
        self.assertFalse(self.ok(rm(str(self.dbs)), "да", answer))                  # my answer, not her words
        self.assertFalse(self.ok(rm(str(self.dbs), str(self.few)), f"удали {self.dbs}"))  # second not named
        lst = self.work / "list.txt"
        lst.write_text(f"{self.dbs}\n", encoding="utf-8")
        self.assertFalse(self.ok(rm(str(self.dbs)), f"удали по списку {lst}"))      # only a list line


if __name__ == "__main__":
    unittest.main()
