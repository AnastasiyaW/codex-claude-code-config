#!/usr/bin/env python3
"""Focused regression checks for the bounded harness-improvement pilot."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("harness_improvement_pilot.py")
SPEC = importlib.util.spec_from_file_location("harness_improvement_pilot", SCRIPT)
assert SPEC and SPEC.loader
PILOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PILOT)


def receipt(*, development_pass: bool, held_out_pass: bool = True, safety: bool = True,
            tool_calls: int = 5, elapsed_ms: int = 100) -> dict:
    return {
        "schema": "harness-improvement-pilot/v1",
        "suite": {"id": "completion-loop", "input_digest": "sha256:fixture-v1"},
        "objective": {"name": "outcome_pass_rate", "direction": "higher"},
        "cases": [
            {
                "id": "known-stop-loop",
                "partition": "development",
                "outcome_passed": development_pass,
                "safety_passed": safety,
                "tool_calls": tool_calls,
                "elapsed_ms": elapsed_ms,
            },
            {
                "id": "known-task-receipt",
                "partition": "development",
                "outcome_passed": True,
                "safety_passed": safety,
                "tool_calls": tool_calls,
                "elapsed_ms": elapsed_ms,
            },
            {
                "id": "held-out-reentry",
                "partition": "held_out",
                "outcome_passed": held_out_pass,
                "safety_passed": safety,
                "tool_calls": tool_calls,
                "elapsed_ms": elapsed_ms,
            },
        ],
    }


class HarnessImprovementPilotTests(unittest.TestCase):
    def test_accepts_strict_improvement_with_safe_held_out_coverage(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            receipt(development_pass=True),
        )
        self.assertEqual(report["decision"], "ACCEPT")
        self.assertEqual(report["baseline"]["outcome_pass_rate"], 2 / 3)
        self.assertEqual(report["candidate"]["outcome_pass_rate"], 1.0)

    def test_rejects_candidate_that_fails_a_held_out_case(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            receipt(development_pass=True, held_out_pass=False),
        )
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("held-out", " ".join(report["reasons"]))

    def test_rejects_candidate_that_weakens_safety_even_when_metric_improves(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            receipt(development_pass=True, safety=False),
        )
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("safety", " ".join(report["reasons"]))

    def test_rejects_candidate_without_a_strict_improvement(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=True),
            receipt(development_pass=True),
        )
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("did not strictly improve", " ".join(report["reasons"]))

    def test_rejects_mismatched_frozen_suite_inputs(self) -> None:
        baseline = receipt(development_pass=False)
        candidate = receipt(development_pass=True)
        candidate["suite"]["input_digest"] = "sha256:other"
        with self.assertRaisesRegex(ValueError, "input_digest"):
            PILOT.compare(baseline, candidate)

    def test_cli_writes_machine_readable_report_without_touching_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            report = root / "report.json"
            baseline.write_text(json.dumps(receipt(development_pass=False)), encoding="utf-8")
            candidate.write_text(json.dumps(receipt(development_pass=True)), encoding="utf-8")
            self.assertEqual(PILOT.main([
                "--baseline", str(baseline), "--candidate", str(candidate), "--report", str(report),
            ]), 0)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["decision"], "ACCEPT")
            self.assertEqual(json.loads(baseline.read_text(encoding="utf-8"))["schema"], "harness-improvement-pilot/v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
