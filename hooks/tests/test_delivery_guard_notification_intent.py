# -*- coding: utf-8 -*-
"""A background-task notification is not the owner's delivery intent.

Measured 2026-09-15: Claude Code delivers a finished background task through the
same UserPromptSubmit event as a human prompt. Its text is a bare
<task-notification> element (1492 of 1492 notification records in the local
transcripts start with it at byte 0, nothing follows the closing tag; a live
probe matched the recorded intent digest to that raw text). The words inside it
- "failed", "error", "completed" - matched the incident patterns, and because
intent state is one file per (repository, session), each notification replaced
the session's real intent. A case frozen under the owner's intent id then
stopped matching, and every source edit was blocked "without a valid
PLAN_FROZEN case" while one existed.

What must NOT change: genuine owner prompts, in either language, still record an
intent, and an owner intent with no frozen case still blocks source edits.
"""
import atexit
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

TMP = pathlib.Path(tempfile.mkdtemp(prefix="delivery-guard-notification-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
STATE = TMP / "state"
STATE.mkdir(parents=True, exist_ok=True)
os.environ["AGENT_ROOT_CAUSE_STATE_DIR"] = str(STATE)

REPO = TMP / "repo"
REPO.mkdir()
subprocess.run(["git", "init", "-q", str(REPO)], check=True, capture_output=True)

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location("delivery_guard", HOOKS / "root-cause-delivery-guard.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

SESSION = "session-owner"
# Shape copied from a real record: the fields a completed or failed background
# task carries, with the incident words the old classifier caught.
NOTIFICATION = (
    "<task-notification>\n"
    "<task-id>bwujs3efm</task-id>\n"
    "<tool-use-id>toolu_01GxKM5iBY8fCvPLjoMUQoyy</tool-use-id>\n"
    "<output-file>tasks/bwujs3efm.output</output-file>\n"
    "<status>failed</status>\n"
    "<summary>Background command \"Build and deploy the fix\" failed (exit code 1)</summary>\n"
    "<result>error: build broken, regression in the release step</result>\n"
    "</task-notification>"
)
# The same event as the model sees it rendered inside the harness marker.
WRAPPED_NOTIFICATION = (
    "<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\n"
    "This is an automated background-task event, NOT a message from the user.\n\n"
    + NOTIFICATION + "\n</system-reminder>"
)
# A real owner prompt in the desktop app arrives with harness reminders in front.
WORKTREE_REMINDER = "<system-reminder>\nYou are operating in a git worktree.\n</system-reminder>\n"


def submit(prompt: str) -> None:
    os.chdir(REPO)
    with contextlib.redirect_stdout(io.StringIO()):
        g.handle_hook({"session_id": SESSION, "hook_event_name": "UserPromptSubmit", "prompt": prompt})


def current_intent() -> dict | None:
    return g.active_intent(REPO.resolve(), SESSION)


def reset() -> None:
    for path in STATE.glob("*.json"):
        path.unlink()
    shutil.rmtree(REPO / ".agent", ignore_errors=True)


def edit_blocked() -> bool:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        g.pretool({"session_id": SESSION, "tool_name": "Write",
                   "tool_input": {"file_path": str(REPO / "service.py")}})
    output = buffer.getvalue().strip()
    return bool(output) and json.loads(output).get("decision") == "block"


def freeze_case_for(intent_id: str) -> None:
    now = time.time()
    case = {
        "schema_version": 1, "id": "owner-case", "intent_id": intent_id,
        "session_id": SESSION, "builder": SESSION, "kind": "incident",
        "status": "PLAN_FROZEN", "summary": "owner incident",
        "created_at": now, "updated_at": now,
        "observed": {"expected": "deploy passes", "actual": "deploy crashes"},
        "layer": {
            "entrypoints": ["service.py::main"], "owner_paths": ["service.py"],
            "direct_dependents": ["deploy"], "state_or_contract": ["exit status"],
            "tests_or_probes": ["python -m pytest"], "release_boundary": "not-applicable",
        },
        "plan": {"causal_hypothesis": "missing guard", "fix_steps": ["add the guard"],
                 "focused_argv": ["python", "-m", "pytest"]},
        "verification": {"before": {"argv": ["python", "-m", "pytest"], "returncode": 1}},
        "attempts": [], "release": {"required": False},
    }
    path = REPO / ".agent" / "delivery-cases" / "owner-case" / "case.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(case), encoding="utf-8")


results = []


def check(label: str, expected, got) -> None:
    results.append((label, expected, got))


# 1. Genuine owner prompts still record, in both languages.
reset()
submit("Сборка падает с ошибкой после обновления, почини")
check("Russian incident prompt records an intent", "incident", (current_intent() or {}).get("kind"))

reset()
submit("The deploy script crashes with an error on start, fix this")
check("English incident prompt records an intent", "incident", (current_intent() or {}).get("kind"))

reset()
submit(WORKTREE_REMINDER + "The release job is broken, fix this")
check("owner prompt behind an unrelated system-reminder records", "incident",
      (current_intent() or {}).get("kind"))

reset()
submit("Why did the task-notification say failed? Fix this error in the parser")
check("prompt quoting task-notification mid-text records", "incident",
      (current_intent() or {}).get("kind"))

reset()
submit("The deploy is broken, fix this. The task only reported:\n"
       "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>")
check("owner text written before a pasted notification records", "incident",
      (current_intent() or {}).get("kind"))

reset()
submit(NOTIFICATION + "\n\nThe build is broken again, fix this")
check("owner text written after a pasted notification records", "incident",
      (current_intent() or {}).get("kind"))

# 2. Notifications record nothing.
reset()
submit(NOTIFICATION)
check("task-notification containing failed/error records nothing", None, current_intent())

reset()
submit("\n  " + NOTIFICATION)
check("task-notification after leading whitespace records nothing", None, current_intent())

# An opening tag or marker with no notification body closing after it is not a
# notification we can prove; it fails closed to the old classification.
reset()
submit(NOTIFICATION[: NOTIFICATION.index("</result>")])
check("unclosed task-notification keeps the old classification", "incident",
      (current_intent() or {}).get("kind"))

reset()
submit("<task-notification> events overwrite the delivery intent - fix this bug")
check("owner prompt opening with a literal unclosed tag records", "incident",
      (current_intent() or {}).get("kind"))
check("... and blocks a source edit without a case", True, edit_blocked())

reset()
submit("<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\nmonitor event\n</system-reminder>\n"
       "the parser crashes, fix this")
check("owner text after a marker wrapper with no notification body records", "incident",
      (current_intent() or {}).get("kind"))

reset()
submit("[SYSTEM NOTIFICATION - NOT USER INPUT] shows up in my prompt and the hook crashes, fix this")
check("owner prompt opening with the bare marker records", "incident",
      (current_intent() or {}).get("kind"))

# The same owner prompts quoting the closing tag later: a tag and a closing tag
# are not a notification without the child element the runtime always writes.
reset()
submit("<task-notification> events break the delivery guard, fix this bug. The element ends with </task-notification>")
check("owner prompt opening with the tag and quoting its close records", "incident",
      (current_intent() or {}).get("kind"))
check("... and blocks a source edit without a case", True, edit_blocked())

reset()
submit("<task-notification> ломает гейт, почини. Пример закрытия: </task-notification>")
check("Russian owner prompt opening with the tag and quoting its close records", "incident",
      (current_intent() or {}).get("kind"))

reset()
submit("[SYSTEM NOTIFICATION - NOT USER INPUT] the hook crashes, fix this; it strips up to </task-notification>")
check("owner prompt opening with the marker and quoting the close records", "incident",
      (current_intent() or {}).get("kind"))

reset()
submit("<task-notification> implement a parser for this element and its </task-notification>")
check("change prompt opening with the tag and quoting its close records", "change",
      (current_intent() or {}).get("kind"))

reset()
submit(WRAPPED_NOTIFICATION)
check("notification inside the SYSTEM NOTIFICATION marker records nothing", None, current_intent())

# 3. The reported failure: a notification must not replace the owner's intent.
reset()
submit("The deploy script crashes with an error on start, fix this")
owner_id = (current_intent() or {}).get("intent_id")
submit(NOTIFICATION)
check("notification leaves the owner's intent id in place", owner_id,
      (current_intent() or {}).get("intent_id"))

# 4. The gate is not weakened, and a frozen case survives a notification.
reset()
submit("The deploy script crashes with an error on start, fix this")
check("owner intent with no case blocks a source edit", True, edit_blocked())
submit(NOTIFICATION)
check("... and still blocks after a notification", True, edit_blocked())
freeze_case_for(str((current_intent() or {}).get("intent_id")))
check("owner intent with a frozen case allows the edit", False, edit_blocked())
submit(NOTIFICATION)
check("... and still allows it after a notification", False, edit_blocked())

failures = [r for r in results if r[1] != r[2]]
for label, expected, got in results:
    print(f"  {'ok  ' if expected == got else 'FAIL'} {label}"
          + ("" if expected == got else f" (expected {expected!r}, got {got!r})"))
print()
if failures:
    print(f"{len(failures)} of {len(results)} wrong")
    sys.exit(1)
print(f"all {len(results)} cases correct")
