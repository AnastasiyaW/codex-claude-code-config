"""Replay real hook events through the hook process's stdin, as Claude Code invokes it."""
import json, os, pathlib, subprocess, sys, tempfile, time

hook = pathlib.Path(sys.argv[1]).resolve()
assert hook.is_file(), hook
# The transcript is named by the caller, not baked in: this file is public, and
# a project directory name carries the machine's user and folder layout. Pass
# it as the second argument or in REPLAY_TRANSCRIPT.
transcript_arg = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("REPLAY_TRANSCRIPT", "")
assert transcript_arg, "give the transcript path as argv[2] or REPLAY_TRANSCRIPT"
transcript = pathlib.Path(transcript_arg).expanduser()
assert transcript.is_file(), transcript
notification = None
for line in transcript.open(encoding="utf-8", errors="replace"):
    if "b5jhe7jfl" in line and "queued_command" in line:
        notification = json.loads(line)["attachment"]["prompt"]
        break
assert notification and notification.startswith("<task-notification>"), "real notification not found"

work = pathlib.Path(tempfile.mkdtemp(prefix="replay-", dir=os.environ["REPLAY_TMP"]))
state = work / "state"; state.mkdir()
repo = work / "repo"; repo.mkdir()
subprocess.run(["git", "init", "-q", str(repo)], check=True)
env = dict(os.environ, AGENT_ROOT_CAUSE_STATE_DIR=str(state))
session = "replay-session-0001"
base = {"session_id": session, "transcript_path": str(transcript), "cwd": str(repo), "permission_mode": "bypassPermissions"}

def run(event):
    r = subprocess.run([sys.executable, str(hook)], input=json.dumps(event), capture_output=True,
                       text=True, encoding="utf-8", cwd=repo, env=env, timeout=60)
    if r.returncode != 0:
        raise SystemExit(f'hook process failed rc={r.returncode}: {r.stderr.strip()[:300]}')
    return r.returncode, r.stdout.strip()

def intent_id():
    files = list(state.glob("*.json"))
    return json.loads(files[0].read_text(encoding="utf-8"))["intent_id"] if files else None

def prompt(text):
    return run({**base, "hook_event_name": "UserPromptSubmit", "prompt": text})

write_event = {**base, "hook_event_name": "PreToolUse", "tool_name": "Write",
               "tool_input": {"file_path": str(repo / "service.py"), "content": "print('fixed')\n"}}

def blocked():
    rc, out = run(write_event)
    return bool(out) and json.loads(out).get("decision") == "block"

lines = []
prompt("The deploy script crashes with an error on start, fix this")
owner = intent_id()
lines.append(f"owner prompt recorded intent: {owner is not None}")
lines.append(f"PreToolUse Write with owner intent and no case -> blocked: {blocked()}")
rc, out = prompt(notification)
lines.append(f"real notification b5jhe7jfl -> hook printed an intent receipt: {'intent' in out}; intent id unchanged: {intent_id() == owner}")
case = {"schema_version": 1, "id": "owner-case", "intent_id": owner, "session_id": session, "builder": session,
        "kind": "incident", "status": "PLAN_FROZEN", "summary": "owner incident", "created_at": time.time(), "updated_at": time.time(),
        "observed": {"expected": "deploy passes", "actual": "deploy crashes"},
        "layer": {"entrypoints": ["service.py::main"], "owner_paths": ["service.py"], "direct_dependents": ["deploy"],
                  "state_or_contract": ["exit status"], "tests_or_probes": ["python -m pytest"], "release_boundary": "not-applicable"},
        "plan": {"causal_hypothesis": "missing guard", "fix_steps": ["add the guard"], "focused_argv": ["python", "-m", "pytest"]},
        "verification": {"before": {"argv": ["python", "-m", "pytest"], "returncode": 1}}, "attempts": [], "release": {"required": False}}
path = repo / ".agent/delivery-cases/owner-case/case.json"; path.parent.mkdir(parents=True); path.write_text(json.dumps(case), encoding="utf-8")
lines.append(f"PreToolUse Write with a PLAN_FROZEN case bound to the owner intent -> blocked: {blocked()}")
prompt(notification)
lines.append(f"after replaying the notification again, PreToolUse Write -> blocked: {blocked()}")
print("\n".join(lines))
