Case: delivery-guard-notification-overwrites-intent-20260915
Verdict: NEEDS_WORK
Baseline cause: handle_hook classifies the whole prompt text of every UserPromptSubmit event, and the runtime delivers background-task notifications through that event as a leading <task-notification> element, so words inside the notification record a new intent that overwrites the owner's
Owner boundary: hooks/root-cause-delivery-guard.py
Reproducer: ["python", "hooks/tests/test_delivery_guard_notification_intent.py"]
After result: notification test exit 0 (14/14), scope test exit 0 (10/10), proof-executor test exit 0 (14/14); new test with HOOKS_DIR pointing at the unfixed main checkout (3656fdf) exit 1 (6 of 14 wrong)

# Independent review (fresh context, read-only except this file)

## What was checked

- Worktree HEAD is 3656fdf; `git status` shows only `hooks/root-cause-delivery-guard.py` modified plus the untracked test and case directory. The diff has two hunks: `owner_text` and its constants inserted after `record_intent`, and a one-line change in the UserPromptSubmit branch of `handle_hook`. `INCIDENT_PATTERNS`, `CHANGE_PATTERNS`, `record_intent`, `pretool` and `stop` are untouched. `record_intent` still hashes the full raw prompt.
- The baseline cause is confirmed. The main checkout (clean at 3656fdf, no `owner_text`) records an incident intent from a bare `<task-notification>` containing "failed"/"error", and the intent id is replaced.
- The owner boundary is confirmed as `hooks/root-cause-delivery-guard.py`. The reproducer argv is confirmed and matches `plan.focused_argv`.
- I ran the three test files; exit codes are in the After result line. The red run against the unfixed hook fails exactly the 6 cases listed in `before-supplement-unfixed-hook.txt`.
- Evidence matches case.json. The sha256 of `before-00.txt` is 49378e19... and of `after-00.txt` is a69530e2...; both equal the recorded values. `before-00.txt` is the 13-case version (5 wrong, no truncated case), as claimed. I did not re-run `replay-real-events.txt`: its scratch script is not in the case. Its content is internally consistent. case.json has `intent_id: null`; I noted this and did not investigate further.
- Requirement 2 (structural detection) holds: no new word lists, only envelope detection. I checked the author's claim that the payload has no provenance field against the hooks docs, but only partially: the common input fields contain no origin/source field, and the fetched page was truncated before the UserPromptSubmit-specific section.

## Real-data check (local transcripts, 510 files containing the tag or marker)

- 3711 `attachment.prompt` and 1496 `user` string records start with a bare `<task-notification>`, contain one element, and have nothing after the close tag. `owner_text` returns empty for all of them.
- 110 `user` records in subagent transcripts start with the bare marker `[SYSTEM NOTIFICATION - NOT USER INPUT]`, not wrapped in `<system-reminder>`, and carry 1 to 3 concatenated notifications. `owner_text` returns empty for all of them. So stripping through the LAST closing tag (`rfind`) is justified by data.
- A real desktop owner prompt (this session's) starts with a worktree `<system-reminder>` and mentions the marker mid-text. It is returned unchanged and classified.

## Equivalence property

- I checked `classify_prompt(owner_text(p)) == classify_prompt(p)` and `owner_text(p) == p.lstrip()` for every p that does not open with a notification. "Opens with a notification" was defined independently: a leading `<task-notification` followed by space, `/` or `>`; or the leading marker; or a leading `<system-reminder>` followed by the marker.
- Samples: 12,827 real user strings from transcripts (3223 incident, 2379 change, 7225 none), hand-written RU/EN prompts, and 200,000 fuzz strings over a hostile alphabet (tags, marker, CRLF, NBSP, BOM, Cyrillic).
- Result: 0 mismatches out of 201,073 checked. No pattern is anchored with `^`, so the `lstrip` cannot change `\b` matching.

## Holes proven by calling the functions

These are the reason for NEEDS_WORK. Each input is genuine owner-authored text. Through `handle_hook` followed by `pretool` Write on `service.py` with no case, the fixed hook records NO intent and does NOT block the edit. The unfixed hook records an incident and blocks. That violates "genuine owner prompts are classified exactly as before" and requirement 4 for these inputs.

- H1 (the most plausible, in this repo): `<task-notification> events overwrite the delivery intent - fix this bug`. The leading opening tag has no closing tag, so `owner_text` returns `""`. The cause is the `end < 0: return ""` branch, which exists only to satisfy the added test case "truncated task-notification without its closing tag records nothing". In the transcript data, 0 of 5207 notification records are truncated, so that branch is fail-open on an unobserved shape.
- H2: `<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\nmonitor event\n</system-reminder>\nthe parser crashes, fix this`. The wrapper contains no `</task-notification>`, so the owner text after `</system-reminder>` is dropped (same branch).
- H3: `[SYSTEM NOTIFICATION - NOT USER INPUT] shows up in my prompt and the hook crashes, fix this`. The owner literally opens with the marker, and the whole prompt is swallowed (same branch). This one is contrived.
- H4 (accepted residual, not blocking): `<task-notification>\n<status>done</status>\n</task-notification>\nThe hook is broken, fix this: it mishandles a trailing </task-notification> tag`. `rfind` cuts the owner text at the owner's own quoted close tag. This trade-off is needed so that notifications which quote the close tag inside their result are fully stripped.

## Minimal direction for the fix

- When no `</task-notification>` is found, return the text unchanged, which fails closed to the old classification. Do not return `""`.
- Change the "truncated" test case to expect an intent, or remove it.
- Add a case for an owner prompt that opens with an unclosed literal `<task-notification>` tag and ends with an incident request. Assert that the intent is recorded and that a source edit is blocked.

## Notification shapes still classified (not blocking, no real occurrences)

- A notification prefixed by U+FEFF (BOM) or U+200B: Python `str.lstrip` does not strip these, so the text classifies as incident.
- `<system-reminder>\n<task-notification>...` without the marker also classifies as incident.
- None of these shapes occurs in 5207 real records. `<task-notification-extra>` is correctly not treated as a notification.

## Ruled out

- CRLF, leading whitespace, NBSP, an uppercase tag, a tag with attributes, a self-closing `<task-notification/>`, multiple concatenated notifications, and the model-facing marker wrapper with CRLF: all return empty.
- A prompt quoting "task-notification" mid-text, a leading unrelated `<system-reminder>`, the marker appearing later in the text, and a leading `<b>` tag: all are unchanged and classified as before.
