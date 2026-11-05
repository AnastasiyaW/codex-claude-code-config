"""Owner 2026-11-05 (two folders she named in a Windows drive root on a host over ssh was refused as
"root-level path"): a folder directly in a Windows drive root on a remote host now goes when she names
its full path herself. The drive root itself, OS folders, unnamed paths, a bare yes and the same
command run locally stay refused.
"""
from __future__ import annotations

import importlib.util
import json
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

RI = "Remove-" + "Item -Recurse -Force"
A, B = "C:\\old-evals", "C:\\old-scrape"


def ps(paths: str) -> str:
    return f"ssh winhost \"powershell -Command {RI} {paths}\""


class RemoteDriveRoot(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-remote-root-"))
        hcg.APPROVAL_LOG = self.work / "audit.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def event(self, prompt: str, answer: str = "") -> dict:
        rows = []
        if answer:
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
        rows.append({"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt}})
        path = self.work / f"t{len(list(self.work.iterdir()))}.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return {"transcript_path": str(path), "tool_name": "Bash", "session_id": "test"}

    def ok(self, cmd: str, prompt: str, answer: str = "") -> bool:
        return hcg.approved_by_owner(cmd, self.event(prompt, answer))[0]

    def test_named_remote_root_folders(self) -> None:
        self.assertTrue(self.ok(ps(f"'{A}','{B}'"), f"удали\n{A}\n{B}"))
        self.assertTrue(self.ok(ps(f"'{A}'"), f"удали {A.lower()}"))          # Windows: case-insensitive

    def test_refused(self) -> None:
        self.assertFalse(self.ok(ps(f"'{A}','{B}'"), f"удали {A}"))              # B not named
        self.assertFalse(self.ok(ps("'C:\\'"), "удали C:\\"))                     # the drive root
        self.assertFalse(self.ok(ps("'C:\\Windows'"), "удали C:\\Windows"))       # OS folder
        self.assertFalse(self.ok(ps("'C:\\Users'"), "удали C:\\Users"))
        self.assertFalse(self.ok(ps("'C:\\Recovery'"), "удали C:\\Recovery"))
        self.assertFalse(self.ok(ps("'C:\\ProgramData'"), "удали C:\\ProgramData"))
        self.assertFalse(self.ok(f"powershell -Command {RI} '{A}'", f"удали {A}"))  # local, not ssh
        self.assertFalse(self.ok(ps(f"'{A}'"), "да", f"Удалю {A}, ответь «да»"))  # bare yes
        self.assertFalse(self.ok(ps(f"'{A}'"), f"не удаляй {A}"))                 # negation


if __name__ == "__main__":
    unittest.main()
