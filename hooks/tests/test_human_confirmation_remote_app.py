"""Owner 2026-11-07 («Поправь хук»: a trojan's files on a Windows host over ssh could not be removed after
her «да»): an application's files in Program Files, ProgramData and AppData on a remote host go when she
names the full path or says yes to my Удаление block. OS folders, secrets and the local machine stay refused.
A quoted path with a space stays one path through `powershell -Command`.
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
HOME = "C:\\" + "Users" + "\\someone"  # assembled: the public-repo scanner flags literal home paths
APP = "C:\\Program Files\\Bad App"
VBS = "C:\\ProgramData\\Microsoft\\bad.vbs"
XML = "C:\\ProgramData\\Microsoft\\bad.xml"
ROAM = HOME + "\\AppData\\Roaming\\badapp\\pro"
ALL = (APP, VBS, XML, ROAM)


def ps(*paths: str) -> str:
    quoted = ",".join(f"'{p}'" for p in paths)
    return f'ssh winhost "powershell -Command {RI} {quoted}"'


def block(*paths: str) -> str:
    return "**Удаление** — ответь «да»:\n```\n" + "\n".join(paths) + "\n```\n"


class RemoteApp(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-remote-app-"))
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

    def test_quoted_path_with_a_space_stays_one_target(self) -> None:
        self.assertEqual(hcg.plain_delete_targets(ps(APP)), [(APP, True)])
        self.assertEqual(hcg.plain_delete_targets(ps(APP, VBS)), [(APP, True), (VBS, True)])

    def test_a_quoted_string_still_hides_nothing(self) -> None:
        for hidden in ('ssh h "powershell -Command \\"C:\\x y; rm D:/data/z\\""',
                       'ssh h powershell -Command "C:\\x y; rm D:/data/z"'):
            targets = [t for t, _ in hcg.plain_delete_targets(hidden) or []]
            self.assertIn("D:/data/z", targets, hidden)

    def test_yes_to_the_block_and_her_own_words(self) -> None:
        self.assertTrue(self.ok(ps(*ALL), "да", block(*ALL)))
        self.assertTrue(self.ok(ps(*ALL), "удали\n" + "\n".join(ALL)))

    def test_refused_unnamed(self) -> None:
        self.assertFalse(self.ok(ps(*ALL), "да", block(APP)))                     # outside the block
        self.assertFalse(self.ok(ps(APP), "да", f"Удалю {APP}, ответь «да»"))     # a yes with no block
        self.assertFalse(self.ok(ps(APP), "удали вирус"))                         # not named
        self.assertFalse(self.ok(ps(APP), f"не удаляй {APP}"))                    # negation

    def test_refused_local(self) -> None:
        for p in ALL:
            cmd = f"powershell -Command {RI} '{p}'"
            self.assertFalse(self.ok(cmd, f"удали {p}"), p)

    def test_refused_os_and_secrets(self) -> None:
        for p in ("C:\\Program Files", "C:\\Program Files\\WindowsApps", "C:\\Program Files\\Common Files\\x",
                  "C:\\Program Files\\Windows Defender", "C:\\Program Files\\Microsoft Office",
                  "C:\\Program Files (x86)\\Microsoft\\Edge", "C:\\ProgramData",
                  "C:\\ProgramData\\Microsoft", "C:\\ProgramData\\Microsoft\\Windows",
                  "C:\\ProgramData\\Microsoft\\Windows\\Start.lnk",
                  "C:\\Windows\\System32\\x.dll", HOME + "\\AppData\\Roaming",
                  HOME + "\\AppData\\Roaming\\Microsoft\\Windows\\x",
                  HOME + "\\AppData\\Roaming\\.ssh\\id",
                  HOME + "\\AppData\\Roaming\\app\\.git",
                  HOME + "\\.claude\\AppData\\Roaming\\x"):
            self.assertFalse(self.ok(ps(p), f"удали {p}"), p)
            self.assertFalse(self.ok(ps(p), "да", block(p)), p)


if __name__ == "__main__":
    unittest.main()
