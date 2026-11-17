"""Owner 2026-11-17 («удали эти 7 ссылок и остаток character-lora»): NTFS junctions on a Windows host can be
removed safely only by `cmd /c rmdir <junction>` (the link goes, the target stays). Windows PowerShell 5.1
Remove-Item without -Recurse throws NullReferenceException on a junction, and with -Recurse it empties the
target. The guard read `cmd /c ...` as "not a plain file delete", so the one safe form was refused. Now
`cmd /c` is unwrapped like `bash -c`, and the inner rmdir is judged by the usual rules.
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

J1 = "G:\\data4\\proj-lora\\runtime\\models\\org\\Model-A"
J2 = "G:\\data4\\proj-lora\\runtime\\models\\org\\Model-B"
RMDIR = "rm" + "dir"


def ssh(inner: str) -> str:
    return f'ssh winhost "{inner}"'


class CmdCRmdir(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-cmd-c-"))
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

    def test_unwraps_cmd_c(self) -> None:
        self.assertEqual(hcg.remote_command(f"cmd /c {RMDIR} {J1}"), f"{RMDIR} {J1}")
        self.assertEqual(hcg.remote_command(f"cmd.exe /d /c {RMDIR} {J1}"), f"{RMDIR} {J1}")
        self.assertEqual(hcg.remote_command(f'cmd /c "{RMDIR} {J1}"'), f"{RMDIR} {J1}")
        # only one balanced pair around the whole body is taken off
        self.assertEqual(hcg.remote_command(f'cmd /c "{RMDIR} {J1}'), f'"{RMDIR} {J1}')
        self.assertEqual(hcg.remote_command(f'cmd /c "{RMDIR}" "{J1}"'), f'"{RMDIR}" "{J1}"')
        self.assertEqual(hcg.remote_command('cmd /c "'), '"')
        self.assertEqual(hcg.plain_delete_targets(ssh(f"cmd /c {RMDIR} {J1}")), [(J1, True)])

    def test_junction_links_go_on_her_request(self) -> None:
        self.assertTrue(self.ok(ssh(f"cmd /c {RMDIR} {J1}"), "удали эти 7 ссылок и остаток proj-lora"))
        self.assertTrue(self.ok(ssh(f"cmd /c {RMDIR} {J1} && {RMDIR} {J2}"), "удали эти ссылки"))
        self.assertTrue(self.ok(ssh(f"cmd /c {RMDIR} {J1}"), f"удали {J1}"))

    def test_refused(self) -> None:
        self.assertFalse(self.ok(ssh(f"cmd /c {RMDIR} {J1}"), "продолжим"))                 # no delete request
        self.assertFalse(self.ok(ssh(f"cmd /c {RMDIR} /s /q {J1}"), "удали эти ссылки"))   # /s is read as a path
        self.assertFalse(self.ok(ssh(f"cmd /c {RMDIR} %TEMP%\\x"), "удали эти ссылки"))     # cmd variable
        self.assertFalse(self.ok(ssh(f"cmd /c {RMDIR} G:\\"), "удали G:\\"))               # drive root
        self.assertFalse(self.ok(ssh(f"cmd /c {RMDIR} G:\\data4"), "удали эти ссылки"))    # drive-root folder, unnamed
        self.assertFalse(self.ok(ssh(f"cmd /k {RMDIR} {J1}"), "удали эти ссылки"))         # /k is not unwrapped
        self.assertFalse(self.ok(f"cmd /c {RMDIR} C:\\Windows", "удали C:\\Windows"))      # local OS folder
        self.assertFalse(self.ok(ssh(f"cmd /c {RMDIR} {J1} ^& {RMDIR} {J2}"), "удали эти ссылки"))  # cmd escape


if __name__ == "__main__":
    unittest.main()
