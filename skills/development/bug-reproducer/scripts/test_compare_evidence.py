#!/usr/bin/env python3
"""Entry-point checks for receipt-backed Bug Reproducer classification."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
CAPTURE = SCRIPTS / "capture_command.py"
COMPARE = SCRIPTS / "compare_evidence.py"


class CompareEvidenceEntrypointTests(unittest.TestCase):
    def capture(self, output: Path, status_file: Path) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(CAPTURE),
                "--output",
                str(output),
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; raise SystemExit(int(Path(r'{status_file}').read_text()))",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def classify(self, directory: Path, broader_exit: int | None) -> dict[str, object]:
        before = directory / "before.json"
        after = directory / "after.json"
        result = directory / "result.json"
        target_status = directory / "target-status.txt"
        target_status.write_text("1", encoding="utf-8")
        self.capture(before, target_status)
        target_status.write_text("0", encoding="utf-8")
        self.capture(after, target_status)
        command = [
            sys.executable,
            str(COMPARE),
            str(before),
            str(after),
            str(result),
            "--reproduction",
            "confirmed",
        ]
        if broader_exit is not None:
            broader = directory / "broader.json"
            broader_status = directory / "broader-status.txt"
            broader_status.write_text(str(broader_exit), encoding="utf-8")
            self.capture(broader, broader_status)
            command.extend(["--relevant-evidence", str(broader)])
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(result.read_text(encoding="utf-8"))

    def test_missing_broader_receipt_is_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.classify(Path(temporary), None)
        self.assertEqual(result["status"], "FIX_UNVERIFIED")
        self.assertEqual(result["relevant_check"], "not-run")

    def test_failing_broader_receipt_is_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.classify(Path(temporary), 1)
        self.assertEqual(result["status"], "FIX_REGRESSION")
        self.assertEqual(result["relevant_check"], "failed")

    def test_passing_broader_receipt_proves_fix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.classify(Path(temporary), 0)
        self.assertEqual(result["status"], "FIX_PROVEN")
        self.assertEqual(result["relevant_check"], "passed")

    def test_self_reported_full_suite_flag_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            before = directory / "before.json"
            after = directory / "after.json"
            target_status = directory / "target-status.txt"
            target_status.write_text("1", encoding="utf-8")
            self.capture(before, target_status)
            target_status.write_text("0", encoding="utf-8")
            self.capture(after, target_status)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(COMPARE),
                    str(before),
                    str(after),
                    str(directory / "result.json"),
                    "--reproduction",
                    "confirmed",
                    "--full-suite",
                    "passed",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unrecognized arguments", completed.stderr)


if __name__ == "__main__":
    unittest.main()
