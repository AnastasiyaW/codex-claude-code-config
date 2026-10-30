#!/usr/bin/env python3
"""Focused proof for SUPERSEDED terminal status and measured-correction retriage.

Negative controls must stay red: a supersede that names a missing case, a case
with no shared owner path, a chain, a cycle, or an already-terminal case; and a
measured correction whose evidence file lacks a labeled ``Observed:`` line or
lies outside the repository.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1])).resolve()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="root-cause-supersede-"))
ROOT = TMP / "repo"
ROOT.mkdir()
OUTSIDE = TMP / "outside-correction.txt"
OUTSIDE.write_text("Observed: a real line outside the repository\n", encoding="utf-8")

spec = importlib.util.spec_from_file_location("root_cause_delivery_guard", HOOKS / "root-cause-delivery-guard.py")
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)

ORIGINAL_CWD = os.getcwd()
os.chdir(ROOT)
subprocess.run(["git", "init", "-q"], cwd=ROOT, check=True)


def make_case(case_id: str, status: str, owners: list[str], attempts: int = 0) -> None:
    case = guard.default_case(ROOT, case_id, "incident", f"{case_id} summary", "unscoped")
    case["status"] = status
    case["observed"] = {"expected": "pass", "actual": "fail"}
    case["layer"] = {
        "entrypoints": ["ci.yml"],
        "owner_paths": owners,
        "direct_dependents": ["consumer"],
        "state_or_contract": ["contract"],
        "tests_or_probes": ["probe"],
        "release_boundary": "not-applicable",
    }
    case["plan"] = {
        "causal_hypothesis": f"hypothesis of {case_id}",
        "fix_steps": ["bounded change"],
        "focused_argv": ["python", "probe.py"],
    }
    case["attempts"] = [
        {"number": n + 1, "result": "FAIL", "hypothesis": f"try {n + 1}", "changed_paths": []}
        for n in range(attempts)
    ]
    guard.save_case(guard.case_path(ROOT, case_id), case)


def load(case_id: str) -> dict:
    case, _ = guard.load_case(ROOT, case_id)
    assert case is not None, case_id
    return case


def run(argv: list[str]) -> int:
    """Run the real CLI; argparse refusals (unknown flag or subcommand) count as code 2."""
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            return guard.cli(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2


def write_repo_file(relative: str, text: str) -> str:
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return relative


results: list[tuple[str, bool]] = []
OWNER = ".github/workflows/ci.yml"
CANON = "canon-case"

make_case(CANON, "IMPLEMENTING", [OWNER])
make_case("dup-a", "IMPLEMENTING", [OWNER])
make_case("dup-unshared", "IMPLEMENTING", ["docs/other.md"])
make_case("dup-verified", "VERIFIED", [OWNER])
make_case("dup-b", "IMPLEMENTING", [OWNER])

# --- supersede: positive path ------------------------------------------------
code = run(["supersede", "dup-a", "--by", CANON, "--reason", "same cause as canon-case"])
dup_a = load("dup-a")
record = dup_a.get("superseded") if isinstance(dup_a.get("superseded"), dict) else {}
results.append(("supersede by a same-repo canonical case returns 0", code == 0))
results.append(("supersede sets terminal status SUPERSEDED", dup_a.get("status") == "SUPERSEDED"))
results.append((
    "supersede records canonical, reason and timestamp",
    record.get("by_case") == CANON
    and record.get("reason") == "same cause as canon-case"
    and isinstance(record.get("recorded_at"), (int, float)),
))
results.append(("supersede records the shared owner path", record.get("shared_owner_paths") == [OWNER]))

open_blocking, _ = guard.unfinished_cases(ROOT, "unscoped")
open_ids = {case.get("id") for case, _ in open_blocking}
results.append(("SUPERSEDED case no longer blocks Stop", "dup-a" not in open_ids))
results.append(("open canonical still blocks Stop after supersede", CANON in open_ids))
results.append(("validate passes a well-formed SUPERSEDED case", run(["validate", "dup-a"]) == 0))
results.append((
    "a well-formed SUPERSEDED record has no validation errors",
    guard.validation_errors(dup_a, root=ROOT) == [],
))

# --- supersede: must-fail negatives -----------------------------------------
results.append((
    "supersede by a missing case is refused",
    run(["supersede", "dup-b", "--by", "no-such-case", "--reason", "x"]) != 0
    and load("dup-b")["status"] == "IMPLEMENTING",
))
results.append((
    "supersede by a case with no shared owner path is refused",
    run(["supersede", "dup-b", "--by", "dup-unshared", "--reason", "x"]) != 0
    and load("dup-b")["status"] == "IMPLEMENTING",
))
results.append((
    "supersede by an already VERIFIED canonical with a shared owner path is allowed",
    run(["supersede", "dup-b", "--by", "dup-verified", "--reason", "x"]) == 0,
))
results.append((
    "supersede of an already terminal case is refused",
    run(["supersede", "dup-a", "--by", CANON, "--reason", "again"]) != 0,
))
results.append((
    "supersede of a case by itself is refused",
    run(["supersede", CANON, "--by", CANON, "--reason", "self"]) != 0
    and load(CANON)["status"] == "IMPLEMENTING",
))

make_case("chain-x", "IMPLEMENTING", [OWNER])
make_case("chain-y", "IMPLEMENTING", [OWNER])
make_case("chain-z", "IMPLEMENTING", [OWNER])
results.append(("chain setup: x superseded by y", run(["supersede", "chain-x", "--by", "chain-y", "--reason", "dup"]) == 0))
results.append((
    "supersede chain is refused: canonical y is itself SUPERSEDED",
    run(["supersede", "chain-z", "--by", "chain-x", "--reason", "chain"]) != 0
    and load("chain-z")["status"] == "IMPLEMENTING",
))
results.append((
    "supersede cycle is refused: y cannot be superseded by x after x points at y",
    run(["supersede", "chain-y", "--by", "chain-x", "--reason", "cycle"]) != 0
    and load("chain-y")["status"] == "IMPLEMENTING",
))
results.append((
    "a canonical that already has superseded duplicates cannot itself be superseded",
    run(["supersede", "chain-y", "--by", CANON, "--reason", "reverse chain"]) != 0
    and load("chain-y")["status"] == "IMPLEMENTING",
))

# --- retriage: measured correction ------------------------------------------
make_case("retriage-canon", "IMPLEMENTING", [OWNER], attempts=0)
good = write_repo_file(
    ".agent/delivery-cases/retriage-canon/evidence/measured-correction.txt",
    "External prerequisite: none\nObserved: job log - restore 20m25s before go test; save 5m31s\n",
)
new_hypothesis = "corrected: cache round trips on the self-hosted runner exceed the timeout"
code = run([
    "retriage", "retriage-canon",
    "--causal-hypothesis", new_hypothesis,
    "--measured-correction", good,
])
case = load("retriage-canon")
history = case.get("history") or []
digest = hashlib.sha256((ROOT / good).read_bytes()).hexdigest()
results.append(("retriage with measured correction and zero attempts returns 0", code == 0))
results.append(("retriage with measured correction returns the case to ANALYZED", case.get("status") == "ANALYZED"))
results.append(("retriage with measured correction installs the corrected hypothesis", case["plan"]["causal_hypothesis"] == new_hypothesis))
results.append((
    "retriage with measured correction records hypothesis change, path and digest in history",
    any(
        item.get("event") == "retriage"
        and item.get("previous_hypothesis") == "hypothesis of retriage-canon"
        and item.get("causal_hypothesis") == new_hypothesis
        and item.get("evidence_path") == good
        and item.get("sha256") == digest
        for item in history
        if isinstance(item, dict)
    ),
))
write_repo_file(good, "Observed: changed after recording\n")
tamper_errors = guard.validation_errors(load("retriage-canon"), root=ROOT)
results.append((
    "a tampered measured-correction file fails validation",
    any("digest is stale" in error for error in tamper_errors),
))

make_case("retriage-noobs", "IMPLEMENTING", [OWNER], attempts=0)
no_obs = write_repo_file("retriage-noobs-correction.txt", "External prerequisite: none\nnote: nothing measured\n")
results.append((
    "measured correction without a labeled Observed line is refused",
    run(["retriage", "retriage-noobs", "--causal-hypothesis", "h2", "--measured-correction", no_obs]) != 0
    and load("retriage-noobs")["status"] == "IMPLEMENTING",
))
results.append((
    "measured correction outside the repository is refused",
    run(["retriage", "retriage-noobs", "--causal-hypothesis", "h2", "--measured-correction", str(OUTSIDE)]) != 0
    and load("retriage-noobs")["status"] == "IMPLEMENTING",
))

# --- retriage: unchanged two-attempt path -----------------------------------
make_case("retriage-one", "IMPLEMENTING", [OWNER], attempts=1)
results.append((
    "one failed attempt without a measured correction is still refused",
    run(["retriage", "retriage-one", "--expanded-owner-path", "src/new.py",
         "--causal-hypothesis", "h3"]) != 0
    and load("retriage-one")["status"] == "IMPLEMENTING",
))

make_case("retriage-two", "IMPLEMENTING", [OWNER], attempts=2)
code = run(["retriage", "retriage-two", "--expanded-owner-path", "src/new.py", "--causal-hypothesis", "h4"])
two = load("retriage-two")
results.append(("two failed attempts with a new owner boundary still retriage", code == 0))
results.append((
    "two-attempt retriage records no measured correction",
    "measured_correction" not in (two.get("retriage") or {}),
))
results.append((
    "two-attempt retriage without a new owner boundary is still refused",
    run(["retriage", "retriage-two", "--expanded-owner-path", OWNER, "--causal-hypothesis", "h5"]) != 0,
))

os.chdir(ORIGINAL_CWD)
failures = [label for label, passed in results if not passed]
for label, passed in results:
    print(f"  {'ok' if passed else 'FAIL'} {label}")
shutil.rmtree(TMP, ignore_errors=True)
if failures:
    print(f"{len(failures)} of {len(results)} wrong")
    raise SystemExit(1)
print(f"all {len(results)} checks correct")
