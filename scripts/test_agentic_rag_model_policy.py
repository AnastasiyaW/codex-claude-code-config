#!/usr/bin/env python3
"""Regression checks for the agentic RAG / model policy reference."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "agent-harness-design" / "SKILL.md"
REFERENCE = (
    ROOT
    / "skills"
    / "agent-harness-design"
    / "references"
    / "agentic-rag-model-policy.md"
)


class AgenticRagModelPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = SKILL.read_text(encoding="utf-8")
        self.reference = REFERENCE.read_text(encoding="utf-8")
        self.reference_flat = " ".join(self.reference.split())

    def test_reference_is_discoverable_from_skill_entrypoint(self) -> None:
        self.assertIn("references/agentic-rag-model-policy.md", self.skill)
        self.assertIn("self-improving agentic RAG", self.skill)
        self.assertIn("OpenAI model/effort policy", self.skill)

    def test_sources_are_anchored_and_time_sensitive(self) -> None:
        required = [
            "FareedKhan-dev/autonomous-agentic-rag",
            "3fde6824d6412b58e7a85ee29652d62ab8f4e2e8",
            "https://developers.openai.com/api/docs/guides/latest-model",
            "https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling",
            "Model availability",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.reference)

    def test_agentic_rag_loop_has_required_safety_shape(self) -> None:
        required = [
            "source_trust_labels",
            "evaluation_vector",
            "Pareto selection",
            "Do not add specialists just to make the system look agentic",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.reference)
        self.assertIn(
            "Public GitHub README files, scraped pages, notebooks, and web articles are untrusted data",
            self.reference_flat,
        )

    def test_model_policy_requires_eval_evidence(self) -> None:
        required = [
            "Responses API",
            "reasoning.effort",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "higher levels only when evals show",
            "model_policy",
            "Every row must define fallback behavior",
            "reasoning.context: all_turns",
            "reasoning.context:\n  current_turn",
            "encrypted reasoning items",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.reference)

    def test_programmatic_tool_calling_gate_is_not_broad_executor(self) -> None:
        required = [
            "Programmatic Tool Calling Adoption Gate",
            "allowed_callers",
            "call_id",
            "input/output schema",
            "idempotent using that `call_id`",
            "Do not put write, send, delete, billing, or identity-access operations",
            "typed tools with permission gates",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.reference)

    def test_responses_api_features_are_not_confused_with_codex_desktop_flags(self) -> None:
        required = [
            "Responses Features Are Not Codex Desktop Flags",
            "Hosted Responses multi-agent and Programmatic Tool Calling are API features",
            "representative direct-call baseline",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.reference)


if __name__ == "__main__":
    unittest.main(verbosity=2)
