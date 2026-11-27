#!/usr/bin/env python3
"""Focused regression checks for the bounded harness-improvement pilot."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).with_name("harness_improvement_pilot.py")
SPEC = importlib.util.spec_from_file_location("harness_improvement_pilot", SCRIPT)
assert SPEC and SPEC.loader
PILOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PILOT)

DIGEST = "sha256:" + "a" * 64
LESSON = {
    "cue": "stop loop re-enters after a tool failure",
    "lesson": "name the stop condition before the retry instruction",
    "evidence": "evidence/comparison.json",
    "confidence": "medium",
}


def receipt(*, development_pass: bool, held_out_pass: bool = True, safety: bool = True,
            tool_calls: int = 5, elapsed_ms: int = 100,
            dev_runs: list[bool] | None = None, task_runs: list[bool] | None = None) -> dict:
    def item(case_id: str, partition: str, passed: bool, runs: list[bool] | None) -> dict:
        return {
            "id": case_id,
            "partition": partition,
            "runs": runs if runs is not None else [passed] * 3,
            "safety_passed": safety,
            "tool_calls": tool_calls,
            "elapsed_ms": elapsed_ms,
        }

    return {
        "schema": "harness-improvement-pilot/v1",
        "suite": {"id": "completion-loop", "input_digest": "sha256:fixture-v1"},
        "objective": {"name": "outcome_pass_rate", "direction": "higher"},
        "cases": [
            item("known-stop-loop", "development", development_pass, dev_runs),
            item("known-task-receipt", "development", True, task_runs),
            item("held-out-reentry", "held_out", held_out_pass, None),
        ],
    }


def candidate_receipt(*, component: object = "prompt", lesson: object = LESSON, **kwargs) -> dict:
    data = receipt(**kwargs)
    data["candidate"] = {"component": component, "diff_sha256": DIGEST}
    if lesson is not None:
        data["candidate"]["lesson"] = lesson
    return data


def legacy_shape(data: dict) -> dict:
    for item in data["cases"]:
        item["outcome_passed"] = item.pop("runs")[0]
    return data


class HarnessImprovementPilotTests(unittest.TestCase):
    def test_accepts_strict_improvement_with_safe_held_out_coverage(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            candidate_receipt(development_pass=True),
        )
        self.assertEqual(report["decision"], "ACCEPT")
        self.assertEqual(report["baseline"]["outcome_pass_rate"], 2 / 3)
        self.assertEqual(report["candidate"]["outcome_pass_rate"], 1.0)

    def test_rejects_candidate_that_fails_a_held_out_case(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            candidate_receipt(development_pass=True, held_out_pass=False),
        )
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("held-out", " ".join(report["reasons"]))

    def test_rejects_candidate_that_weakens_safety_even_when_metric_improves(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            candidate_receipt(development_pass=True, safety=False),
        )
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("safety", " ".join(report["reasons"]))

    def test_rejects_candidate_without_a_strict_improvement(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=True),
            candidate_receipt(development_pass=True),
        )
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("did not strictly improve", " ".join(report["reasons"]))

    def test_rejects_mismatched_frozen_suite_inputs(self) -> None:
        baseline = receipt(development_pass=False)
        candidate = candidate_receipt(development_pass=True)
        candidate["suite"]["input_digest"] = "sha256:other"
        with self.assertRaisesRegex(ValueError, "input_digest"):
            PILOT.compare(baseline, candidate)


class ComponentTests(unittest.TestCase):
    def test_candidate_without_component_is_not_checked(self) -> None:
        candidate = candidate_receipt(development_pass=True)
        del candidate["candidate"]["component"]
        with self.assertRaisesRegex(ValueError, "not checked"):
            PILOT.compare(receipt(development_pass=False), candidate)

    def test_unknown_component_is_an_input_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "one of"):
            PILOT.compare(
                receipt(development_pass=False),
                candidate_receipt(development_pass=True, component="vibes"),
            )

    def test_candidate_without_diff_digest_is_not_checked(self) -> None:
        candidate = candidate_receipt(development_pass=True)
        del candidate["candidate"]["diff_sha256"]
        with self.assertRaisesRegex(ValueError, "not checked"):
            PILOT.compare(receipt(development_pass=False), candidate)

    def test_malformed_diff_digest_is_an_input_error(self) -> None:
        candidate = candidate_receipt(development_pass=True)
        candidate["candidate"]["diff_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(ValueError, "sha256"):
            PILOT.compare(receipt(development_pass=False), candidate)

    def test_more_than_one_component_is_rejected(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            candidate_receipt(development_pass=True, component=["prompt", "hook"]),
        )
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("more than one component", " ".join(report["reasons"]))

    def test_single_component_list_is_accepted(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            candidate_receipt(development_pass=True, component=["prompt"]),
        )
        self.assertEqual(report["decision"], "ACCEPT")

    def test_report_names_the_changed_component(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            candidate_receipt(development_pass=True, component="skill"),
        )
        self.assertEqual(report["change"], {"component": "skill", "diff_sha256": DIGEST})


class RepeatTests(unittest.TestCase):
    def test_case_passes_on_majority_of_runs(self) -> None:
        metrics = PILOT.metrics(receipt(development_pass=False, dev_runs=[True, False, True]))
        self.assertEqual(metrics["outcome_pass_rate"], 1.0)

    def test_case_fails_without_majority_of_runs(self) -> None:
        metrics = PILOT.metrics(receipt(development_pass=False, dev_runs=[True, False, False]))
        self.assertEqual(metrics["outcome_pass_rate"], 2 / 3)

    def test_even_split_is_not_a_majority(self) -> None:
        metrics = PILOT.metrics(receipt(development_pass=False, dev_runs=[True, False, True, False]))
        self.assertEqual(metrics["outcome_pass_rate"], 2 / 3)

    def test_improvement_resting_on_fewer_than_three_runs_is_confounded(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            candidate_receipt(development_pass=True, dev_runs=[True]),
        )
        self.assertEqual(report["verdict"], "CONFOUNDED")
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("fewer than 3 runs", " ".join(report["reasons"]))

    def test_legacy_single_boolean_shape_reads_as_one_run(self) -> None:
        report = PILOT.compare(
            legacy_shape(receipt(development_pass=False)),
            legacy_shape(candidate_receipt(development_pass=True)),
        )
        self.assertEqual(report["verdict"], "CONFOUNDED")
        self.assertEqual(report["decision"], "REJECT")

    def test_thin_runs_on_an_unchanged_case_do_not_confound(self) -> None:
        report = PILOT.compare(
            receipt(development_pass=False),
            candidate_receipt(development_pass=True, task_runs=[True]),
        )
        self.assertEqual(report["verdict"], "ACCEPT")
        self.assertEqual(report["decision"], "ACCEPT")


class StabilityTests(unittest.TestCase):
    """pass@k / pass^k and regression cases (Anthropic, Demystifying evals for AI agents)."""

    def test_pass_at_k_and_pass_hat_k_differ_on_a_flaky_case(self) -> None:
        metrics = PILOT.metrics(receipt(development_pass=False, dev_runs=[True, False, True]))
        self.assertEqual(metrics["outcome_pass_rate"], 1.0)
        self.assertEqual(metrics["pass_at_k_rate"], 1.0)
        self.assertEqual(metrics["pass_hat_k_rate"], 2 / 3)

    def test_pass_at_k_counts_a_case_with_no_passing_run_as_failed(self) -> None:
        metrics = PILOT.metrics(receipt(development_pass=False, dev_runs=[False, False, False]))
        self.assertEqual(metrics["pass_at_k_rate"], 2 / 3)

    def test_regression_case_failing_one_run_rejects(self) -> None:
        candidate = candidate_receipt(development_pass=True, task_runs=[True, True, False])
        candidate["cases"][1]["kind"] = "regression"
        base = receipt(development_pass=False)
        base["cases"][1]["kind"] = "regression"
        report = PILOT.compare(base, candidate)
        self.assertEqual(report["decision"], "REJECT")
        self.assertIn("candidate regression cases did not pass every run: known-task-receipt",
                      report["reasons"])

    def test_capability_case_may_fail_one_run(self) -> None:
        candidate = candidate_receipt(development_pass=True, task_runs=[True, True, False])
        candidate["cases"][1]["kind"] = "capability"
        base = receipt(development_pass=False)
        base["cases"][1]["kind"] = "capability"
        report = PILOT.compare(base, candidate)
        self.assertEqual(report["decision"], "ACCEPT")

    def test_candidate_cannot_relabel_or_drop_a_regression_kind(self) -> None:
        for relabel in ("capability", None):
            base = receipt(development_pass=False)
            base["cases"][1]["kind"] = "regression"
            cand = candidate_receipt(development_pass=True, task_runs=[True, True, False])
            if relabel:
                cand["cases"][1]["kind"] = relabel
            with self.assertRaisesRegex(ValueError, "keep each case's kind"):
                PILOT.compare(base, cand)

    def test_unknown_kind_is_an_input_error(self) -> None:
        data = receipt(development_pass=True)
        data["cases"][0]["kind"] = "smoke"
        with self.assertRaisesRegex(ValueError, "kind must be one of"):
            PILOT.validate_receipt(data)

    def test_pass_hat_k_objective_accepts_a_stabilised_case(self) -> None:
        base = receipt(development_pass=True, dev_runs=[True, False, True])
        cand = candidate_receipt(development_pass=True)
        for data in (base, cand):
            data["objective"] = {"name": "pass_hat_k_rate", "direction": "higher"}
        report = PILOT.compare(base, cand)
        self.assertEqual(report["decision"], "ACCEPT")
        self.assertEqual(report["baseline"]["pass_hat_k_rate"], 2 / 3)

    def test_pass_hat_k_gain_on_thin_runs_is_confounded(self) -> None:
        base = receipt(development_pass=True, dev_runs=[True, False])
        cand = candidate_receipt(development_pass=True, dev_runs=[True, True])
        for data in (base, cand):
            data["objective"] = {"name": "pass_hat_k_rate", "direction": "higher"}
        report = PILOT.compare(base, cand)
        self.assertEqual(report["verdict"], "CONFOUNDED")

    def test_pass_hat_k_objective_does_not_rest_on_unchanged_thin_case(self) -> None:
        base = receipt(development_pass=True, dev_runs=[True, False, True], task_runs=[True])
        cand = candidate_receipt(development_pass=True, task_runs=[True])
        for data in (base, cand):
            data["objective"] = {"name": "pass_hat_k_rate", "direction": "higher"}
        self.assertEqual(PILOT.compare(base, cand)["verdict"], "ACCEPT")


class LowerObjectiveAndInputTests(unittest.TestCase):
    def numeric(self, base_calls: int, cand_calls: int) -> dict:
        base = receipt(development_pass=True, tool_calls=base_calls)
        cand = candidate_receipt(development_pass=True, tool_calls=cand_calls)
        for data in (base, cand):
            data["objective"] = {"name": "mean_tool_calls", "direction": "lower"}
        return PILOT.compare(base, cand)

    def test_fewer_tool_calls_is_accepted(self) -> None:
        report = self.numeric(5, 4)
        self.assertEqual(report["decision"], "ACCEPT")
        self.assertEqual(report["baseline"]["mean_tool_calls"], 5.0)
        self.assertEqual(report["baseline"]["mean_elapsed_ms"], 100.0)

    def test_equal_tool_calls_is_not_an_improvement(self) -> None:
        self.assertEqual(self.numeric(5, 5)["decision"], "REJECT")

    def bad(self, mutate, message: str) -> None:
        data = receipt(development_pass=True)
        mutate(data)
        with self.assertRaisesRegex(ValueError, message):
            PILOT.validate_receipt(data)

    def test_suite_needs_both_fields(self) -> None:
        self.bad(lambda d: d["suite"].pop("input_digest"), "input_digest")
        self.bad(lambda d: d["suite"].update(id="  "), "input_digest")

    def test_objective_direction_is_fixed(self) -> None:
        self.bad(lambda d: d["objective"].update(direction="lower"), "fixed direction")

    def test_suite_needs_three_cases(self) -> None:
        self.bad(lambda d: d["cases"].pop(), "at least three")

    def test_case_ids_must_be_unique_and_non_empty(self) -> None:
        self.bad(lambda d: d["cases"][1].update(id=d["cases"][0]["id"]), "unique")
        self.bad(lambda d: d["cases"][1].update(id=" "), "unique")


class LessonLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lessons = self.root / "evidence" / "harness-lessons.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, baseline: dict, candidate: dict) -> int:
        base = self.root / "baseline.json"
        cand = self.root / "candidate.json"
        base.write_text(json.dumps(baseline), encoding="utf-8")
        cand.write_text(json.dumps(candidate), encoding="utf-8")
        return PILOT.main([
            "--baseline", str(base), "--candidate", str(cand),
            "--report", str(self.root / "report.json"), "--lessons", str(self.lessons),
        ])

    def ledger_lines(self) -> list[str]:
        return self.lessons.read_text(encoding="utf-8").splitlines()

    def test_accepted_change_appends_one_lesson_line(self) -> None:
        self.assertEqual(self.run_cli(receipt(development_pass=False),
                                      candidate_receipt(development_pass=True)), 0)
        lines = self.ledger_lines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["verdict"], "ACCEPT")
        self.assertEqual(entry["component"], "prompt")
        self.assertEqual(entry["cue"], LESSON["cue"])
        self.assertEqual(entry["lesson"], LESSON["lesson"])
        self.assertEqual(entry["evidence"], LESSON["evidence"])
        self.assertEqual(entry["confidence"], LESSON["confidence"])
        self.assertEqual(entry["date"], date.today().isoformat())

    def test_later_runs_append_without_rewriting_earlier_lines(self) -> None:
        self.run_cli(receipt(development_pass=False), candidate_receipt(development_pass=True))
        first = self.ledger_lines()[0]
        self.assertEqual(self.run_cli(receipt(development_pass=False),
                                      candidate_receipt(development_pass=True, held_out_pass=False)), 1)
        lines = self.ledger_lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], first)
        self.assertEqual(json.loads(lines[1])["verdict"], "REJECT")

    def test_missing_lesson_writes_no_entry(self) -> None:
        self.run_cli(receipt(development_pass=False),
                     candidate_receipt(development_pass=True, lesson=None))
        entry = json.loads(self.ledger_lines()[0])
        self.assertEqual(entry["entry"], "NO_ENTRY")
        self.assertEqual(entry["verdict"], "ACCEPT")
        self.assertNotIn("lesson", entry)

    def test_confounded_verdict_writes_no_entry_even_with_a_lesson(self) -> None:
        self.assertEqual(self.run_cli(receipt(development_pass=False),
                                      candidate_receipt(development_pass=True, dev_runs=[True])), 1)
        entry = json.loads(self.ledger_lines()[0])
        self.assertEqual(entry, {"date": date.today().isoformat(), "verdict": "CONFOUNDED", "entry": "NO_ENTRY"})

    def test_incomplete_lesson_is_an_input_error_and_writes_nothing(self) -> None:
        incomplete = dict(LESSON)
        del incomplete["evidence"]
        self.assertEqual(self.run_cli(receipt(development_pass=False),
                                      candidate_receipt(development_pass=True, lesson=incomplete)), 2)
        self.assertFalse(self.lessons.exists())


class CommandLineTests(unittest.TestCase):
    def test_cli_writes_machine_readable_report_without_touching_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            report = root / "report.json"
            baseline.write_text(json.dumps(receipt(development_pass=False)), encoding="utf-8")
            candidate.write_text(json.dumps(candidate_receipt(development_pass=True)), encoding="utf-8")
            self.assertEqual(PILOT.main([
                "--baseline", str(baseline), "--candidate", str(candidate), "--report", str(report),
                "--lessons", str(root / "lessons.jsonl"),
            ]), 0)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["decision"], "ACCEPT")
            self.assertEqual(json.loads(baseline.read_text(encoding="utf-8"))["schema"], "harness-improvement-pilot/v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
