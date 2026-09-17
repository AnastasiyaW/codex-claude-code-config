Case: delivery-guard-notification-overwrites-intent-20260915
Verdict: NEEDS_WORK
Baseline cause: handle_hook classifies the whole prompt text of every UserPromptSubmit event, and the runtime delivers background-task notifications through that event as a leading <task-notification> element, so words inside the notification record a new intent that overwrites the owner's
Owner boundary: hooks/root-cause-delivery-guard.py
Reproducer: ["python", "hooks/tests/test_delivery_guard_notification_intent.py"]
After result: notification test exit 0 (18/18); scope test exit 0 (10/10); proof-executor test exit 0 (14/14); notification test with HOOKS_DIR at the unfixed main checkout exit 1 (5 of 18 wrong); replay exit 0 for both hooks, output identical to replay-real-events.txt

# Second independent review (fresh context, read-only except this file)

## Scope of the change

- Worktree base is 3656fdf. `git diff -U0` on the hook shows exactly two hunks: the `owner_text` block with its three constants, inserted after `record_intent`, and the one-line `classify_prompt(owner_text(prompt))` change in the UserPromptSubmit branch of `handle_hook`.
- `INCIDENT_PATTERNS`, `CHANGE_PATTERNS`, `record_intent`, `pretool` and `stop` are untouched. `record_intent` still receives the raw prompt.
- The main checkout's `hooks/root-cause-delivery-guard.py` has no diff against its HEAD 3656fdf, so the HOOKS_DIR run exercised the unfixed hook. (The main checkout does have an unrelated uncommitted edit to `hooks/safety_common.py`.)
- No pattern is anchored, so the `lstrip` in `owner_text` cannot change a match.

## Baseline cause, owner boundary, reproducer

- Baseline cause confirmed. With HOOKS_DIR at the unfixed hook, a bare `<task-notification>` records an incident and replaces the owner's intent id. The replay of the real notification b5jhe7jfl through the unfixed hook process prints an intent receipt and changes the intent id.
- Owner boundary confirmed: the defect and the fix are both in `hooks/root-cause-delivery-guard.py`.
- Reproducer confirmed: it is the same argv as `plan.focused_argv`. It exits 1 against the unfixed hook, failing the same 5 cases as `before-supplement-unfixed-hook.txt`, and exits 0 against the worktree hook.
- The evidence digests match case.json: `before-00.txt` is 49378e19..., `after-01.txt` is 4daadeb8....

## Test runs (exit codes)

- `python hooks/tests/test_delivery_guard_notification_intent.py`: exit 0, all 18 correct.
- `python hooks/tests/test_delivery_guard_scope.py`: exit 0, all 10 correct.
- `python hooks/tests/test_root_cause_proof_executor.py`: exit 0, all 14 correct.
- The notification test with `HOOKS_DIR=~/.claude/claude-code-config/hooks`: exit 1, 5 of 18 wrong. This is the expected red.
- The replay was re-run with REPLAY_TMP in the scratchpad against both hooks. Both exit 0, and all five lines of each block are identical to `replay-real-events.txt`.

## H1-H3 from the first review: closed

- Each input went through `handle_hook`, then `pretool` Write on `service.py` with no case, using a temp git repo and `AGENT_ROOT_CAUSE_STATE_DIR` in a temp dir.
- H1 `<task-notification> events overwrite the delivery intent - fix this bug`: records incident, and the edit is blocked.
- H2 `<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\nmonitor event\n</system-reminder>\nthe parser crashes, fix this`: records incident, and the edit is blocked.
- H3 `[SYSTEM NOTIFICATION - NOT USER INPUT] shows up in my prompt and the hook crashes, fix this`: records incident, and the edit is blocked.
- On all three the unfixed hook gives the same result.

## Equivalence property

- Setup: 300,000 fuzz strings over an alphabet of the tag in several spellings, the close tag, `<system-reminder>`, the marker, CRLF, NBSP, BOM, ZWSP, RU and EN incident and change words, and noise. "Opens with a notification" was defined independently of the hook.
- Prompts that do not open with a notification: 0 mismatches in `classify_prompt(owner_text(p)) == classify_prompt(p)`, and `owner_text(p) == p.lstrip()` holds for all of them.
- Prompts that open with the tag or marker and contain no `</task-notification>` anywhere: 0 mismatches. The old classification is kept.
- Prompts that open with the tag or marker and contain a close tag: 3,920 strings, and 977 of them changed classification. This is the only region where behaviour changes, and the new holes below live in it.

