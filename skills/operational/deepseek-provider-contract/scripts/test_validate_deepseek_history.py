from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_deepseek_history.py")
SPEC = importlib.util.spec_from_file_location("deepseek_history", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DeepSeekHistoryTests(unittest.TestCase):
    def test_tool_history_with_reasoning_is_valid(self) -> None:
        messages = [
            {"role": "user", "content": "weather"},
            {"role": "assistant", "reasoning_content": "need tool", "tool_calls": [{"id": "call-1"}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "sunny"},
            {"role": "user", "content": "and tomorrow?"},
        ]
        self.assertEqual(MODULE.validate(messages), [])

    def test_tool_history_requires_reasoning(self) -> None:
        errors = MODULE.validate([{"role": "assistant", "tool_calls": [{"id": "call-1"}]}])
        self.assertIn("lacks reasoning_content", errors[0])

    def test_tool_result_must_name_prior_call(self) -> None:
        errors = MODULE.validate([{"role": "tool", "content": "sunny"}])
        self.assertIn("lacks tool_call_id", errors[0])

    def test_non_tool_history_is_valid_without_reasoning(self) -> None:
        self.assertEqual(MODULE.validate([{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
