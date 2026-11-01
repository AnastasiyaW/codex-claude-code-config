"""Owner 2026-11-01 («поправь хук»): the course layout by topic needs folder renames, which the guard
read as deletes. A shown relocate list approved by her bare yes or «переноси» now runs through
scripts/relocate_from_list.py: same volume only, never over an existing target, delete hard limits
on both ends except a folder two levels below a drive root.
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
SCRIPT = _HOOKS.parent / "scripts" / "relocate_from_list.py"


class RelocateApproval(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-relocate-"))
        self.lists = self.work / "lists"
        self.lists.mkdir()
        hcg.RELOCATE_LIST_DIR = self.lists
        hcg.APPROVAL_LOG = self.work / "audit.jsonl"
        self.src = self.work / "course [SW.BAND] (2023)"
        self.src.mkdir()
        (self.src / "lesson.mp4").write_bytes(b"x")
        self.dst = self.work / "01 Копирайтинг" / "course (2023)"

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def write_list(self, *pairs: tuple[Path | str, Path | str]) -> tuple[str, str]:
        f = self.lists / f"l{len(list(self.lists.iterdir()))}.txt"
        f.write_text("".join(f"{s} => {d}\n" for s, d in pairs), encoding="utf-8")
        return f.as_posix(), hashlib.sha256(f.read_bytes()).hexdigest()[:16]

    def run_list(self, lst: str, sha: str, prompt: str, answer: str) -> tuple[bool, str]:
        rows = [{"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}},
                {"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt}}]
        t = self.work / f"t{len(list(self.work.glob('t*.jsonl')))}.jsonl"
        t.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        cmd = f"python {SCRIPT.as_posix()} {lst} --sha {sha}"
        self.assertFalse(hcg.decide(cmd)[0])  # never passes without the owner check
        return hcg.approved_by_owner(cmd, {"transcript_path": str(t), "tool_name": "Bash", "session_id": "t"})

    def test_shown_list_and_yes_or_move_word(self) -> None:
        lst, sha = self.write_list((self.src, self.dst))
        shown = f"**Перенос** — 1 папка\nrelocate-list: {lst} sha256:{sha}"
        for prompt in ("да", "переноси", "да, переноси"):
            ok, why = self.run_list(lst, sha, prompt, shown)
            self.assertTrue(ok, f"{prompt}: {why}")
        rec = json.loads(hcg.APPROVAL_LOG.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["action"], "relocate")

    def test_refused(self) -> None:
        lst, sha = self.write_list((self.src, self.dst))
        shown = f"relocate-list: {lst} sha256:{sha}"
        self.assertFalse(self.run_list(lst, sha, "да", "вот план")[0])           # not shown
        self.assertFalse(self.run_list(lst, sha, "не переноси", shown)[0])       # negated
        self.assertFalse(self.run_list(lst, sha, "переносить?", shown)[0])       # a question
        self.assertFalse(self.run_list(lst, sha, "удали", shown)[0])            # not a go for a rename
        drive = str(self.work)[0]
        for bad in ((self.src, ("C" if drive.upper() != "C" else "E") + str(self.dst)[1:]),  # other volume
                    (f"{drive}:/somefolder", self.dst),                                 # folder in a drive root
                    (self.src, Path.home() / ".claude" / "x"),                          # protected target
                    (self.src, self.src / "inner")):                                    # into itself
            l2, s2 = self.write_list(bad)
            self.assertFalse(self.run_list(l2, s2, "да", f"relocate-list: {l2} sha256:{s2}")[0], bad)

    def test_changed_list(self) -> None:
        lst, sha = self.write_list((self.src, self.dst))
        shown = f"relocate-list: {lst} sha256:{sha}"
        Path(lst).write_text(f"{self.src} => {self.work / 'other'}\n", encoding="utf-8")
        self.assertFalse(self.run_list(lst, sha, "да", shown)[0])


class ScriptNeedsTheRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="hcg-relocate-home-"))
        self.lists = self.home / ".claude" / "state" / "relocate-lists"
        self.lists.mkdir(parents=True)
        (self.home / ".claude" / "logs").mkdir(parents=True)
        self.src = self.home / "work" / "course"
        self.src.mkdir(parents=True)
        (self.src / "a.mp4").write_bytes(b"x")
        (self.src / "b.srt").write_bytes(b"y")
        self.dst = self.home / "work" / "topic" / "course"

    def tearDown(self) -> None:
        shutil.rmtree(self.home, ignore_errors=True)

    def run_script(self, approve: bool) -> int:
        lst = self.lists / "x.txt"
        lst.write_text(f"{self.src} => {self.dst}\n", encoding="utf-8")
        sha = hashlib.sha256(lst.read_bytes()).hexdigest()
        if approve:
            rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "action": "relocate",
                   "list": Path(str(lst).replace("\\", "/")).as_posix().lower(), "sha": sha[:16]}
            with (self.home / ".claude" / "logs" / "deletion-approvals.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        env = {**os.environ, "USERPROFILE": str(self.home), "HOME": str(self.home)}
        return subprocess.run([sys.executable, str(SCRIPT), str(lst), "--sha", sha[:16]], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True).returncode

    def test_refused_without_the_record(self) -> None:
        self.assertEqual(self.run_script(approve=False), 1)
        self.assertTrue(self.src.exists())

    def test_moved_with_the_record(self) -> None:
        self.assertEqual(self.run_script(approve=True), 0)
        self.assertFalse(self.src.exists())
        self.assertEqual(sorted(p.name for p in self.dst.iterdir()), ["a.mp4", "b.srt"])

    def test_never_over_an_existing_target(self) -> None:
        self.dst.mkdir(parents=True)
        self.assertEqual(self.run_script(approve=True), 1)
        self.assertTrue(self.src.exists())


if __name__ == "__main__":
    unittest.main()
