"""Owner 2026-11-05 («поправь хук что бы он не мешал работать»): her «удали» with ten pasted
D:\\<folder> paths was refused as "root-level path". A folder directly in a local Windows drive root
now goes when she names its full path herself, in a plain delete or a pasted deletion list. The drive
root itself, OS folders, unnamed paths, a bare yes and a negation stay refused.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

_HOOKS = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("hcg", _HOOKS / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)
SCRIPT = _HOOKS.parent / "scripts" / "delete_from_list.py"

RI = "Remove-" + "Item -Recurse -Force"
A, B = "D:\\hcg-test-absent-a", "D:\\hcg-test-absent-b"


def ps(paths: str) -> str:
    return f"powershell -Command {RI} {paths}"


class LocalDriveRoot(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-local-root-"))
        self.lists = self.work / "lists"
        self.lists.mkdir()
        hcg.DELETION_LIST_DIR = self.lists
        hcg.APPROVAL_LOG = self.work / "audit.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def event(self, prompt: str, answer: str = "") -> dict:
        rows = []
        if answer:
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
        rows.append({"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt}})
        path = self.work / f"t{len(list(self.work.glob('t*.jsonl')))}.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return {"transcript_path": str(path), "tool_name": "Bash", "session_id": "test"}

    def ok(self, cmd: str, prompt: str, answer: str = "") -> bool:
        return hcg.approved_by_owner(cmd, self.event(prompt, answer))[0]

    def run_list(self, prompt: str, *paths: str, answer: str = "") -> bool:
        f = self.lists / f"l{len(list(self.lists.iterdir()))}.txt"
        f.write_text("\n".join(paths) + "\n", encoding="utf-8")
        sha = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        return self.ok(f"python {SCRIPT.as_posix()} {f.as_posix()} --sha {sha}", prompt, answer)

    def test_reason_is_its_own(self) -> None:
        self.assertEqual(hcg.target_hard_limit("D:/hcg-test-absent-a", True), hcg.LOCAL_DRIVE_ROOT)
        self.assertEqual(hcg.target_hard_limit("D:/", True), "root-level path")
        self.assertNotEqual(hcg.target_hard_limit("C:/Windows", True), hcg.LOCAL_DRIVE_ROOT)

    def test_named_folders_go(self) -> None:
        self.assertTrue(self.ok(ps(f"'{A}'"), f"удали {A}"))
        self.assertTrue(self.run_list(f"удали\n{A}\n{B}", A, B))  # the pasted list that was refused
        record = json.loads(hcg.APPROVAL_LOG.read_text(encoding="utf-8").splitlines()[-1])
        self.assertTrue(record.get("owner_named"))
        self.assertEqual(record.get("action"), "drive-root-folder")

    def test_refused(self) -> None:
        self.assertFalse(self.run_list(f"удали\n{A}", A, B))                          # B not pasted
        self.assertFalse(self.ok(ps(f"'{A}'"), "да", f"**Удаление** — 1 путь:\n```\n{A}\n```"))  # bare yes
        self.assertFalse(self.ok(ps(f"'{A}'"), f"не удаляй {A}"))                    # negation
        self.assertFalse(self.ok(ps(f"'{A}'"), "удали старые папки"))                 # not named
        self.assertFalse(self.ok(ps("'D:\\'"), "удали D:\\"))                          # the drive root
        self.assertFalse(self.ok(ps("'C:\\Windows'"), "удали C:\\Windows"))            # OS folders
        self.assertFalse(self.ok(ps("'C:\\Users'"), "удали C:\\Users"))
        self.assertFalse(self.ok(ps("'C:\\ProgramData'"), "удали C:\\ProgramData"))
        self.assertFalse(self.ok(ps("'D:\\$RECYCLE.BIN'"), "удали D:\\$RECYCLE.BIN"))


if __name__ == "__main__":
    unittest.main()
