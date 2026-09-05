#!/usr/bin/env python3
"""Unit tests for the optional RTK integration layer."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import rtk_integration


class RtkIntegrationTests(unittest.TestCase):
    def test_pinned_metadata_is_explicit(self) -> None:
        self.assertEqual(rtk_integration.PINNED_VERSION, "0.43.0")
        self.assertEqual(len(rtk_integration.WINDOWS_ASSET_SHA256), 64)
        self.assertEqual(len(rtk_integration.PINNED_BINARY_SHA256), 64)
        self.assertIn("x86_64-pc-windows-msvc.zip", rtk_integration.WINDOWS_ASSET)

    def test_sha256_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload"
            path.write_bytes(b"rtk-proof")
            self.assertEqual(
                rtk_integration.sha256_file(path),
                hashlib.sha256(b"rtk-proof").hexdigest(),
            )

    def test_verify_archive_uses_asset_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rtk.zip"
            path.write_bytes(b"release-archive")
            original = rtk_integration.WINDOWS_ASSET_SHA256
            try:
                rtk_integration.WINDOWS_ASSET_SHA256 = hashlib.sha256(
                    b"release-archive"
                ).hexdigest()
                result = rtk_integration.verify_archive(path)
                self.assertEqual(result["sha256"], rtk_integration.WINDOWS_ASSET_SHA256)
            finally:
                rtk_integration.WINDOWS_ASSET_SHA256 = original

    def test_merge_hook_is_idempotent_and_matches_both_shell_tools(self) -> None:
        settings = {"hooks": {"PreToolUse": []}}
        binary = Path("C:/tools/rtk.exe")
        self.assertTrue(rtk_integration.merge_hook(settings, binary))
        self.assertFalse(rtk_integration.merge_hook(settings, binary))
        entries = settings["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["matcher"], "Bash|PowerShell")
        self.assertIn("hook claude", entries[0]["hooks"][0]["command"])
        if rtk_integration.os.name == "nt":
            self.assertNotIn("\\\\", entries[0]["hooks"][0]["command"])

    def test_merge_hook_upgrades_the_legacy_backslash_command_in_place(self) -> None:
        settings = {"hooks": {"PreToolUse": [{
            "matcher": "Bash|PowerShell",
            "hooks": [{
                "type": "command",
                "command": r"C:\\legacy\\rtk.exe hook claude",
                "statusMessage": "old",
            }],
        }]}}

        self.assertTrue(rtk_integration.merge_hook(settings, Path("C:/tools/rtk.exe")))
        entries = settings["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1)
        command = entries[0]["hooks"][0]["command"]
        self.assertIn("c:/tools/rtk.exe", command.lower())
        self.assertEqual(entries[0]["hooks"][0]["statusMessage"], rtk_integration.HOOK_STATUS)

    def test_install_is_dry_run_by_default_and_writes_backup_when_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
            data = rtk_integration.load_json(settings_path)
            changed = rtk_integration.merge_hook(data, Path("C:/tools/rtk.exe"))
            self.assertTrue(changed)
            self.assertFalse(settings_path.with_suffix(".json.bak").exists())
            rtk_integration.write_json_atomic(settings_path, data)
            self.assertTrue(settings_path.with_suffix(".json.bak").exists())
            reread = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(len(reread["hooks"]["PreToolUse"]), 1)


if __name__ == "__main__":
    unittest.main()
