"""Owner 2026-11-01 («ты мне даёшь список, я его копирую, пишу там же удали — и ты всё удаляешь»):
"Удаляй все три" after a proposal of three duplicate course folders was refused for all three, each
for a different reason (brackets in the command line, a folder in a drive root, datasets inside).

Her own request to delete that pastes every listed path now approves the deletion list: it need not
have been shown before, and what she pasted counts as named by her (drive-root entries, the
irreplaceable). Irreplaceable files inside a pasted folder count when my proposal listed them.
A bare yes keeps the old rules; a missing, partial or negated paste is refused.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HOOKS = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("hcg", _HOOKS / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)
SCRIPT = _HOOKS.parent / "scripts" / "delete_from_list.py"


class OwnerPastedList(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-owner-list-"))
        self.lists = self.work / "lists"
        self.lists.mkdir()
        hcg.DELETION_LIST_DIR = self.lists
        hcg.APPROVAL_LOG = self.work / "audit.jsonl"
        self.plain = self.work / "course [SW.BAND] (2023)"
        self.plain.mkdir()
        (self.plain / "lesson.mp4").write_bytes(b"x")
        self.db = self.work / "store.db"
        self.db.write_bytes(b"x")
        self.withdata = self.work / "Karpov (2022)"
        self.withdata.mkdir()
        (self.withdata / "lesson_dataset.csv").write_bytes(b"a,b")

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def write_list(self, *paths: Path) -> tuple[str, str]:
        f = self.lists / f"l{len(list(self.lists.iterdir()))}.txt"
        f.write_text("\n".join(str(p) for p in paths) + "\n", encoding="utf-8")
        return f.as_posix(), hashlib.sha256(f.read_bytes()).hexdigest()[:16]

    def event(self, prompt: str, answer: str = "") -> dict:
        rows = []
        if answer:
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
        rows.append({"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt}})
        t = self.work / f"t{len(list(self.work.glob('t*.jsonl')))}.jsonl"
        t.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return {"transcript_path": str(t), "tool_name": "Bash", "session_id": "test"}

    def run_list(self, lst: str, sha: str, prompt: str, answer: str = "") -> tuple[bool, str]:
        cmd = f"python {SCRIPT.as_posix()} {lst} --sha {sha}"
        return hcg.approved_by_owner(cmd, self.event(prompt, answer))

    def last_record(self) -> dict:
        return json.loads(hcg.APPROVAL_LOG.read_text(encoding="utf-8").splitlines()[-1])

    def test_pasted_paths_approve_without_showing_the_list(self) -> None:
        lst, sha = self.write_list(self.plain, self.db)
        ok, why = self.run_list(lst, sha, f"удали\n{self.plain}\n{self.db}")
        self.assertTrue(ok, why)
        self.assertIs(self.last_record().get("owner_named"), True)

    def test_pasted_with_backslashes_and_the_word_on_the_first_line(self) -> None:
        lst, sha = self.write_list(self.plain)
        ok, why = self.run_list(lst, sha, f"удали {str(self.plain).replace('/', chr(92))}")
        self.assertTrue(ok, why)

    def test_folder_with_datasets_goes_whole_when_she_pastes_its_path(self) -> None:
        lst, sha = self.write_list(self.withdata)
        # owner 2026-11-08: her own pasted full path names the folder whole, datasets inside included
        ok, why = self.run_list(lst, sha, f"удали\n{self.withdata}", "Удаление — 1 путь")
        self.assertTrue(ok, why)
        ok, why = self.run_list(lst, sha, f"удали\n{self.withdata}",
                                "Удаление — 1 путь, внутри датасеты: lesson_dataset.csv")
        self.assertTrue(ok, why)
        ok, why = self.run_list(lst, sha, f"удали\n{self.withdata}",       # a sentence's closing dot after it
                                "Внутри датасеты: a.ipynb, lesson_dataset.csv.")
        self.assertTrue(ok, why)

    def test_refused(self) -> None:
        lst, sha = self.write_list(self.plain, self.db)
        self.assertFalse(self.run_list(lst, sha, f"удали\n{self.plain}")[0])                 # one not pasted
        self.assertFalse(self.run_list(lst, sha, f"не удаляй\n{self.plain}\n{self.db}")[0])  # negated
        self.assertFalse(self.run_list(lst, sha, f"удали?\n{self.plain}\n{self.db}")[0])     # a question
        longer = Path(str(self.db) + " old")
        lst2, sha2 = self.write_list(self.db)
        self.assertFalse(self.run_list(lst2, sha2, f"удали\n{longer}")[0])                   # a prefix only
        self.assertFalse(self.run_list(lst, sha, "удали всё по списку")[0])                   # no paths

    def test_bare_yes_keeps_the_old_rules(self) -> None:
        lst, sha = self.write_list(self.plain)
        shown = f"deletion-list: {lst} sha256:{sha}"
        ok, why = self.run_list(lst, sha, "да", shown)
        self.assertTrue(ok, why)
        self.assertNotIn("owner_named", self.last_record())
        self.assertFalse(self.run_list(lst, sha, "да")[0])                                   # not shown
        lst2, sha2 = self.write_list(self.db)
        self.assertFalse(self.run_list(lst2, sha2, "удаляй", f"deletion-list: {lst2} sha256:{sha2}")[0])


class ScriptHonoursOwnerNamed(unittest.TestCase):
    """The script refuses the irreplaceable unless the guard's record says the owner pasted it."""

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="hcg-owner-home-"))
        self.lists = self.home / ".claude" / "state" / "deletion-lists"
        self.lists.mkdir(parents=True)
        (self.home / ".claude" / "logs").mkdir(parents=True)
        self.db = self.home / "work" / "store.db"
        self.db.parent.mkdir()
        self.db.write_bytes(b"x")

    def tearDown(self) -> None:
        shutil.rmtree(self.home, ignore_errors=True)

    def run_script(self, owner_named: bool) -> int:
        lst = self.lists / "x.txt"
        lst.write_text(f"{self.db}\n", encoding="utf-8")
        sha = hashlib.sha256(lst.read_bytes()).hexdigest()
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
               "list": Path(str(lst).replace("\\", "/")).as_posix().lower(), "sha": sha[:16]}
        if owner_named:
            rec["owner_named"] = True
        with (self.home / ".claude" / "logs" / "deletion-approvals.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        env = {**os.environ, "USERPROFILE": str(self.home), "HOME": str(self.home)}
        return subprocess.run([sys.executable, str(SCRIPT), str(lst), "--sha", sha[:16]], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True).returncode

    def test_refused_without_the_mark(self) -> None:
        self.assertEqual(self.run_script(owner_named=False), 1)
        self.assertTrue(self.db.exists())

    def test_deleted_with_the_mark(self) -> None:
        self.assertEqual(self.run_script(owner_named=True), 0)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
