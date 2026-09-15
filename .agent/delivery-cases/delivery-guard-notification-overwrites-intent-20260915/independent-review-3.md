Case: delivery-guard-notification-overwrites-intent-20260915
Verdict: PASS
Baseline cause: handle_hook classifies the whole prompt text of every UserPromptSubmit event, and the runtime delivers background-task notifications through that event as a <task-notification> element, so words inside the notification record a new intent that overwrites the owner's; the exclusion must recognise that element by its structure (opening tag followed by a child element, then its closing tag), because a leading tag or marker plus any later closing tag also matches owner prompts that quote them
Owner boundary: hooks/root-cause-delivery-guard.py
Reproducer: ["python", "hooks/tests/test_delivery_guard_notification_intent.py"]
After result: notification test exit 0 (24/24); scope test exit 0 (10/10); proof-executor test exit 0 (14/14); notification test with HOOKS_DIR at the unfixed main checkout exit 1 (5 of 24 wrong); replay exit 0 on both hooks, output identical to replay-real-events.txt (CRLF aside)

# Third independent review (fresh context, read-only except this file)

## Scope of the change

- Worktree base is 3656fdf. `git diff 3656fdf` on the hook has two hunks, +51 -1: the `owner_text` block with `SYSTEM_NOTIFICATION_MARKER`, `NOTIFICATION_CLOSE`, `_NOTIFICATION_OPEN` and `_MARKER_LEAD`, inserted after `record_intent`, and the one call site `classify_prompt(owner_text(prompt))` in `handle_hook`.
- `INCIDENT_PATTERNS`, `CHANGE_PATTERNS`, `classify_prompt`, `record_intent`, `pretool` and `stop` are untouched. `record_intent` still hashes the raw prompt.
- While this review ran, two commits landed on the branch: b6d7fe2 (the guard fix) and 24b2c1a (`.gitattributes` to keep the case records byte-exact).
  - `git diff 3656fdf HEAD` on the hook has the same sha256 (98c4178d...) as the working-tree diff I reviewed.
  - The worktree is otherwise clean, so this verdict applies to HEAD 24b2c1a.
  - Current file digests: hook cdd96b98..., test 0aa68696....
- In the main checkout, `hooks/root-cause-delivery-guard.py` is clean at 3656fdf and has no `owner_text` (grep count 0), so the HOOKS_DIR run exercised the unfixed hook.

## Baseline cause, owner boundary, reproducer: confirmed

- Baseline cause (copied above byte for byte): confirmed. With the unfixed hook, a bare notification that contains "error" records an incident and replaces the owner's intent id. The replay of real notification b5jhe7jfl prints an intent receipt and changes the intent id. With the fixed hook it does neither.
- Owner boundary: confirmed. The defect and the fix are both in this one file.
- Reproducer: confirmed. The argv equals `plan.focused_argv`. It exits 1 against the unfixed hook, and the five FAIL labels match `before-supplement-unfixed-hook.txt`. It exits 0 against the worktree hook, and its labels match `after-02.txt`.
- Evidence digests match case.json: `after-02.txt` is 77c69747... and `before-00.txt` is 49378e19....

## H1-H3 and N1-N4: all closed

- Method: each input went through `handle_hook`, then `pretool` Write on `service.py` with no case. The repo was a temp git repo and `AGENT_ROOT_CAUSE_STATE_DIR` pointed at a temp dir.
- Fixed hook: H1, H2, H3, N1, N1-ru, N2 and N3 record an incident and block the edit. N4 records a change and blocks.
- The unfixed hook gives identical results on all eight inputs.

## Requirements

- R1, notifications: every one records nothing and leaves the owner intent in place. This holds for:
  - the bare element;
  - the element after leading whitespace or with CRLF line endings;
  - the bare marker followed by the real preamble;
  - `<system-reminder>` plus the marker;
  - three concatenated elements.
- R1, owner prompts: see the equivalence property and the residuals below.
- R2 holds. Detection is by envelope only: an opening tag followed by `\s*<letter`, then a later close tag. No word list was added.
- R3 holds. RU and EN incident prompts record. A notification containing failed/error records nothing. A prompt quoting "task-notification" mid-text records.
- R4 holds. An owner prompt followed by a Write with no case is blocked, and it is still blocked after a notification.

## Equivalence property

- Fuzz: 300,000 strings built from tag spellings, the close tag, `<system-reminder>`, the marker, CRLF, NBSP, BOM, ZWSP and RU/EN trigger words.
  - 298,978 contain no structural element anywhere. "Structural element" was defined independently: an opening tag, then whitespace and `<letter`, then a close tag later.
  - Among those: 0 classification mismatches, and `owner_text(p) == p.lstrip()` holds for all of them.
