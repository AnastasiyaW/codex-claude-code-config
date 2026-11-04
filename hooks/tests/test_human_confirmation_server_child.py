"""Owner 2026-11-04 («поправь хук»): after she named two folders by full path with «удали», both deletes
were refused. One sits one level below / on a server ("root-level path"); the other lives on a
password-only server whose commands go through a local wrapper script, which the guard did not read
as ssh. Both now pass when she names the full path herself; / itself, the folders in it, OS folders,
unnamed paths, a bare yes and a wrapper not listed in the local config stay refused.
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
SRV, INC = "/srv/old-stand", "/root/stand-incoming"
WRAP = "python D:/work/remote/run.py"


class ServerChild(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-server-child-"))
        hcg.APPROVAL_LOG = self.work / "audit.jsonl"
        self.saved = hcg.SSH_WRAPPER_SCRIPTS
        hcg.SSH_WRAPPER_SCRIPTS = frozenset({"/remote/run.py"})

    def tearDown(self) -> None:
        hcg.SSH_WRAPPER_SCRIPTS = self.saved
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

    def test_named_server_child(self) -> None:
        self.assertTrue(self.ok(f"ssh srv1 'sudo -n {RM} {SRV}'", f"удали {SRV}\n{INC}"))
        self.assertTrue(self.ok(f"ssh h '{RM} /opt/old-stand'", "удали /opt/old-stand"))

    def test_server_child_refused(self) -> None:
        self.assertFalse(self.ok(f"ssh h '{RM} /srv/other'", f"удали {SRV}"))              # not named
        self.assertFalse(self.ok(f"ssh h '{RM} /srv'", "удали /srv"))                      # folder in /
        self.assertFalse(self.ok(f"ssh h '{RM} /etc/nginx'", "удали /etc/nginx"))          # OS folder
        self.assertFalse(self.ok(f"ssh h '{RM} /var/lib'", "удали /var/lib"))
        self.assertFalse(self.ok(f"{RM} {SRV}", f"удали {SRV}"))                           # local, not ssh
        self.assertFalse(self.ok(f"ssh h '{RM} {SRV}'", "да", f"Удалю {SRV}, ответь «да»"))  # bare yes

    def test_wrapper_cmd_is_ssh(self) -> None:
        self.assertTrue(self.ok(f"{WRAP} --cmd '{RM} {INC}'", f"удали {SRV}\n{INC}"))
        self.assertFalse(self.ok(f"{WRAP} --cmd '{RM} /root/other'", f"удали {INC}"))
        self.assertFalse(self.ok(f"{WRAP} --cmd '{RM} {INC}' extra", f"удали {INC}"))      # odd shape
        self.assertFalse(self.ok(f"{WRAP} --cmd '{RM} {INC}'", "покажи что там"))           # no request
        self.assertEqual(hcg.remote_command(f"{WRAP} --cmd 'ls /'"), "ls /")
        self.assertIsNone(hcg.remote_command("python other/run2.py --cmd 'ls /'"))         # not listed
        hcg.SSH_WRAPPER_SCRIPTS = frozenset()
        self.assertIsNone(hcg.remote_command(f"{WRAP} --cmd 'ls /'"))                       # no config


if __name__ == "__main__":
    unittest.main()
