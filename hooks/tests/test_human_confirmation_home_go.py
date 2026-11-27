"""Owner 2026-11-27 («поправь хук, чтобы go удалялась»): she pasted the home go folder among 96
folders with «удали» and only that one was refused as a standard home folder. ~/go is the Go toolchain's
GOPATH (module cache, build output), restored by `go mod download`, not a user-documents folder. It now
follows the ordinary home-child rules: named by her on a server or locally. Documents-like folders,
hidden folders, the home itself and a bare yes without the path stay refused.
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

RM = "r" + "m -rf"
H = "/" + "home/" + "fixtureuser"
GO = H + "/go"


class HomeGo(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-home-go-"))
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

    def test_named_go_on_server_passes(self) -> None:
        self.assertTrue(self.ok(f"ssh srv '{RM} -- {GO}'", f"удали\n{GO}"))
        self.assertTrue(self.ok(f"ssh h 'sudo -n {RM} -- {GO}'", f"удали {GO}"))

    def test_other_home_limits_stay(self) -> None:
        self.assertFalse(self.ok(f"ssh h '{RM} -- {H}/Documents'", f"удали {H}/Documents"))
        self.assertFalse(self.ok(f"ssh h '{RM} -- {H}/.ssh'", f"удали {H}/.ssh"))
        self.assertFalse(self.ok(f"ssh h '{RM} -- {H}'", f"удали {H}"))
        self.assertFalse(self.ok(f"ssh h '{RM} -- {GO}'", f"удали {H}/other"))   # not named
        self.assertFalse(self.ok(f"ssh h '{RM} -- {GO}'", "да", "Удалю старые папки, ответь «да»"))  # no path


if __name__ == "__main__":
    unittest.main()
