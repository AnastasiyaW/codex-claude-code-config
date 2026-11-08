"""Owner 2026-10-31: she named the full paths of five unused browser profiles of one of our programs and
every delete was refused: naming a folder did not name the browser databases inside it (review R8),
and a profile with more than 50 of them could not be confirmed at all. Parents of such regenerable
profiles are listed in a private file; her naming the full path of one profile now covers its
databases. Anything else keeps R8.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

SQLITE = b"SQLite format 3\x00" + b"\x00" * 84


def _profile(root: Path, dbs: int) -> Path:
    (root / "Default").mkdir(parents=True)
    for i in range(dbs):
        (root / "Default" / f"db{i}").write_bytes(SQLITE)
    (root / "Default" / "Cookies").write_bytes(SQLITE)
    return root


class RegenerableProfile(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="hcg-wp-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        hcg.APPROVAL_LOG = self.work / "audit.jsonl"
        base = self.work / "Local" / "Vendor" / "Worker" / "profiles"
        roots = self.work / "roots.json"
        roots.write_text(json.dumps({"roots": [os.path.realpath(base)]}), encoding="utf-8")
        hcg.PROFILE_ROOTS_FILE = roots
        self.small = _profile(base / "p~2", 3)
        self.big = _profile(base / "p~3", 60)
        self.other = _profile(self.work / "SomeBrowser" / "profiles" / "p1", 3)
        self.junction = base / "p~j"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(self.junction), str(self.other)],
                           check=True, capture_output=True, stdin=subprocess.DEVNULL)
        else:
            self.junction.symlink_to(self.other)

    def event(self, prompt: str) -> dict:
        row = {"type": "user", "origin": {"kind": "human"}, "message": {"content": prompt}}
        path = self.work / f"t{len(list(self.work.iterdir()))}.jsonl"
        path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return {"transcript_path": str(path), "tool_name": "Bash", "session_id": "test"}

    def ok(self, cmd: str, prompt: str) -> bool:
        return hcg.approved_by_owner(cmd, self.event(prompt))[0]

    def test_owner_names_profiles_by_full_path(self) -> None:
        s, b = str(self.small), str(self.big)
        self.assertTrue(self.ok(f'rm -rf "{s}" "{b}"', f"удали {s} {b}"))

    def test_still_refused(self) -> None:
        s, o = str(self.small), str(self.other)
        self.assertFalse(self.ok(f'rm -rf "{s}"', "удали p~2…p~3"))                # not the full path
        self.assertFalse(self.ok(f'rm -rf "{s}"', f"не удаляй {s}"))              # negated
        self.assertFalse(self.ok(f'rm -rf "{o}"', "удали p1"))                    # not under a listed root
        # owner 2026-11-08: a folder whose full path she typed goes whole, databases inside included
        self.assertTrue(self.ok(f'rm -rf "{o}"', f"удали {o}"))
        self.assertFalse(hcg._worker_profile(str(self.junction)))                 # a junction to elsewhere
        parent = str(self.small.parent)
        self.assertFalse(self.ok(f'rm -rf "{parent}"', "удали p~2"))              # the listed root itself
        self.assertTrue(self.ok(f'rm -rf "{parent}"', f"удали {parent}"))         # ...unless she typed its path
        (self.small / "Default" / "orders.sql.gz").write_bytes(b"x")
        self.assertFalse(self.ok(f'rm -rf "{s}"', f"удали {s}"))                  # a dump is not browser data
        shallow = self.work / "shallow.json"
        drive = Path(os.path.realpath(self.work)).anchor
        shallow.write_text(json.dumps({"roots": [drive, str(Path.home()), str(self.work / "a" / "b" / "c" / "d" / "nope")]}),
                           encoding="utf-8")
        hcg.PROFILE_ROOTS_FILE = shallow
        self.assertEqual(hcg._profile_roots(), set())                             # unsafe or missing roots
        hcg.PROFILE_ROOTS_FILE = self.work / "missing.json"
        s = str(self.big)
        self.assertFalse(hcg._worker_profile(s))                                  # no private list
        self.assertFalse(self.ok(f'rm -rf "{s}"', "удали p~3"))                   # so only the full path names it


if __name__ == "__main__":
    unittest.main()