## Real data (Claude transcripts, 3,547 files under ~/.claude/projects)

- The scan found 5,258 unique notification strings: 3,654 `attachment.prompt` and 1,494 `user` strings are bare elements, and 110 `user` strings open with the bare marker.
- The fixed `owner_text` classifies all 5,258 as None. Before the fix, 1,529 of them were classified as incident or change.
- In every one of them, the first content after the opening `<task-notification>` tag is a child element: `<task-id>` in 5,257 and `<task-type>` in 1.
- Zero prompt-shaped records have the `<system-reminder>` plus marker shape. Zero records wrap a notification behind another reminder.
- Six other-prefix records mention the tag, for example an agent's security-review prompt that quotes a diff. The fixed hook classifies them exactly as the old one did.

## New holes: owner prompts swallowed when a close tag exists (reason for NEEDS_WORK)

- In each case below, the prompt is genuine owner text that opens with the literal tag or the marker. No notification body is present. Somewhere later the owner quotes `</task-notification>`.
- `owner_text` strips through that quoted close tag, so every owner word before it is dropped. The fixed hook records no intent, and `pretool` Write with no case is NOT blocked. The unfixed hook records the intent and blocks.
- This breaks requirement 1 ("genuine owner prompts are classified exactly as before") and requirement 4 for these inputs. It is the same class as H1-H3. The attempt-1 fix only covers the sub-case where no close tag exists anywhere.
- N1 `<task-notification> events break the delivery guard, fix this bug. The element ends with </task-notification>`: fixed hook gives None and no block; unfixed gives incident and a block.
- N1-ru `<task-notification> ломает гейт, почини. Пример закрытия: </task-notification>`: fixed gives None and no block; unfixed gives incident and a block.
- N2 `<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\nmonitor event\n</system-reminder>\nthe hook has an error, fix this. It trips on </task-notification>`: fixed gives None and no block; unfixed gives incident and a block.
- N3 `[SYSTEM NOTIFICATION - NOT USER INPUT] the hook crashes, fix this; it strips up to </task-notification>`: fixed gives None and no block; unfixed gives incident and a block.
- N4 `<task-notification> implement a parser for this element and its </task-notification>`: fixed gives None and no block; unfixed gives change and a block.
- Cause in code: once the text opens with the tag or marker, `owner_text` only calls `text.rfind("</task-notification>")`. It never checks that a notification element exists before that close tag. For the marker spelling it does not even require an opening `<task-notification>`.
- These holes are fixable structurally, with no word list. Every real notification has an opening `<task-notification>` whose first content is a child element, and the close tag comes after it.
- Feasibility check: that condition was added on top of the current `owner_text`. This was done only by substituting the function on the loaded module in the scratchpad; the repository was not edited. Results:
  - the author's test still passes 18 of 18;
  - N1-N4 and H1-H3 all record an intent and block the edit;
  - the real bare and wrapped notifications still record nothing;
  - on the transcript data the condition holds for all 5,258 real notifications, so no real coverage is lost.
- Suggested test additions: N1 with an edit-block assertion, plus N3 or N2.

## Residuals and non-blocking observations

- H4 (accepted residual) still reproduces: a real pasted notification followed by owner text that quotes `</task-notification>` gives `owner_text` = `' tag'`, no intent and no block. Stripping through the last close tag is what makes this happen. The candidate check above does not change it.
- Some notification shapes are still classified, but none occurs in the 5,258 real records:
  - a worktree `<system-reminder>` block followed by a marker-wrapped notification;
  - `<system-reminder>` followed by a notification without the marker;
  - a notification prefixed with U+FEFF.
- Codex, outside the two shapes named in requirement 1:
  - The Codex rollouts under ~/.codex/sessions hold 646 user-role messages that open with `<subagent_notification>`.
  - Both the old and the fixed hook classify 304 of them as incident or change, since the fix does not cover this element.
  - This case's layer says Codex runs this same hook file. I did not measure whether Codex fires UserPromptSubmit for these messages, so this is recorded as an observation, not as a defect of this case.
- Reviewer identity: this review ran as a fresh-context subagent, but its scratchpad path carries session id 668b04d0-c5dd-4be1-b794-cf6462774914, the same id as `builder` in case.json. Whoever records the review should not present it as a distinct session id.
- case.json still has `intent_id: null` and status IMPLEMENTING. `independent-review.md` (the first review) still carries its own stale After result line (14/14). This file supersedes it.
