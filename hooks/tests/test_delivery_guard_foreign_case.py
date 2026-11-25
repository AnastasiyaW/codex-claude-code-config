# -*- coding: utf-8 -*-
"""Stop is held only by this session's own unfinished delivery case.

Measured 2026-11-25 in the Claude_code hub: case chain-weave-classifier-20261125
(IMPLEMENTING, owner fd4ebf92) held the Stop of every other session. Its owner's
transcript had been quiet for more than the 30-minute liveness window, so the
case read as abandoned and blocked everyone until each session spent its three
refusals. The rule those sessions follow forbids editing another session's case,
so the block had no legitimate exit.

Contract checked here, through the real hook entry point (subprocess, Stop event
on stdin):
  - a foreign case never blocks, live owner or quiet owner;
  - a case whose owner cannot be determined never blocks, and says so on stderr;
  - this session's own unfinished case still blocks (negative control), also
    when the owner is recorded as a shortened id or only through this session's
    intent.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
GUARD = HOOKS / "root-cause-delivery-guard.py"

ME = "11111111-aaaa-4bbb-8ccc-000000000001"
OTHER = "22222222-aaaa-4bbb-8ccc-000000000002"
QUIET = "33333333-aaaa-4bbb-8ccc-000000000003"


def setup(case: dict | None, transcripts: dict[str, float]) -> tuple[pathlib.Path, dict[str, str]]:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rcd-foreign-"))
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    sessions = tmp / "projects" / "proj"
    sessions.mkdir(parents=True)
    now = time.time()
    for sid, age in transcripts.items():
        path = sessions / f"{sid}.jsonl"
        path.write_text("{}\n", encoding="utf-8")
        os.utime(path, (now - age, now - age))
    if case is not None:
        folder = repo / ".agent" / "delivery-cases" / case["id"]
        folder.mkdir(parents=True)
        (folder / "case.json").write_text(json.dumps(case), encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("CODEX_SESSION_ID", "AGENT_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")}
    env["CLAUDE_SESSION_ROOT"] = str(tmp / "projects")
    env["AGENT_ROOT_CAUSE_STATE_DIR"] = str(tmp / "state")
    return repo, env


def open_case(case_id: str, **owner: str) -> dict:
    case = {"schema_version": 1, "id": case_id, "kind": "incident", "status": "IMPLEMENTING",
            "summary": "s", "updated_at": time.time(), "intent_id": owner.pop("intent_id", None)}
    case.update(owner)
    return case


def stop(repo: pathlib.Path, env: dict[str, str], session: str | None) -> tuple[bool, str]:
    event = {"hook_event_name": "Stop"}
    if session is not None:
        event["session_id"] = session
    proc = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), cwd=repo, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    blocked = '"decision": "block"' in proc.stdout
    return blocked, proc.stderr


def write_intent(env: dict[str, str], repo: pathlib.Path, session: str, intent_id: str) -> None:
    state = pathlib.Path(env["AGENT_ROOT_CAUSE_STATE_DIR"])
    state.mkdir(parents=True, exist_ok=True)
    (state / f"{intent_id}.json").write_text(json.dumps({
        "schema_version": 1, "intent_id": intent_id, "kind": "incident", "root": str(repo.resolve()),
        "session_id": session, "recorded_at": time.time(), "expires_at": time.time() + 3600,
    }), encoding="utf-8")


results: list[tuple[str, bool]] = []
cleanup: list[pathlib.Path] = []


def check(name: str, case: dict | None, transcripts: dict[str, float], session: str | None,
          want_block: bool, stderr_has: str = "", intent: tuple[str, str] | None = None) -> None:
    repo, env = setup(case, transcripts)
    cleanup.append(repo.parent)
    if intent:
        write_intent(env, repo, *intent)
    blocked, err = stop(repo, env, session)
    ok = blocked == want_block and (stderr_has.lower() in err.lower())
    results.append((name, ok))
    if not ok:
        print(f"   blocked={blocked} stderr={err.strip()[:300]!r}")


check("foreign case, owner quiet past the liveness window: does not block",
      open_case("foreign-quiet", session_id=QUIET, builder=QUIET), {QUIET: 7200, ME: 0}, ME,
      want_block=False, stderr_has=QUIET[:8])
check("foreign case, owner has no transcript at all: does not block",
      open_case("foreign-gone", session_id=OTHER, builder=OTHER), {ME: 0}, ME,
      want_block=False, stderr_has=OTHER[:8])
check("foreign case, owner live: does not block",
      open_case("foreign-live", session_id=OTHER, builder=OTHER), {OTHER: 0, ME: 0}, ME,
      want_block=False, stderr_has=OTHER[:8])
check("case without any owner: does not block, stderr says owner not checked",
      open_case("no-owner"), {ME: 0}, ME, want_block=False, stderr_has="owner unknown")
check("case owned by 'unscoped': does not block, stderr says owner not checked",
      open_case("unscoped-owner", session_id="unscoped", builder="unscoped"), {ME: 0}, ME,
      want_block=False, stderr_has="owner unknown")
check("Stop event without a session id: own-looking case does not block, stderr says not checked",
      open_case("who-am-i", session_id=ME, builder=ME), {ME: 0}, None,
      want_block=False, stderr_has="not checked")
# negative controls: protection of one's own cases must not weaken
check("own unfinished case still blocks",
      open_case("mine", session_id=ME, builder=ME), {ME: 0}, ME, want_block=True)
check("own case recorded with a shortened id still blocks",
      open_case("mine-short", session_id=ME[:8]), {ME: 0}, ME, want_block=True)
check("own case recorded only through this session's intent still blocks",
      open_case("mine-intent", intent_id="abc123abc123"), {ME: 0}, ME, want_block=True,
      intent=(ME, "abc123abc123"))
check("own case whose own transcript is quiet still blocks",
      open_case("mine-quiet", session_id=ME, builder=ME), {ME: 7200}, ME, want_block=True)

for path in cleanup:
    shutil.rmtree(path, ignore_errors=True)
failed = [name for name, ok in results if not ok]
for name, ok in results:
    print(("PASS " if ok else "FAIL ") + name)
print(f"{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
