#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "hooks" / "continuity-contract-guard.py"
spec = importlib.util.spec_from_file_location("continuity_guard", MODULE_PATH)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def contract(**overrides):
    value = {
        "schema_version": 1,
        "mode": "continuation",
        "goal": "finish the focused fix",
        "baseline": {"branch": "feature/x", "head": "abc123", "preexisting_paths": []},
        "scope": {"enforce": True, "protect_unlisted": True, "files": ["src/main.cpp"]},
        "preserve": ["keep the existing ABI"],
        "do_not_redo": ["do not replace the working allocator"],
    }
    value.update(overrides)
    return value


class ContinuityContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="continuity-contract-")
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("AGENT_CONTINUITY_MODE", None)
        os.environ.pop("AGENT_CONTINUITY_REASON", None)

    def event(self, tool="Edit", **tool_input):
        return {"tool_name": tool, "tool_input": tool_input}

    def test_focused_edit_inside_declared_scope_is_allowed(self):
        decision, _ = guard.decision_for_event(
            self.event(file_path=str(self.root / "src" / "main.cpp"), old_string="return 0;", new_string="return 1;"),
            self.root,
            contract(),
            existing_status=set(),
            tracked_paths={"src/main.cpp"},
        )
        self.assertEqual(decision, "allow")

    def test_scope_expansion_is_blocked(self):
        (self.root / "src" / "other.cpp").write_text("int f() { return 0; }\n", encoding="utf-8")
        decision, reason = guard.decision_for_event(
            self.event(file_path=str(self.root / "src" / "other.cpp"), old_string="return 0;", new_string="return 1;"),
            self.root,
            contract(),
            existing_status=set(),
            tracked_paths={"src/other.cpp"},
        )
        self.assertEqual(decision, "block")
        self.assertIn("outside the declared scope", reason)

    def test_contract_itself_stays_editable_under_an_enforcing_contract(self):
        """Контракт обязан оставаться правимым, иначе он запрещает себя дополнять.

        Объём проверяется по СТАРОЙ редакции: если собственного пути в ней нет, добавить
        его туда уже нельзя, и единственным выходом остаётся обойти хук. Поймано 25.08.2026
        на попытке расширить объём после согласованной передачи файлов между агентами.
        """
        contract_file = self.root / ".claude" / "continuity" / "CONTINUITY.json"
        decision, reason = guard.decision_for_event(
            self.event(file_path=str(contract_file),
                       old_string='"files": []', new_string='"files": ["src/new.cpp"]'),
            self.root,
            contract(),
            existing_status=set(),
            tracked_paths=set(),
        )
        self.assertNotEqual(decision, "block", f"контракт заблокирован: {reason}")

    def test_write_over_existing_tracked_file_is_blocked(self):
        decision, reason = guard.decision_for_event(
            self.event(tool="Write", file_path=str(self.root / "src" / "main.cpp"), content="int main() { return 1; }\n"),
            self.root,
            contract(),
            existing_status=set(),
            tracked_paths={"src/main.cpp"},
        )
        self.assertEqual(decision, "block")
        self.assertIn("existing tracked", reason)

    def test_large_replacement_is_blocked(self):
        body = "\n".join(f"int f{i}() {{ return {i}; }}" for i in range(120)) + "\n"
        (self.root / "src" / "main.cpp").write_text(body, encoding="utf-8")
        old = "\n".join(f"int f{i}() {{ return {i}; }}" for i in range(100))
        decision, reason = guard.decision_for_event(
            self.event(file_path=str(self.root / "src" / "main.cpp"), old_string=old, new_string=old.replace("return 0", "return 1")),
            self.root,
            contract(),
            existing_status=set(),
            tracked_paths={"src/main.cpp"},
        )
        self.assertEqual(decision, "block")
        self.assertIn("near-whole-file", reason)

    def test_explicit_replan_allows_intentional_rewrite(self):
        os.environ["AGENT_CONTINUITY_MODE"] = "replan"
        os.environ["AGENT_CONTINUITY_REASON"] = "replace allocator after measured benchmark regression"
        decision, reason = guard.decision_for_event(
            self.event(tool="Write", file_path=str(self.root / "src" / "main.cpp"), content="new implementation\n"),
            self.root,
            contract(),
            existing_status=set(),
            tracked_paths={"src/main.cpp"},
        )
        self.assertEqual(decision, "context")
        self.assertIn("Explicit replan", reason)

    def test_missing_contract_is_advisory_not_a_false_gate(self):
        decision, reason = guard.decision_for_event(
            self.event(tool="Write", file_path=str(self.root / "src" / "main.cpp"), content="new\n"),
            self.root,
            None,
            existing_status=set(),
            tracked_paths={"src/main.cpp"},
        )
        self.assertEqual(decision, "context")
        self.assertIn("No CONTINUITY.json", reason)

    def test_existing_handoff_state_requires_contract_before_code_edit(self):
        (self.root / ".claude" / "handoffs").mkdir(parents=True)
        decision, reason = guard.decision_for_event(
            self.event(file_path=str(self.root / "src" / "main.cpp"), old_string="return 0;", new_string="return 1;"),
            self.root,
            None,
            existing_status=set(),
            tracked_paths={"src/main.cpp"},
        )
        self.assertEqual(decision, "block")
        self.assertIn("already has handoff state", reason)

    def test_contract_file_can_be_created_when_handoff_state_exists(self):
        (self.root / ".claude" / "handoffs").mkdir(parents=True)
        contract_path = self.root / ".claude" / "continuity" / "CONTINUITY.json"
        decision, _ = guard.decision_for_event(
            self.event(tool="Write", file_path=str(contract_path), content="{}\n"),
            self.root,
            None,
            existing_status=set(),
            tracked_paths=set(),
        )
        self.assertEqual(decision, "context")

    def test_repo_root_probe_uses_existing_ancestor_for_new_contract_path(self):
        public_root = MODULE_PATH.parents[1].resolve()
        new_contract = public_root / ".claude" / "continuity" / "CONTINUITY.json"
        self.assertEqual(guard.repo_root_for(new_contract), public_root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
