# -*- coding: utf-8 -*-
"""One session's unfinished delivery must not wedge another session.

Measured 2026-08-16: this session could neither end nor write a file in the hub,
because two OTHER sessions had open delivery intents and the working tree carried
1247 changed paths that this session never touched. Collateral of that shape is
what makes people switch a gate off, so the gate has to hold the session that
owns the delivery and let the others work.

What must NOT change: a session that owns an unresolved intent still has to
produce a delivery case. That is the whole point of the protocol.
"""
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import contextlib
import atexit
import shutil

TMP = pathlib.Path(tempfile.mkdtemp(prefix="delivery-guard-test-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
STATE = TMP / "state"
STATE.mkdir(parents=True, exist_ok=True)
os.environ["AGENT_ROOT_CAUSE_STATE_DIR"] = str(STATE)

REPO = TMP / "repo"
REPO.mkdir()
subprocess.run(["git", "init", "-q", str(REPO)], check=True, capture_output=True)
(REPO / "thing.py").write_text("print('someone else was here')\n", encoding="utf-8")

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
GUARD = HOOKS / "root-cause-delivery-guard.py"
spec = importlib.util.spec_from_file_location("delivery_guard", GUARD)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def record(session_id: str) -> None:
    g.record_intent(REPO, "incident", f"prompt from {session_id}", session_id=session_id)


def ran(fn, event) -> str:
    """Run a hook entry point and return whatever it printed (a block, or nothing)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            fn(event)
        except SystemExit:
            pass
    return buffer.getvalue().strip()


def blocked(output: str) -> bool:
    if not output:
        return False
    try:
        return json.loads(output).get("decision") == "block"
    except json.JSONDecodeError:
        return False


results = []

# 1. Another session owns an unresolved intent; mine owns none.
record("session-other")
os.chdir(REPO)
out_stop = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop, with only another session's intent open",
                False, blocked(out_stop)))

edit_event = {
    "session_id": "session-mine",
    "tool_name": "Write",
    "tool_input": {"file_path": str(REPO / "notes.py")},
}
out_edit = ran(g.pretool, edit_event)
results.append(("my source edit, with only another session's intent open",
                False, blocked(out_edit)))

patch_event = {
    "session_id": "session-mine",
    "cwd": str(REPO),
    "tool_name": "apply_patch",
    "tool_input": {"command": "*** Begin Patch\n*** Update File: thing.py\n@@\n-print('old')\n+print('new')\n*** End Patch"},
}
out_patch_other = ran(g.pretool, patch_event)
results.append(("my Codex apply_patch source edit, with only another session's intent open",
                False, blocked(out_patch_other)))

unparseable_patch_event = {
    "session_id": "session-mine",
    "cwd": str(REPO),
    "tool_name": "apply_patch",
    "tool_input": {"command": "this is not an apply patch document"},
}
out_unparseable_other = ran(g.pretool, unparseable_patch_event)
results.append(("my unparseable Codex apply_patch, with only another session's intent open",
                False, blocked(out_unparseable_other)))

# 2. The protocol itself must survive: MY intent, no case of mine.
record("session-mine")
out_mine = ran(g.pretool, edit_event)
results.append(("my source edit while I own an unresolved intent and no case",
                True, blocked(out_mine)))

out_patch_mine = ran(g.pretool, patch_event)
results.append(("my Codex apply_patch source edit while I own an unresolved intent and no case",
                True, blocked(out_patch_mine)))

out_unparseable_mine = ran(g.pretool, unparseable_patch_event)
results.append(("my unparseable Codex apply_patch while I own an unresolved intent and no case",
                True, blocked(out_unparseable_mine)))

docs_patch_event = {
    **patch_event,
    "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch"},
}
out_docs_patch = ran(g.pretool, docs_patch_event)
results.append(("my Codex apply_patch documentation edit while I own an unresolved intent",
                False, blocked(out_docs_patch)))

# 3. Owning an intent is not the same as having changed anything under it.
# Measured 2026-08-24: a session that only read a task and posted a comment was
# held at Stop because the hub tree carried .sh/.ps1/.json files last written
# three days earlier by other sessions. Attribution is by write time: dirt that
# predates the intent cannot be its product.
old = time.time() - 2 * 86400
os.utime(REPO / "thing.py", (old, old))
out_stop_pre_existing = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop while I own an intent, dirt written before it",
                False, blocked(out_stop_pre_existing)))

os.utime(REPO / "thing.py", None)
out_stop_mine = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop while I own an intent, source written after it and no case",
                True, blocked(out_stop_mine)))

# 4. A deleted file has no mtime. Measured 2026-11-03: another session's deletion,
# made before a letter-writing prompt, held that session's Stop. A file already
# missing when the intent was recorded is not the intent's product; a file deleted
# after it still is, and an intent recorded before this field existed stays fail-closed.
(REPO / "thing.py").unlink()
subprocess.run(["git", "-C", str(REPO), "add", "-A"], check=True, capture_output=True)
(REPO / "gone.py").write_text("x = 1\n", encoding="utf-8")
subprocess.run(["git", "-C", str(REPO), "add", "gone.py"], check=True, capture_output=True)
subprocess.run(["git", "-C", str(REPO), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base"],
               check=True, capture_output=True)
(REPO / "gone.py").unlink()
record("session-mine")
out_deleted_before = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop while I own an intent, source deleted before it",
                False, blocked(out_deleted_before)))

(REPO / "late.py").write_text("y = 2\n", encoding="utf-8")
subprocess.run(["git", "-C", str(REPO), "add", "late.py"], check=True, capture_output=True)
subprocess.run(["git", "-C", str(REPO), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "late"],
               check=True, capture_output=True)
record("session-mine")
(REPO / "late.py").unlink()
out_deleted_after = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop while I own an intent, source deleted after it and no case",
                True, blocked(out_deleted_after)))

legacy = json.loads(g.intent_path(REPO, "session-mine").read_text(encoding="utf-8"))
legacy.pop("missing_at_intent", None)
g._write_json(g.intent_path(REPO, "session-mine"), legacy)
out_legacy = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop with an intent recorded before missing_at_intent existed, a deleted source",
                True, blocked(out_legacy)))

# 5. A non-ASCII source file present at intent and edited after it must block.
# Independent review 2026-11-03: porcelain without -z C-quotes the path, the quoted
# string is not on disk, so the file was recorded as "missing" and its edit skipped.
cyr = REPO / "тест.py"
cyr.write_text("a = 1\n", encoding="utf-8")
subprocess.run(["git", "-C", str(REPO), "add", "-A"], check=True, capture_output=True)
subprocess.run(["git", "-C", str(REPO), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "cyr"],
               check=True, capture_output=True)
cyr.write_text("a = 2\n", encoding="utf-8")
old = time.time() - 2 * 86400
os.utime(cyr, (old, old))
record("session-mine")
cyr.write_text("a = 3\n", encoding="utf-8")
out_cyr = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop while I own an intent, non-ASCII source present at intent and edited after it",
                True, blocked(out_cyr)))

# 6. Renames (second independent review 2026-11-03): the source path of a rename
# is a change. `git mv` keeps the mtime, so a rename after the intent was only
# visible through the renamed-away source path.
cyr.write_text("a = 1\n", encoding="utf-8")
subprocess.run(["git", "-C", str(REPO), "add", "-A"], check=True, capture_output=True)
subprocess.run(["git", "-C", str(REPO), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "clean"],
               check=True, capture_output=True)
(REPO / "keep.py").write_text("k = 1\n", encoding="utf-8")
subprocess.run(["git", "-C", str(REPO), "add", "keep.py"], check=True, capture_output=True)
subprocess.run(["git", "-C", str(REPO), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "keep"],
               check=True, capture_output=True)
os.utime(REPO / "keep.py", (old, old))
record("session-mine")
subprocess.run(["git", "-C", str(REPO), "mv", "keep.py", "moved.py"], check=True, capture_output=True)
os.utime(REPO / "moved.py", (old, old))
out_renamed = ran(g.stop, {"session_id": "session-mine"})
results.append(("my Stop while I own an intent, source renamed after it (old mtime kept)",
                True, blocked(out_renamed)))
results.append(("git_source_changes lists both sides of a staged rename",
                True, {"keep.py", "moved.py"} <= set(g.git_source_changes(REPO))))

subprocess.run(["git", "-C", str(REPO), "mv", "moved.py", "keep.py"], check=True, capture_output=True)
(REPO / "ita.py").write_text("i = 1\n", encoding="utf-8")
subprocess.run(["git", "-C", str(REPO), "add", "-N", "ita.py"], check=True, capture_output=True)
(REPO / "keep.py").rename(REPO / "renamed.py")
subprocess.run(["git", "-C", str(REPO), "add", "-N", "renamed.py"], check=True, capture_output=True)
listed = set(g.git_source_changes(REPO))
results.append(("git_source_changes parses an intent-to-add rename without garbage paths",
               True, listed <= {"ita.py", "renamed.py", "keep.py"} and "renamed.py" in listed))

failures = [r for r in results if r[1] != r[2]]
for label, expected, got in results:
    print(f"  {'ok  ' if expected == got else 'FAIL'} expected={'block' if expected else 'pass':<5} "
          f"got={'block' if got else 'pass':<5} {label}")
print()
if failures:
    print(f"{len(failures)} of {len(results)} wrong")
    sys.exit(1)
print(f"all {len(results)} cases correct")
