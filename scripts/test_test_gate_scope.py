from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).resolve().parent.parent / "hooks" / "test-gate-stop-hook.py"
spec = importlib.util.spec_from_file_location("test_gate_stop_hook", HOOK)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class TestGateScopeTests(unittest.TestCase):
    def run_gate(self, root: Path, policy: dict[str, list[str]]) -> subprocess.CompletedProcess[str]:
        (root / ".claude").mkdir(exist_ok=True)
        (root / ".claude" / "test-policy.json").write_text(
            json.dumps(policy), encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
        return subprocess.run(
            [sys.executable, str(HOOK)],
            cwd=root,
            input=json.dumps({"stop_hook_active": False}),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_docs_only_changes_do_not_trigger_suite(self) -> None:
        scope = module.classify_paths(["README.md", "docs/research/testing.md"])
        self.assertEqual(scope.name, "docs-only")
        self.assertFalse(scope.should_run)

    def test_boundary_change_is_high_risk(self) -> None:
        scope = module.classify_paths(["src/auth/token_service.py", "db/migrations/004.sql"])
        self.assertEqual(scope.name, "high-risk")
        self.assertTrue(scope.should_run)
        self.assertIn("boundary", scope.reason)

    def test_test_only_change_still_runs_fast_gate(self) -> None:
        scope = module.classify_paths(["tests/unit/test_parser.py"])
        self.assertEqual(scope.name, "tests-only")
        self.assertTrue(scope.should_run)

    def test_common_word_does_not_trigger_boundary_risk(self) -> None:
        scope = module.classify_paths(["src/capitalization.py"])
        self.assertEqual(scope.name, "source")

    def test_policy_commands_are_lists_of_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".claude").mkdir()
            (root / ".claude" / "test-policy.json").write_text(
                json.dumps({"fast": ["python", "-m", "pytest", "-q"]}),
                encoding="utf-8",
            )
            commands = module.load_policy_commands(root)
            self.assertEqual(commands["fast"], ["python", "-m", "pytest", "-q"])

    def test_docs_only_does_not_execute_configured_fast_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-gate-docs-") as raw:
            root = Path(raw)
            (root / "README.md").write_text("docs", encoding="utf-8")
            marker = "from pathlib import Path; Path('fast.marker').write_text('ran')"
            result = self.run_gate(root, {"fast": [sys.executable, "-c", marker]})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((root / "fast.marker").exists())

    def test_high_risk_runs_fast_and_integration_commands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-gate-high-risk-") as raw:
            root = Path(raw)
            (root / "src").mkdir()
            (root / "src" / "auth.py").write_text("# source", encoding="utf-8")
            fast = "from pathlib import Path; Path('fast.marker').write_text('ran')"
            integration = "from pathlib import Path; Path('integration.marker').write_text('ran')"
            result = self.run_gate(
                root,
                {
                    "fast": [sys.executable, "-c", fast],
                    "integration": [sys.executable, "-c", integration],
                },
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / "fast.marker").exists())
            self.assertTrue((root / "integration.marker").exists())

    def test_failing_fast_command_blocks_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-gate-failure-") as raw:
            root = Path(raw)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("# source", encoding="utf-8")
            result = self.run_gate(
                root,
                {"fast": [sys.executable, "-c", "raise SystemExit(3)"]},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload.get("decision"), "block")
            self.assertIn("policy.fast exit 3", payload.get("reason", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
