"""Owner 2026-11-01 («поправь хук, он должен удалять без танцев с бубном»): she pasted the full paths
of VM folders like E:\\VMs\\old-vm-win32 with «удали», and the delete over ssh was refused as a
"root-level path". An entry inside a folder that sits directly in a drive root now goes when the owner
names its full path herself; the drive root, the folders directly in it and anything she did not name
stay refused.
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
PASTED = f"удали \n\n<pasted_content id=\"f54e\">\n{A}\n{B}\n</pasted_content id=\"f54e\">"


def ssh(*paths: str) -> str:
    quoted = ",".join(f"'{p}'" for p in paths)
    return f'ssh winhost "powershell -Command {RM} -Recurse -Force {quoted}"'


class DriveChild(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-drive-child-"))
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

    def test_owner_pasted_full_paths(self) -> None:
        self.assertTrue(self.ok(ssh(A, B), PASTED))

    def test_bare_yes_to_my_full_path_list(self) -> None:
        self.assertTrue(self.ok(ssh(A, B), "да", f"Удалю эти пути:\n{A}\n{B}\nОтветь «да»."))
        self.assertFalse(self.ok(ssh(A, B), "да", f"Удалю {A}, подтверди"))       # B not in my list

    def test_still_refused(self) -> None:
        # owner 2026-11-05: a folder directly in a remote drive root goes when she names it (REMOTE_DRIVE_ROOT)
        self.assertTrue(self.ok(ssh(r"E:\VMs"), r"удали E:\VMs"))
        self.assertFalse(self.ok(ssh(r"E:\VMs"), r"удали E:\VMs2"))               # a different name
        self.assertFalse(self.ok(ssh("E:\\"), "удали E:\\"))                        # the drive root
        self.assertFalse(self.ok(ssh(A), "удали old-vm-win32"))               # name without path
        self.assertFalse(self.ok(ssh(A), "да", "Удалю 20 путей, подтверди"))       # my answer named no path
        self.assertFalse(self.ok(ssh(A, r"E:\VMs\keep-me"), PASTED))               # an unnamed extra
        self.assertFalse(self.ok(ssh(A), f"не удаляй {A}"))                        # negated

    def test_hard_limit_reason(self) -> None:
        self.assertEqual(hcg.target_hard_limit(A, True), hcg.DRIVE_CHILD)
        self.assertEqual(hcg.target_hard_limit(r"E:\VMs", True), hcg.LOCAL_DRIVE_ROOT)  # named by her only
        self.assertEqual(hcg.target_hard_limit("C:\\" + "Users" + "\\someone", True), "root-level path")


if __name__ == "__main__":
    unittest.main()