- Real transcripts: 3,578 jsonl files under ~/.claude/projects, labelled by runtime provenance (`origin.kind` and attachment `commandMode`).
  - Of 11,112 unique non-notification prompt texts (5,846 labelled human), `owner_text` stripped none. Classification mismatches: 0.
  - None of them contains a structural element.

## Direction 2: real notification shapes

- 5,348 unique runtime-labelled notification records were measured: `attach:task-notification`, `user-origin:task-notification`, and their subagent forms.
- Before the fix, 1,550 of them classified as incident or change. After the fix, 0 do.
- Every record is stripped, and none leaves words after the close tag.
- All 112 marker-lead records carry one identical preamble between the marker and the element. So `search` after the marker is needed.
- Concatenation: 3 records hold more than one element, separated only by blank lines.
- No record has more close tags than opening tags.
- Shapes that still classify: a BOM or ZWSP prefix, `<system-reminder>` without the marker, a worktree reminder in front of the marker, an attribute on the opening tag, text or a comment as the first child, and an uppercase tag.
  - Proven by execution with an "error" result: both hooks record an incident for each.
  - None of these shapes occurs in the 5,348 records. Each one falls back to the old behaviour. Accepted.

## Direction 1: owner prompts that are swallowed (accepted residuals)

In each input below the fixed hook records no intent and does not block the Write. The unfixed hook records the intent and blocks.

- H4 (the documented residual) still reproduces: a pasted notification followed by `The hook is broken, fix this: it mishandles a trailing </task-notification> tag`.
- X1 (new, undocumented): `[SYSTEM NOTIFICATION - NOT USER INPUT] blocks are misread by the delivery guard, fix this bug. Example:` followed by a pasted real-shaped element.
  - The RU form and a change form (`... implement a filter so that this is ignored:`) behave the same way.
  - Cause: in marker mode, `_NOTIFICATION_OPEN.search` discards the owner words between the marker and the element.
- X2 (new): `<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\n</system-reminder>\nThe hook is broken, fix this. It got:` followed by a pasted element. The cause is the same as X1.
- X3 (new): a pasted element, then `The deploy is broken after these two, fix this`, then a second pasted element. Cause: `rfind` strips through the last close tag.
- X5: an owner-written element with a child, `<task-notification><status>failed</status> is what I see, fix this bug</task-notification>`. It cannot be told apart from a real notification by structure.

Why these are accepted rather than blocking:

- Each input needs an owner prompt that opens with a complete notification envelope, or with the marker literal followed by one.
  - 0 of 5,846 human-labelled prompts open with the tag, the marker, or `<system-reminder>` plus a notification.
  - H3 and N3 had a no-cost structural fix. These inputs do not.
- Two candidate fixes were measured by substituting `owner_text` in scratch only.
  - "gap" (also classify the text between the marker and the element) closes X1 and X2.
  - "each" (additionally strip each element through its own first close tag) also closes X3 and H4.
  - Both pass the author's 24 cases and leave all 5,348 real notifications unclassified.
- Each candidate has a runtime-side cost, proven by execution:
  - Under "each", an agent result `<result>... strips through </task-notification>; the parser has a bug, fix this ...</result>` records an incident. The current code records nothing.
  - Under "gap", a marker preamble containing a trigger word ("Do not write a reply ... as if the user created it") records a change. The current code records nothing.
  - So "each" reopens the original defect for review reports that quote the tag, which is plausible in this repo. "gap" ties correctness to the harness preamble wording, which violates R2 in spirit.
- The current trade-off is the better one.

## Non-blocking nits

- The `owner_text` docstring claims "anything written after a pasted one is still classified". That is false for H4.
- Neither the code comment nor case.json names the residuals H4, X1, X2, X3 and X5. The quality-code rule asks that a simplification comment name its ceiling.
- The test module docstring still cites "1492 of 1492" records, while the hook comment cites 5258.
- `before-supplement-unfixed-hook.txt` lost the leading indentation on its first line. Its content matches my run.
- case.json still has `intent_id: null` and status IMPLEMENTING.

## Observations outside this case's requirements

- Codex `hooks.json` runs this hook on UserPromptSubmit. Review 2 found 304 Codex `<subagent_notification>` messages that classify. Neither hook excludes them.
- Transcript messages with `origin.kind` coordinator (193) or peer (35) are messages from another session or a coordinator. Of 228 unique texts, 148 classify as incident or change under both hooks.
- I did not measure whether any of these fire UserPromptSubmit. If they do, they belong to the same defect class and need a separate case.

## Reviewer identity

- This review ran as a fresh-context subagent. Its scratchpad path carries session id 668b04d0-c5dd-4be1-b794-cf6462774914, the same id as `builder` in case.json.
- Whoever records it should not present that id as a distinct reviewer session.
- Scratch files are under `D:\tmp\claude\...\scratchpad\review3-k8qfz_xc`: probe.py, probe2.py, fuzz.py, scan.py, scan2.py and variants.py.
