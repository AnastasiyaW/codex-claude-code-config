#!/usr/bin/env python3
"""Focused proof that delivery-case argv cannot become a shell executor."""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile


TMP = pathlib.Path(tempfile.mkdtemp(prefix="root-cause-proof-executor-"))
ROOT = TMP / "repo"
ROOT.mkdir()
HOOKS = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("root_cause_delivery_guard", HOOKS / "root-cause-delivery-guard.py")
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


def planned(argv: list[str]) -> dict:
    case = guard.default_case(ROOT, "proof-case", "change", "proof executor test")
    case["status"] = "ANALYZED"
    case["layer"] = {
        "entrypoints": ["hooks/root-cause-delivery-guard.py"],
        "owner_paths": ["hooks/root-cause-delivery-guard.py"],
        "direct_dependents": ["hooks/tests/test_root_cause_proof_executor.py"],
        "state_or_contract": [".agent/delivery-cases"],
        "tests_or_probes": ["hooks/tests/test_root_cause_proof_executor.py"],
        "release_boundary": "not-applicable",
    }
    case["plan"] = {
        "causal_hypothesis": "proof executor only runs typed local checks",
        "fix_steps": ["enforce the focused argv contract"],
        "focused_argv": argv,
    }
    return case


results: list[tuple[str, bool]] = []

# Approved repository-local verifier: it is accepted at freeze and runs through
# capture.  A non-zero "before" return is the expected evidence shape.
script = ROOT / "hooks" / "tests" / "test_local_probe.py"
script.parent.mkdir(parents=True)
script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
safe_argv = [sys.executable, "hooks/tests/test_local_probe.py"]
results.append(("approved local Python test script validates", guard._proof_argv_error(safe_argv, ROOT) is None))
safe_case = planned(safe_argv)
results.append(("approved local Python test script can freeze", not guard.validation_errors(safe_case, root=ROOT)))
safe_case["status"] = "INTAKE"
safe_path = guard.case_path(ROOT, "proof-case")
guard.save_case(safe_path, safe_case)
code, message = guard.capture(ROOT, "proof-case", "before", safe_argv)
results.append(("approved local Python test script captures evidence", code == 0 and "evidence=" in message))

for label, argv, expected in (
    ("shell interpreter", ["bash", "-c", "echo harmless"], "shell interpreter"),
    ("dynamic Python", [sys.executable, "-c", "print('x')"], "dynamic execution"),
    ("network client", ["curl", "https://example.invalid"], "network"),
    ("destructive executable", ["rm", "-rf", "build"], "destructive"),
    ("mutating linter", ["ruff", "check", "--fix", "."], "mutating"),
    ("mutating formatter", ["ruff", "format", "."], "format --check"),
    ("unknown executable", ["agent-proof-runner", "--pass"], "approved local"),
):
    error = guard._proof_argv_error(argv, ROOT)
    results.append((f"{label} is rejected", error is not None and expected in error))

unsafe_plan_errors = guard.validation_errors(planned(["curl", "https://example.invalid"]), root=ROOT)
results.append(("network argv cannot freeze a delivery plan", any("network" in error for error in unsafe_plan_errors)))

# A hand-edited legacy case must still never reach subprocess just because it
# already contains the same frozen argv that capture was given.
unsafe_case = planned(["curl", "https://example.invalid"])
unsafe_case["status"] = "INTAKE"
guard.save_case(safe_path, unsafe_case)
called = False
original_run = guard.subprocess.run


def unexpected_run(*args, **kwargs):  # type: ignore[no-untyped-def]
    global called
    called = True
    raise AssertionError("unsafe proof argv reached subprocess.run")


guard.subprocess.run = unexpected_run
try:
    code, message = guard.capture(ROOT, "proof-case", "before", ["curl", "https://example.invalid"])
finally:
    guard.subprocess.run = original_run
results.append(("unsafe frozen argv is blocked before subprocess", code == 2 and "unsafe focused_argv" in message and not called))

# The proof ceiling must leave real focused suites enough headroom. A timeout is
# still a legitimate red baseline, and a later successful run of the exact same
# argv must be able to provide the green after-capture.
timeout_case = planned(safe_argv)
timeout_case["kind"] = "incident"
timeout_case["status"] = "INTAKE"
guard.save_case(safe_path, timeout_case)
observed_timeout = None


def timed_out(*args, **kwargs):  # type: ignore[no-untyped-def]
    global observed_timeout
    observed_timeout = kwargs.get("timeout")
    raise subprocess.TimeoutExpired(args[0], observed_timeout, output="partial-out", stderr="partial-err")


guard.subprocess.run = timed_out
try:
    code, message = guard.capture(ROOT, "proof-case", "before", safe_argv)
finally:
    guard.subprocess.run = original_run
timed_case, _ = guard.load_case(ROOT, "proof-case")
results.append((
    "capture uses the bounded 900 second proof ceiling",
    observed_timeout == 900 and code == 0 and timed_case["verification"]["before"]["returncode"] == 124,
))

timed_case["status"] = "IMPLEMENTING"
guard.save_case(safe_path, timed_case)


def succeeded(argv, **kwargs):  # type: ignore[no-untyped-def]
    return subprocess.CompletedProcess(argv, 0, stdout="green", stderr="")


guard.subprocess.run = succeeded
try:
    code, message = guard.capture(ROOT, "proof-case", "after", safe_argv)
finally:
    guard.subprocess.run = original_run
timed_case, _ = guard.load_case(ROOT, "proof-case")
results.append((
    "a timed-out baseline can be followed by a green exact-argv capture",
    code == 0
    and timed_case["verification"]["before"]["returncode"] == 124
    and timed_case["verification"]["after"]["returncode"] == 0,
))

failures = [label for label, passed in results if not passed]
for label, passed in results:
    print(f"  {'ok' if passed else 'FAIL'} {label}")
shutil.rmtree(TMP, ignore_errors=True)
if failures:
    print(f"{len(failures)} of {len(results)} wrong")
    raise SystemExit(1)
print(f"all {len(results)} cases correct")
