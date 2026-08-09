"""Prove the test gate selects candidate states instead of repeating costly work.

This drives the real selection functions in ``test-gate-stop-hook.py``. It does
not run a full project suite: the contract being tested is that per-edit hooks
choose the smallest sufficient lane and leave full-matrix and specialized-
environment proof to the immutable candidate workflow.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = ROOT / "hooks" / "test-gate-stop-hook.py"
SPEC = importlib.util.spec_from_file_location("test_gate_stop_hook", HOOK_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {HOOK_PATH}")
HOOK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HOOK
SPEC.loader.exec_module(HOOK)


def check(label: str, condition: bool, failures: list[str]) -> None:
    print(f"  [{'ok ' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="test-strategy-") as raw:
        root = Path(raw)
        policy_dir = root / ".claude"
        policy_dir.mkdir()
        (policy_dir / "test-policy.json").write_text(json.dumps({
            "fast": ["python", "focused.py"],
            "integration": ["python", "boundary.py"],
            "release": ["python", "full_matrix.py"],
        }), encoding="utf-8")

        normal = HOOK.classify_paths(["src/parser.py"])
        normal_commands = HOOK.detect_test_commands(root, normal)
        normal_labels = [label for _, label in normal_commands]
        check("normal source selects fast only", normal_labels == ["policy.fast"], failures)
        check("normal source does not select candidate matrix", "policy.release" not in normal_labels, failures)

        risky = HOOK.classify_paths(["src/auth/login.py"])
        risky_commands = HOOK.detect_test_commands(root, risky)
        risky_labels = [label for _, label in risky_commands]
        check("high-risk source selects fast plus integration", risky_labels == ["policy.fast", "policy.integration"], failures)
        check("high-risk source does not select candidate matrix", "policy.release" not in risky_labels, failures)

        tests_only = HOOK.classify_paths(["tests/test_parser.py"])
        tests_only_commands = HOOK.detect_test_commands(root, tests_only)
        tests_only_labels = [label for _, label in tests_only_commands]
        check("tests-only change stays on fast lane", tests_only_labels == ["policy.fast"], failures)

        docs_only = HOOK.classify_paths(["docs/testing-strategy.md"])
        docs_commands = HOOK.detect_test_commands(root, docs_only)
        check("docs-only change selects no test lane", docs_only.name == "docs-only" and not docs_commands, failures)

    print("TEST STRATEGY:", "PASS" if not failures else "FAIL")
    for failure in failures:
        print("  -", failure)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
