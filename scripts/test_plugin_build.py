#!/usr/bin/env python3
"""Tests for plugin_build.py and the plugin-rules-context hook."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("plugin_build", REPO / "scripts" / "plugin_build.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PluginBuildTests(unittest.TestCase):
    def test_committed_hooks_json_is_current(self) -> None:
        self.assertEqual(MODULE.render(), MODULE.TARGET.read_text(encoding="utf-8"))

    def test_every_category_listed(self) -> None:
        self.assertEqual(MODULE.unlisted_skill_categories(), [])

    def test_unlisted_category_is_reported(self) -> None:
        manifest = json.loads(MODULE.MANIFEST.read_text(encoding="utf-8"))
        manifest["skills"].remove("./skills/ios/")
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "plugin.json"
            fake.write_text(json.dumps(manifest), encoding="utf-8")
            original = MODULE.MANIFEST
            MODULE.MANIFEST = fake
            try:
                self.assertEqual(MODULE.unlisted_skill_categories(), ["skills/ios"])
            finally:
                MODULE.MANIFEST = original

    def test_manifest_has_no_version(self) -> None:
        self.assertNotIn("version", json.loads(MODULE.MANIFEST.read_text(encoding="utf-8")))

    def test_check_fails_on_manifest_version(self) -> None:
        manifest = json.loads(MODULE.MANIFEST.read_text(encoding="utf-8"))
        manifest["version"] = "1.0.0"
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "plugin.json"
            fake.write_text(json.dumps(manifest), encoding="utf-8")
            original = MODULE.MANIFEST
            MODULE.MANIFEST = fake
            try:
                self.assertEqual(MODULE.main(["--check"]), 1)
            finally:
                MODULE.MANIFEST = original

    def test_no_user_path_in_hooks_json(self) -> None:
        text = MODULE.TARGET.read_text(encoding="utf-8")
        self.assertNotIn("Users", text)
        for group in json.loads(text)["hooks"].values():
            for entry in group:
                for hook in entry["hooks"]:
                    self.assertTrue(hook["args"][0].startswith("${CLAUDE_PLUGIN_ROOT}/hooks/"))
                    self.assertTrue((REPO / "hooks" / hook["args"][0].rsplit("/", 1)[1]).is_file())

    def test_plugin_extras_registered_with_extras_event(self) -> None:
        hooks = json.loads(MODULE.TARGET.read_text(encoding="utf-8"))["hooks"]
        for script in MODULE.PLUGIN_EXTRAS:
            groups = [g for g in hooks["PreToolUse"] if any(h["args"][0].endswith("/" + script) for h in g["hooks"])]
            self.assertEqual([g.get("matcher") for g in groups], ["Bash|PowerShell"], script)

    def test_token_savers_registered(self) -> None:
        hooks = json.loads(MODULE.TARGET.read_text(encoding="utf-8"))["hooks"]

        def matchers(event: str, script: str) -> list:
            return [g.get("matcher") for g in hooks[event] if any(h["args"][0].endswith("/" + script) for h in g["hooks"])]

        self.assertEqual(matchers("SessionStart", "benjamin-plus-inject.py"), ["startup|resume|clear|compact"])
        self.assertEqual(matchers("PreToolUse", "rtk-plugin-hook.py"), ["Bash|PowerShell"])
        self.assertTrue((REPO / "references" / "benjamin-plus" / "injected-instruction.md").is_file())

    def test_rtk_hook_self_test(self) -> None:
        result = subprocess.run([sys.executable, str(REPO / "hooks" / "rtk-plugin-hook.py"), "--self-test"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_plugin_extra_is_refused(self) -> None:
        original = MODULE.PLUGIN_EXTRAS
        MODULE.PLUGIN_EXTRAS = original + ["no-such-hook.py"]
        try:
            with self.assertRaises(SystemExit):
                MODULE.selection()
        finally:
            MODULE.PLUGIN_EXTRAS = original

    def test_rules_context_self_test(self) -> None:
        result = subprocess.run([sys.executable, str(REPO / "hooks" / "plugin-rules-context.py"), "--self-test"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
