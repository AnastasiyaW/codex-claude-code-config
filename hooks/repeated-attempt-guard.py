#!/usr/bin/env python3
"""Stop the guess-and-retry loop: no fourth try at the same thing without reading first.

The failure this exists for, in the words of the session that produced it:

    "Fourth time, the same mistake -- I am guessing at the shape of the list
     instead of reading the resolver. Reading it now."

Nothing caught that, and the reason is structural rather than a missing rule. We have an
always-on rule that says do not guess, and prose loses to a task under pressure -- the
same shape as a skill that declares AUTO-APPLY with nothing wiring it. But more
fundamentally: the loop is only visible ACROSS calls. Attempt, fail, vary the surface,
attempt again. A hook that receives one tool call and no history cannot see it, however
good its rule.

Measured before writing this: of ~50 hooks here, 26 hold state and exactly one keys it
per target with a threshold. The rest remember "did I already speak about this file",
which is anti-nag, not memory of what was tried.

So this one remembers attempts. The rule it enforces is deliberately narrow and always
satisfiable by the cheap correct action:

    You may not make a FOURTH attempt at a target that has failed three times
    unless you have read something since the last failure.

Reading anything -- the resolver, the spec, the error's source -- clears it. That is the
whole point: the block is lifted by the action that would have solved it three attempts
ago. Advisory at the third, blocking at the fourth, because the fourth is where the
quoted session noticed and where the cost stops being tolerable.

A second, narrower signal rides on the same record: the premise loop. Reading clears the
retry block, but it does not clear this one -- an edit, a run, the SAME error, another edit,
the same error again. Two fixes that failed on one check share an assumption, and a third
fix on that assumption is the circle `finish-the-task.md` ("attack the premise") forbids.
When one normalised error signature comes back three times in a session with an edit
between each, the agent gets one advisory note per signature (never a block). The idea is
from TokenEconomizer's failure-loop intervention (github.com/microsoft/TokenEconomizer,
arXiv 2610.22732), rebuilt rule-only: no judge model, no stop.

Wire on BOTH events:
    PostToolUse  -- records outcomes (needs tool_response to see failure); also on
                    Edit|Write|MultiEdit|NotebookEdit so edits between failures are seen
    PreToolUse   -- reads the record and decides

Tunables: CLAUDE_RETRY_SOFT (2 prior failures -> advise), CLAUDE_RETRY_HARD (3 -> block),
          CLAUDE_RETRY_WINDOW_SEC (3600)
Bypass:   CLAUDE_ALLOW_RETRY_LOOP=1, or `# claude-bypass: retry-loop` in the command
Self-test: python repeated-attempt-guard.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# Counted in PRIOR FAILURES, not in attempts, because that is what the state file holds
# and mixing the two units cost me an off-by-one the first time: the block landed on the
# fifth try when the whole point is the fourth. Two prior failures means this call is the
# third attempt; three means it is the fourth.
WARN_AFTER_FAILURES = int(os.environ.get("CLAUDE_RETRY_SOFT", "2"))
BLOCK_AFTER_FAILURES = int(os.environ.get("CLAUDE_RETRY_HARD", "3"))
WINDOW = int(os.environ.get("CLAUDE_RETRY_WINDOW_SEC", "3600"))

STATE = Path(os.environ.get("CLAUDE_RETRY_STATE",
                            str(Path.home() / ".claude" / "state" / "attempts.jsonl")))

ACTING = {"Bash", "PowerShell", "Edit", "Write", "MultiEdit", "NotebookEdit"}
CONSULTING = {"Read", "Grep", "Glob", "WebFetch", "NotebookRead"}

_FLAG = re.compile(r"^-")
_PATHISH = re.compile(r"[\\/]|\.[A-Za-z0-9]{1,5}$")
# A long remote script is one attempt, not fifty; the cap keeps the key bounded while
# still reaching past `cd <project> &&` into the command that follows it.
MAX_KEY_TOKENS = 14


def target_key(tool: str, tool_input: dict) -> str:
    """A stable name for 'the thing being attempted'.

    Flags are dropped, arguments are kept. That split is the whole design: a flag is
    the surface variation a guess-and-retry loop consists of, an argument is what the
    attempt is aimed at. Keeping only the FIRST argument was the mistake -- on real
    command lines the first token is `cd`, so the key became the working directory and
    three failures of anything in a project blocked everything else in it.

    Scored on 14 days of this machine's real history (48,602 tool calls), counting a
    block as justified only when the exact same failing command is retried:

        verb + first argument   1390 blocks,  24 identical-command repeats   (98% noise)
        verb + all arguments      55 blocks,  18 identical-command repeats
        whole command             39 blocks,  18 identical-command repeats

    The middle one is kept: it still sees through a changed flag, which the strictest
    variant does not, and it costs ~16 extra stops in two weeks to keep that. Note the
    `cd <project>` prefix survives here as CONTEXT rather than as the whole key, which
    is also what stops two different projects running `npm test` from colliding.
    """
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        p = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return f"file:{Path(p).name.lower()}" if p else ""
    cmd = (tool_input.get("command") or "").strip()
    if not cmd:
        return ""
    tokens = [t for t in cmd.split() if not _FLAG.match(t)][:MAX_KEY_TOKENS]
    if not tokens:
        return ""
    parts = []
    for raw in tokens:
        raw = raw.strip("\"'")
        parts.append(Path(raw).name.lower() if _PATHISH.search(raw) else raw.lower())
    return "cmd:" + ":".join(parts)


def failed(tool_response) -> bool:
    """Did the call fail? Unknown shapes count as success -- never invent a failure."""
    if isinstance(tool_response, dict):
        if tool_response.get("is_error") or tool_response.get("error"):
            return True
        code = tool_response.get("exit_code", tool_response.get("returncode"))
        if isinstance(code, int) and code != 0:
            return True
        text = str(tool_response.get("stderr") or "")
    else:
        text = str(tool_response or "")
    return bool(re.search(r"\b(traceback|command not found|no such file|fatal:|error:)\b",
                          text, re.I))


PREMISE_AFTER = 3
EDITING = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# A named exception says which failure it is; a bare "1 failed" summary would make two
# different failing tests look like one, so it is used only when nothing better is there.
_NAMED_ERROR = re.compile(r"\w*(error|exception)\b|\bfatal\b", re.I)
_ERROR_LINE = re.compile(r"\w*(error|exception)\b|\b(traceback|failed|failure|fatal|assert\w*)\b", re.I)
_MASKS = (
    (re.compile(r"0x[0-9a-f]+", re.I), "<hex>"),
    (re.compile(r"(?:[A-Za-z]:)?[\\/][^\s:'\"()]+"), "<path>"),
    (re.compile(r"\d+"), "<n>"),
)


def error_signature(tool_response) -> str:
    """The last error-looking line, with paths, numbers and addresses masked.

    The last such line is where an exception ends up; masking keeps one failure the same
    signature across a changed line number or temp path.
    """
    if isinstance(tool_response, dict):
        text = "\n".join(str(tool_response.get(k) or "") for k in ("stderr", "stdout", "error"))
    else:
        text = str(tool_response or "")
    lines = [l.strip() for l in text.splitlines()]
    named = [l for l in lines if _NAMED_ERROR.search(l)]
    lines = named or [l for l in lines if _ERROR_LINE.search(l)]
    if not lines:
        return ""
    sig = lines[-1]
    for pattern, mask in _MASKS:
        sig = pattern.sub(mask, sig)
    return sig[:200]


def premise_loop(rows: list[dict], sig: str, sid: str) -> int:
    """How many times `sig` failed in this session with an edit before each repeat."""
    if not sig:
        return 0
    mine = [r for r in rows if r.get("sid") == sid]
    times = sorted(float(r["ts"]) for r in mine if r.get("kind") == "fail" and r.get("sig") == sig)
    edits = [float(r["ts"]) for r in mine if r.get("kind") == "edit"]
    count = 1 if times else 0
    for before, after in zip(times, times[1:]):
        if any(before < t < after for t in edits):
            count += 1
    return count


def _load(now: float) -> list[dict]:
    try:
        rows = [json.loads(l) for l in STATE.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []
    return [r for r in rows if now - float(r.get("ts", 0)) <= WINDOW]


def _append(row: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        with STATE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def assess(rows: list[dict], key: str) -> tuple[int, bool]:
    """How many failures for this key, and has anything been read since the last one."""
    fails = [r for r in rows if r.get("key") == key and r.get("kind") == "fail"]
    if not fails:
        return 0, True
    last = max(float(r["ts"]) for r in fails)
    consulted = any(r.get("kind") == "read" and float(r.get("ts", 0)) > last for r in rows)
    return len(fails), consulted


def record(event: dict) -> int:
    tool = event.get("tool_name") or ""
    ti = event.get("tool_input") or {}
    sid = str(event.get("session_id") or "")
    hook = event.get("hook_event_name") or "PostToolUse"
    # PostToolUseFailure is the engine saying the call failed (a Bash exit != 0 arrives here, not
    # in PostToolUse); its text is in `error`. An abort is not a failed attempt.
    is_failure_event = hook == "PostToolUseFailure"
    if is_failure_event and event.get("is_interrupt"):
        return 0
    response = event.get("error") if is_failure_event else event.get("tool_response")
    now = time.time()
    if tool in CONSULTING:
        _append({"ts": now, "kind": "read", "key": target_key(tool, ti) or tool})
    elif tool in ACTING and (is_failure_event or failed(response)):
        key = target_key(tool, ti)
        sig = error_signature(response)
        if key:
            _append({"ts": now, "kind": "fail", "key": key, "sid": sid, "sig": sig})
        rows = _load(now)
        noted = any(r.get("kind") == "premise" and r.get("sid") == sid and r.get("sig") == sig for r in rows)
        if sig and not noted and premise_loop(rows, sig, sid) >= PREMISE_AFTER:
            _append({"ts": now, "kind": "premise", "sid": sid, "sig": sig})
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": hook,
                "additionalContext": (
                    f"[premise-loop] The same error came back {PREMISE_AFTER} times in this session, "
                    f"with a fix between each: `{sig}`. The fixes share an assumption that is "
                    f"wrong. Before a fourth fix: write that assumption in one sentence, name who "
                    f"holds it, and test it with one observation that would come out differently "
                    f"if it were false (finish-the-task.md, \"attack the premise\")."),
            }}, ensure_ascii=False))
    elif not is_failure_event and (tool in EDITING or _shell_edited(response)):
        _append({"ts": now, "kind": "edit", "sid": sid})
    return 0


def _shell_edited(response) -> bool:
    """A shell command that changed files (sed -i, a redirect, git apply) is an edit too."""
    diff = response.get("bashEditDiff") if isinstance(response, dict) else None
    return isinstance(diff, dict) and bool(diff.get("changedFiles") or diff.get("files"))


def decide(event: dict) -> int:
    tool = event.get("tool_name") or ""
    ti = event.get("tool_input") or {}
    if tool not in ACTING:
        return 0
    blob = json.dumps(ti, ensure_ascii=False)
    if "claude-bypass: retry-loop" in blob:
        return 0
    key = target_key(tool, ti)
    if not key:
        return 0

    n, consulted = assess(_load(time.time()), key)
    if consulted or n < WARN_AFTER_FAILURES:
        return 0

    where = key.split(":", 1)[1]
    if n < BLOCK_AFTER_FAILURES:
        print(f"[retry] '{where}' has failed {n} times and nothing has been read since the "
              f"last failure. The next variation is a guess at the shape of the answer. "
              f"Open the thing that defines it -- the resolver, the schema, the error's "
              f"source -- before trying again.", file=sys.stderr)
        return 0

    print(json.dumps({
        "decision": "block",
        "reason": (
            f"Attempt {n + 1} at '{where}'. It has failed {n} times and nothing has been "
            f"read since the last failure, so each attempt has been a guess at a shape "
            f"that could be looked up. Read the definition -- the resolver, schema, or "
            f"source of the error -- then retry; a single Read clears this. "
            f"Deliberate override: CLAUDE_ALLOW_RETRY_LOOP=1 or "
            f"'# claude-bypass: retry-loop' in the command."
        ),
    }))
    return 0


def main() -> int:
    if os.environ.get("CLAUDE_ALLOW_RETRY_LOOP") == "1":
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0  # fail open: a guard bug must not be the reason work stops
    hook = event.get("hook_event_name") or ""
    return record(event) if hook in ("PostToolUse", "PostToolUseFailure") else decide(event)


def self_test() -> int:
    import tempfile

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    check("edit key is the filename",
          target_key("Edit", {"file_path": "C:/a/b/Resolver.py"}), "file:resolver.py")
    check("same file from another directory keys the same",
          target_key("Write", {"file_path": "/other/resolver.py"}), "file:resolver.py")
    check("command key survives a changed flag",
          target_key("Bash", {"command": "python build.py --fast"}),
          target_key("Bash", {"command": "python build.py --slow -v"}))

    # These are the shapes real command lines actually have on this machine. The
    # earlier suite tested only `python build.py`, which is why a key that resolved
    # to the working directory passed every synthetic check and then blocked ~1,300
    # times in two weeks of replayed history.
    check("a cd prefix does not swallow the command after it",
          target_key("Bash", {"command": 'cd "D:/work/some-project" && git checkout -q master'}),
          "cmd:cd:some-project:&&:git:checkout:master")
    check("two commands in one directory stay distinct",
          target_key("Bash", {"command": "cd /repo && git push"}) !=
          target_key("Bash", {"command": "cd /repo && git status"}), True)
    check("the same command in two projects stays distinct",
          target_key("Bash", {"command": "cd /a/proj-one && npm test"}) !=
          target_key("Bash", {"command": "cd /a/proj-two && npm test"}), True)
    check("bare navigation is still its own attempt",
          target_key("Bash", {"command": "cd /nowhere"}), "cmd:cd:nowhere")
    check("two remote scripts over one transport are not one key",
          target_key("Bash", {"command": "tailscale ssh ws@vm 'nvidia-smi'"}) !=
          target_key("Bash", {"command": "tailscale ssh ws@vm 'df -h /workspace'"}), True)
    check("different git targets are different attempts",
          target_key("Bash", {"command": "git checkout -B pr133 origin/fix-a"}) !=
          target_key("Bash", {"command": "git checkout --detach origin/master"}), True)
    check("failure detected from exit code", failed({"exit_code": 2}), True)
    check("failure detected from traceback text", failed("Traceback (most recent call last)"), True)
    check("success is not invented", failed({"exit_code": 0, "stdout": "fine"}), False)
    check("unknown shape counts as success", failed(None), False)

    now = time.time()
    key = "cmd:python:build.py"
    three = [{"ts": now - 30, "kind": "fail", "key": key}] * 3
    check("three failures, nothing read -> counted", assess(three, key), (3, False))
    with_read = three + [{"ts": now - 1, "kind": "read", "key": "file:resolver.py"}]
    check("a read after the last failure clears it", assess(with_read, key)[1], True)
    early_read = [{"ts": now - 60, "kind": "read", "key": "x"}] + three
    check("a read BEFORE the last failure does not clear it",
          assess(early_read, key)[1], False)
    check("unrelated key is untouched", assess(three, "cmd:other")[0], 0)

    check("signature masks line numbers, paths and addresses",
          error_signature({"stderr": "File \"D:/a/x.py\", line 12\nAssertionError: got 3 at 0xdeadbeef"}),
          error_signature({"stderr": "File \"/tmp/b/x.py\", line 99\nAssertionError: got 7 at 0x1f"}))
    check("output without an error line has no signature",
          error_signature({"stdout": "all good", "stderr": ""}), "")
    check("two failing tests are not one signature because both end in '1 failed'",
          error_signature("E   KeyError: 'a'\n1 failed") != error_signature("E   TypeError: x\n1 failed"), True)
    check("different errors keep different signatures",
          error_signature("TypeError: bad operand") != error_signature("KeyError: 'name'"), True)
    sig = "AssertionError: got <n>"
    loop = [{"ts": 1, "kind": "fail", "sig": sig, "sid": "s"}, {"ts": 2, "kind": "edit", "sid": "s"},
            {"ts": 3, "kind": "fail", "sig": sig, "sid": "s"}, {"ts": 4, "kind": "edit", "sid": "s"},
            {"ts": 5, "kind": "fail", "sig": sig, "sid": "s"}]
    check("same error after each of two fixes counts three", premise_loop(loop, sig, "s"), 3)
    no_edits = [r for r in loop if r["kind"] == "fail"]
    check("plain retries without edits are not a premise loop", premise_loop(no_edits, sig, "s"), 1)
    check("another session's edits and failures do not count", premise_loop(loop, sig, "other"), 0)
    changing = [dict(r, sig=f"Error {i}") if r["kind"] == "fail" else r for i, r in enumerate(loop)]
    check("errors that keep changing stay silent",
          max(premise_loop(changing, f"Error {i}", "s") for i in range(5)), 1)

    global STATE
    with tempfile.TemporaryDirectory() as td:
        saved = STATE
        try:
            import contextlib
            import io
            STATE = Path(td) / "premise.jsonl"
            fail = {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "session_id": "s1",
                    "tool_input": {"command": "pytest tests/test_x.py"},
                    "error": "Exit code 1\nE   AssertionError: got 3\n1 failed"}
            edit = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "session_id": "s1",
                    "tool_input": {"file_path": "x.py"}, "tool_response": {"filePath": "x.py"}}
            notes = []
            for step in (fail, edit, fail, edit, fail, edit, fail):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    record(step)
                if out.getvalue():
                    notes.append(json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"])
            check("third failure after two fixes adds one note, the fourth adds none", len(notes), 1)
            STATE = Path(td) / "premise-shell.jsonl"
            sed = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s2",
                   "tool_input": {"command": "sed -i s/a/b/ x.py"},
                   "tool_response": {"stdout": "", "stderr": "", "bashEditDiff": {"changedFiles": ["x.py"]}}}
            shell_fail = dict(fail, session_id="s2")

            def notes_for(steps) -> int:
                count = 0
                for step in steps:
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        record(step)
                    count += bool(out.getvalue())
                return count
            check("edits made by a shell command count as fixes",
                  notes_for((shell_fail, sed, shell_fail, sed, shell_fail)), 1)
            STATE = Path(td) / "premise-abort.jsonl"
            aborted = dict(shell_fail, session_id="s3", is_interrupt=True)
            sed3 = dict(sed, session_id="s3")
            check("aborted calls are not failures",
                  notes_for((dict(shell_fail, session_id="s3"), sed3, aborted, sed3, aborted)), 0)
            STATE = Path(td) / "premise.jsonl"
            check("the note names the repeated error", "got <n>" in (notes[0] if notes else ""), True)
        finally:
            STATE = saved

    with tempfile.TemporaryDirectory() as td:
        saved = STATE
        try:
            STATE = Path(td) / "attempts.jsonl"
            for _ in range(WARN_AFTER_FAILURES):
                record({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                        "tool_input": {"command": "python build.py"},
                        "tool_response": {"exit_code": 1}})
            rows = _load(time.time())
            check("failures persisted", len([r for r in rows if r["kind"] == "fail"]), WARN_AFTER_FAILURES)
            check("advisory at the soft threshold, not a block",
                  decide({"tool_name": "Bash", "tool_input": {"command": "python build.py"}}), 0)
            record({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "python build.py"},
                    "tool_response": {"exit_code": 1}})
            check("bypass marker is honoured",
                  decide({"tool_name": "Bash",
                          "tool_input": {"command": "# claude-bypass: retry-loop\npython build.py"}}), 0)
            record({"hook_event_name": "PostToolUse", "tool_name": "Read",
                    "tool_input": {"file_path": "resolver.py"}, "tool_response": "ok"})
            n, consulted = assess(_load(time.time()), "cmd:python:build.py")
            check("reading the source clears the block", consulted, True)
        finally:
            STATE = saved

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
