"""Owner 2026-11-01 («поправь хук: присылается список того, что будет удаляться, и я говорю да; нам
нужен единый формат оформления удаления»). One format: a line starting «Удаление» and a fenced block of
full paths. A bare yes to that answer approves exactly the listed paths, including entries in a
drive-root folder; a path outside the block, an unlisted extra and a drive root stay refused.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

RM = "Remove" + "-Item"
A, B = r"E:\VMs\old-vm-win32", r"E:\VMs\old-disk.vhdx"
FENCE = "`" * 3
ANSWER = f"Готово с проверкой.\n\n**Удаление** — 2 пути, ответь «да»:\n{FENCE}\n{A}\n{B}\n{FENCE}\n"


def ssh(*paths: str) -> str:
    quoted = ",".join(f"'{p}'" for p in paths)
    return f'ssh winhost "powershell -Command {RM} -Recurse -Force {quoted}"'


class DeleteBlock(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-delete-block-"))
        hcg.APPROVAL_LOG = self.work / "audit.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def ok(self, cmd: str, prompt: str, answer: str) -> bool:
        rows = [{"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}},
                {"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt}}]
        path = self.work / f"t{len(list(self.work.iterdir()))}.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return hcg.approved_by_owner(cmd, {"transcript_path": str(path), "tool_name": "Bash",
                                           "session_id": "test"})[0]

    def test_bare_yes_to_the_block(self) -> None:
        self.assertTrue(self.ok(ssh(A, B), "да", ANSWER))
        self.assertTrue(self.ok(ssh(A), "да, удаляй", ANSWER))

    def test_block_is_parsed(self) -> None:
        self.assertEqual(hcg.delete_block(ANSWER).split(), [A, B])
        self.assertIsNone(hcg.delete_block(f"Удалю {A}"))

    def test_still_refused(self) -> None:
        self.assertFalse(self.ok(ssh(A, r"E:\VMs\keep-me"), "да", ANSWER))            # unlisted extra
        outside = f"Не трогаю {r'E:\VMs\keep-me'}.\n" + ANSWER
        self.assertFalse(self.ok(ssh(r"E:\VMs\keep-me"), "да", outside))              # named outside the block
        root = f"**Удаление**:\n{FENCE}\nE:\\\n{FENCE}\n"
        self.assertFalse(self.ok(ssh("E:\\"), "да", root))                            # drive root
        self.assertFalse(self.ok(ssh(A), "нет", ANSWER))                               # not a yes


if __name__ == "__main__":
    unittest.main()
