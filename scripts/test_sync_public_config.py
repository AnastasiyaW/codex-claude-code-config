#!/usr/bin/env python3
"""Focused privacy-scan regression checks for sync_public_config.py."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("sync_public_config.py")
SPEC = importlib.util.spec_from_file_location("sync_public_config", SCRIPT)
assert SPEC and SPEC.loader
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


class SyncPublicConfigTests(unittest.TestCase):
    def run_repo_scan(self, root: Path, config: dict, files: list[Path]) -> tuple[int, str]:
        manifest = root / "sync-manifest.json"
        manifest.write_text(json.dumps(config), encoding="utf-8")
        output = io.StringIO()
        with (
            mock.patch.object(SYNC, "REPO_ROOT", root),
            mock.patch.object(SYNC, "MANIFEST", manifest),
            mock.patch.object(SYNC, "iter_indexed_files", return_value=iter(files)),
            mock.patch.object(sys, "argv", ["sync_public_config.py", "--scan-repo", "--strict"]),
            contextlib.redirect_stdout(output),
        ):
            code = SYNC.main()
        return code, output.getvalue()

    def test_repo_scan_exempts_only_manifest_listed_third_party_asset(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            font_data = root / "vendor" / "fonts.csv"
            source = root / "hooks" / "guard.py"
            font_data.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            font_data.write_text("private-marker", encoding="utf-8")
            source.write_text("private-marker", encoding="utf-8")
            config = {
                "active_root": "unused",
                "mappings": [],
                "privacy_markers": ["private-marker"],
                "privacy_scan_exempt_paths": ["vendor/fonts.csv"],
            }
            code, output = self.run_repo_scan(root, config, [font_data, source])
            self.assertEqual(code, 1)
            self.assertIn("EXEMPT vendor/fonts.csv", output)
            self.assertIn("MARKER hooks/guard.py", output)

    def test_repo_scan_rejects_malformed_exemption_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = {
                "active_root": "unused",
                "mappings": [],
                "privacy_markers": ["private-marker"],
                "privacy_scan_exempt_paths": ["../vendor/fonts.csv"],
            }
            code, output = self.run_repo_scan(root, config, [])
            self.assertEqual(code, 2)
            self.assertIn("ERROR", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
