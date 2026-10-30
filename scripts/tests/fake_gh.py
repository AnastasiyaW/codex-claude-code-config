"""A fake `gh` executable for safe_merge tests.

Answers from the scenario in $FAKE_GH_SCENARIO (see safe_merge.ScenarioGh) and keeps the
call log and the merged/ref-read state in $FAKE_GH_STATE, because every gh call is a new
process. $SAFE_MERGE_DIR names the folder holding the safe_merge.py under test.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "safe_merge", Path(os.environ["SAFE_MERGE_DIR"]) / "safe_merge.py")
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)

state_path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
gh = sm.ScenarioGh(json.loads(Path(os.environ["FAKE_GH_SCENARIO"]).read_text(encoding="utf-8")))
gh.calls = state.get("calls", [])
gh.merged = state.get("merged", False)
gh.ref_reads = state.get("ref_reads", 0)
code, out, err = gh.answer(sys.argv[1:])
state_path.write_text(json.dumps({"calls": gh.calls, "merged": gh.merged,
                                  "ref_reads": gh.ref_reads}), encoding="utf-8")
sys.stdout.write(out)
sys.stderr.write(err)
sys.exit(code)
