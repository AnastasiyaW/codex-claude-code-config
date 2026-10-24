#!/usr/bin/env python3
"""Focused regression checks for the terminology-drift checker."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("term_drift_check.py")
SPEC = importlib.util.spec_from_file_location("term_drift_check", SCRIPT)
assert SPEC and SPEC.loader
DRIFT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIFT  # dataclasses resolve annotations through sys.modules
SPEC.loader.exec_module(DRIFT)


def run(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, text=True,
                          capture_output=True, encoding="utf-8")


class TermDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.glossary = Path(self.tmp.name) / "glossary.json"
        self.glossary.write_text(json.dumps(
            {"terms": {"воркер": ["обработчик*"]}, "max_words": 10}, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_self_test_passes(self) -> None:
        self.assertEqual(run("--self-test").returncode, 0)

    def test_drift_is_reported_with_line_and_exit_1(self) -> None:
        result = run("--glossary", str(self.glossary), stdin="Всё ок.\nПерезапусти обработчиков.\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:2: [term-drift]", result.stdout)

    def test_clean_text_exits_0(self) -> None:
        self.assertEqual(run("--glossary", str(self.glossary), stdin="Перезапусти воркер.").returncode, 0)

    def test_missing_glossary_and_empty_input_are_not_green(self) -> None:
        self.assertEqual(run(stdin="text").returncode, 2)
        self.assertEqual(run("--glossary", str(self.glossary), stdin="  \n").returncode, 2)
        self.glossary.write_text('{"terms": {}}', encoding="utf-8")
        self.assertEqual(run("--glossary", str(self.glossary), stdin="text").returncode, 2)

    def test_non_utf8_stdin_is_not_green(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT), "--glossary", str(self.glossary)],
                                input="Перезапусти обработчика.".encode("cp1251"), capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_unclosed_fence_is_not_green(self) -> None:
        self.assertEqual(run("--glossary", str(self.glossary), stdin="ok.\n```\nобработчик\n").returncode, 2)

    def test_longer_fence_is_not_closed_by_shorter_one(self) -> None:
        text = "````\n```\nобработчик\n```\n````\nПерезапусти обработчика.\n"
        result = run("--glossary", str(self.glossary), stdin=text)
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:6:", result.stdout)
        self.assertNotIn("<stdin>:3:", result.stdout)

    def test_glossary_without_variants_is_not_green(self) -> None:
        self.glossary.write_text('{"terms": {"a": []}}', encoding="utf-8")
        self.assertEqual(run("--glossary", str(self.glossary), stdin="text").returncode, 2)

    def test_empty_file_next_to_full_one_is_not_green(self) -> None:
        empty = Path(self.tmp.name) / "empty.md"
        empty.write_text("", encoding="utf-8")
        full = Path(self.tmp.name) / "full.md"
        full.write_text("Перезапусти воркер.", encoding="utf-8")
        self.assertEqual(run("--glossary", str(self.glossary), str(full), str(empty)).returncode, 2)

    def test_glossary_with_bom_is_accepted(self) -> None:
        self.glossary.write_bytes(b"\xef\xbb\xbf" + self.glossary.read_bytes())
        self.assertEqual(run("--glossary", str(self.glossary), stdin="Перезапусти воркер.").returncode, 0)

    def test_input_without_prose_is_not_green(self) -> None:
        self.assertEqual(run("--glossary", str(self.glossary), stdin="```\nобработчик\n```\n").returncode, 2)
        self.assertEqual(run("--glossary", str(self.glossary), stdin="<!--\nобработчик\n-->\n").returncode, 2)

    def test_glossary_that_cannot_flag_or_has_typos_is_not_green(self) -> None:
        for bad in ('{"terms": {"bolt": ["bolt"]}}', '{"terms": {"bolt": ["bol*"]}}',
                    '{"terms": {"bolt": ["screw"]}, "max_word": 30}'):
            self.glossary.write_text(bad, encoding="utf-8")
            self.assertEqual(run("--glossary", str(self.glossary), stdin="text").returncode, 2, bad)

    def test_backtick_in_info_string_is_not_a_fence(self) -> None:
        result = run("--glossary", str(self.glossary), stdin="``` a`b\nПерезапусти обработчика.\n")
        self.assertEqual(result.returncode, 1)

    def test_multiline_html_comment_keeps_line_numbers(self) -> None:
        result = run("--glossary", str(self.glossary),
                     stdin="<!--\nобработчик\n-->\nПерезапусти обработчика.\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:4:", result.stdout)
        self.assertNotIn("<stdin>:2:", result.stdout)

    def test_frontmatter_is_skipped_but_body_lines_keep_numbers(self) -> None:
        text = "---\ntitle: Перезапусти обработчика\n---\nПерезапусти обработчика.\n"
        result = run("--glossary", str(self.glossary), stdin=text)
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:4:", result.stdout)
        self.assertNotIn("<stdin>:2:", result.stdout)

    def test_unclosed_frontmatter_is_checked_as_text(self) -> None:
        result = run("--glossary", str(self.glossary), stdin="---\nПерезапусти обработчика.\n")
        self.assertEqual(result.returncode, 1)

    def test_frontmatter_only_is_not_green(self) -> None:
        self.assertEqual(run("--glossary", str(self.glossary), stdin="---\ntitle: x\n---\n").returncode, 2)

    def test_long_sentence_line_points_at_its_start(self) -> None:
        rules, _ = DRIFT.parse_glossary({"terms": {"a": ["b"]}})
        text = "Short.\n\nOne two three four five\nsix seven eight nine ten eleven."
        findings = DRIFT.check(text, "t", rules, 10)
        self.assertEqual([(f.kind, f.line) for f in findings], [("long-sentence", 3)])


if __name__ == "__main__":
    unittest.main()
