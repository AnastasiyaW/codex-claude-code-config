"""Temp is judged by location (owner 2026-11-07); only links can still reach data outside temp."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "human-confirmation-guard.py"


def load():
    spec = importlib.util.spec_from_file_location("hcg_temp", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def junction(link, target):
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


class TempLocation(unittest.TestCase):
    def setUp(self):
        self.g = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.addCleanup(self.tmp.cleanup)

    def test_database_inside_temp_is_scratch(self):
        d = self.root / "wpa-sqlite-x"
        d.mkdir()
        (d / "work.db").write_bytes(b"SQLite format 3\x00" + b"\0" * 16)
        (d / "plain.bin").write_bytes(b"SQLite format 3\x00" + b"\0" * 16)
        self.assertTrue(self.g.is_target_safe(str(d)))
        self.assertTrue(self.g.is_target_safe(str(d / "work.db")))

    def test_database_outside_temp_stays_refused(self):
        outside = (Path.home() / "Desktop" / "project" / "work.db").as_posix()
        self.assertFalse(self.g.is_target_safe(outside))
        self.assertFalse(self.g.temp_location_ok(outside))

    @unittest.skipUnless(os.name == "nt", "junctions are a Windows feature")
    def test_shell_delete_still_refuses_links(self):
        outside = tempfile.mkdtemp(dir=Path.home())
        self.addCleanup(os.rmdir, outside)
        d = self.root / "with-link"
        d.mkdir()
        junction(d / "out", outside)
        self.addCleanup(os.rmdir, d / "out")
        self.assertFalse(self.g.is_target_safe(str(d)))
        self.assertTrue(self.g.temp_location_ok(str(d)))

    @unittest.skipUnless(os.name == "nt", "junctions are a Windows feature")
    def test_sweep_location_refuses_path_through_a_junction_out_of_temp(self):
        outside = tempfile.mkdtemp(dir=Path.home())
        self.addCleanup(os.rmdir, outside)
        link = self.root / "lead-out"
        junction(link, outside)
        self.addCleanup(os.rmdir, link)
        self.assertFalse(self.g.temp_location_ok(str(link / "victim")))

    def test_location_refuses_tricks(self):
        for bad in (f"{self.root}/../x", f"{self.root}/a,b", f"{self.root}/$X", f"{self.root}/x. "):
            self.assertFalse(self.g.temp_location_ok(bad), bad)
        self.assertFalse(self.g.temp_location_ok((Path.home() / "Desktop" / "x").as_posix()))


if __name__ == "__main__":
    sys.exit(unittest.main())
