# PROBLEMS


## 2026-08-29 - PUBLIC PUSH BLOCKED: THE SEMANTIC LEG OF THE PRE-PUSH SCAN CANNOT RUN

**Status**: missing-dep

`git push` to `AnastasiyaW/codex-claude-code-config` is refused, and refused correctly:

    [pre-push] Agent A passed, invoking Agent B (Claude semantic)...
    [pre-push] Agent B: claude CLI found (...\2.1.246\claude.exe) but call failed:
               Failed to authenticate: OAuth session expired and could not be refreshed
    [pre-push] Agent B (semantic) could not run - THIS IS NOT A PASS.

The regex leg was clean. That is not enough for a public repository and the gate says so in as
many words: a regex cannot see prose naming a host, a client or our infrastructure. **Not
overridden.** `CLAUDE_ALLOW_PUSH=1` exists and was deliberately not used - a public push is the
one boundary where "could not check" must never be spent as "checked", and the judgement the
second leg makes is precisely the one a session should not make for itself.

**What is waiting**: commit `89aef8c` - the delivery guard no longer counts its own bookkeeping
(`.agent/user-tasks/**`) as the source it gates. Committed locally, unpushed. Any further commits
here queue behind the same gate.

**Recheck**: re-authenticate the `claude` CLI, then `git push origin HEAD` and read the exit
status - the gate must print that BOTH legs ran, not merely that Agent A was clean.

## 2026-08-29 - A SECOND, STALE COPY OF THE DELIVERY GUARD EXISTS

**Status**: arch-decision

Two files, different content:

    %USERPROFILE%\.claude\claude-code-config\hooks\root-cause-delivery-guard.py   49704 bytes  <- WIRED
    %USERPROFILE%\.claude\hooks\root-cause-delivery-guard.py                         42960 bytes

`settings.json` names only the first, so the fix above went there and the second is 6.7 KB behind.
Deliberately not copied into: duplicating a guard is a known failure in this codebase - two copies
drift, and the next editor changes whichever one they find first. Whether the second copy should
be deleted, made a thin loader, or is wired into some other harness (Codex reads its own config)
is not a call for a session that only measured which one Claude Code loads.

## 2026-09-15 - DELIVERY GUARD STILL CLASSIFIES PEER AND CODEX MACHINE MESSAGES

**Status**: arch-decision

The fix at a555849 excludes Claude Code <task-notification> elements from intent
classification. The case is .agent/delivery-cases/delivery-guard-notification-overwrites-intent-20260915.
Two other machine-sent message kinds still reach the word patterns:

- Cross-session peer or coordinator messages (<cross-session-message ...>). 148 of 228 unique
  transcript texts classify. A live one recorded intent 18c5c32d3693 in session 668b04d0.
- Codex <subagent_notification>. 304 of 646 local messages classify. Nobody has measured whether
  Codex passes them to this hook.

Whether a peer's work request should open a delivery intent is the owner's design call, not a
mechanical fix. Excluding it would also stop a teammate's real incident report from gating edits.

**Recheck**: the follow-up session "Decide delivery-guard intents for peer and Codex messages".
It must measure both paths against live events, get the owner's decision on peer messages, and
land a structural exclusion with a behavioural test.

## 2026-09-24 - PUBLIC PUSH BLOCKED AGAIN: SEMANTIC SCAN CLI OUT OF WEEKLY QUOTA

**Status**: missing-dep

Same gate as 2026-08-29, different cause. The first attempt was stopped by Agent A on a real
private host name in a self-test string; that commit was never pushed and was amended to a
neutral name. The second attempt:

    [pre-push] Agent A passed, invoking Agent B (Claude semantic)...
    [pre-push] Agent B: claude CLI found (...\2.1.280\claude.exe) but call failed:
               You've hit your weekly limit · resets Sep 26, 12pm (Europe/Budapest)
    [pre-push] Agent B unavailable (claude CLI missing or timeout) — public push blocked

Not overridden, for the reason recorded on 2026-08-29.

**What is waiting**: commit `b892835` "stop-guard: a report of finished work is not a hand-off"
(hooks/stop-phrase-guard.py; independent reviewer PROCEED after three HOLD rounds; self-test ok;
unittest shows only the two errors that also fail on the previous HEAD). The hook already runs
from this working tree, so the fix is live locally; only publication waits.

**Recheck**: after 2026-09-26 12:00 Europe/Budapest, `git push origin main` and read the exit
status - the gate must print that both agents passed.


## 2026-09-26 - STOP-GUARD: ENGLISH DIRECTIVE WORDS FIRE ANYWHERE IN A REPORT

**Status**: arch-decision

Found while closing REQ-EDC941FD1708 (commit `511efa3`, hyphen-in-word is not a flag). The
report of that finished fix was itself blocked as homework. Measured with
`agent_capable_user_homework(final, [action_prompt], {})` -> `'copy'`:

- `_USER_WORK_DIRECTIVE` matched `copy` in "which takes the working-tree copy" (a noun) and
  `run` in a quoted example "run `pre-commit`"; English words there count at any position,
  unless `agent_owns_phrase` finds I/we first in the clause.
- `shape_is_instruction` also flagged a mis-paired backtick span and the path
  `.agent/user-tasks/REQ-.../` because `_INSTRUCTION_VERB` found `copy`/`run` in the window.

Direction: an English directive counts only in imperative position (clause-initial after a
bullet/label/sentence break, or after "please"/"you (should|need to|can)"), as
`_IMPERATIVE_LEAD` + `_is_bare_imperative` already decide for unlisted verbs. Russian
imperative forms stay position-free: they are unambiguous.

Why not in 511efa3: that grammar (`_IMPERATIVE_LEAD`, `_is_bare_imperative`, `_reports_after`,
the question/decision rules) sits in ~310 uncommitted WIP lines of another session in this
same file. Changing its word-position semantics now either conflicts with that WIP or has
to be layered on code nobody has reviewed yet; the WIP owner decides the order.

**Recheck**: when the WIP in `hooks/stop-phrase-guard.py` is committed, add the report
above as a mandatory-green case (with a clause-initial "Run `x --y`." control that stays
red), then apply the position rule.

2026-09-30, while closing `b10aeb3` (hyphen compounds): same class, two more shapes. The
finished report returned `'run'` from "Agent B of the pre-push scan couldn't run" (a verb
after a negated modal), and `Open`/`Запусти` from quoted test inputs inside multi-word
backtick spans ("`Open https://…` returns `'Open'`"). The position rule above covers both;
the negated modal also belongs among its non-imperative leads.

## 2026-09-30 15:58 - PUBLIC PUSH BLOCKED: SEMANTIC SCAN CLI OUT OF WEEKLY QUOTA (b10aeb3)

**Status**: missing-dep

Same gate and cause as 2026-09-24. Refused twice, the second time captured by machine in
`.agent/user-tasks/REQ-5B886CC0BC3A/push-refusal.log`:

    [pre-push] Agent A passed, invoking Agent B (Claude semantic)...
    [pre-push] Agent B: claude CLI found (...\2.1.284\claude.exe) but call failed:
               You've hit your weekly limit · resets Oct 3, 12pm (Europe/Budapest)
    [pre-push] Agent B unavailable (claude CLI missing or timeout) — public push blocked

Not overridden: the owner asked for the gate to be kept.

**What is waiting**: `b10aeb3` "stop-guard: a hyphen-joined verb is a compound, not an
imperative" (self-test ok on the commit alone and on the live tree; 8/8 single-piece
reverts red; independent reviewer PROCEED). The hook runs from this working tree, so the
fix is live locally.

**Recheck**: after 2026-10-03 12:00 Europe/Budapest, `git push origin main`; PASS when
both agents pass and `origin/main` contains `b10aeb3`. Then close item `push-public-repo`
of REQ-5B886CC0BC3A.

## 2026-09-26 14:40 - human-confirmation-guard: deletes hidden in wrappers pass; quoted words false-block

**Status**: arch-decision

Found by the independent review of `031ff27` (temp files deletable without consent). Both
behaviours are identical at the previous HEAD; `031ff27` neither opened nor closed them.

1. Allowed deletions of real data when the delete verb is not the segment's command word:
   `(rm C:\data\x)`, `{ rm x; }`, `if ...; then rm x; fi`, `xargs rm`, `find ... -exec rm {} +`,
   `env`/`nohup`/`busybox rm`, `\rm`, `bash -c "rm ..."`, `powershell -c "del ..."`,
   `iex "ri ..."`, `unlink`, `python -c "shutil.rmtree(...)"`. Old SAFE_TARGET_PATTERNS are
   searched anywhere in the path, so `%USERPROFILE%/dist` or `.../data.bak/stuff` also pass.
2. False blocks: a destructive word inside a quoted argument of a non-printing command
   (`git commit -m "... Remove-Item ..."`) blocks, because `executable_text` only strips
   quotes of printing commands. Measured 2026-09-26 on this very commit's message.

Direction: a real command-line model instead of regexes - strip wrapper words and a leading
backslash, recurse into `-c` / `-Command` / `-exec` payloads, anchor SAFE patterns to the path
relative to cwd, and strip quoted arguments of known non-executing commands (git commit -m,
gh ... --body). One parser, shared with `executable_text` so the blind spot lives in one place.

Why not in 031ff27: it is a parser redesign of the shared `safety_common.executable_text`
that every command guard depends on; patching single wrappers one at a time is the
actor-critic spiral this change was reviewed against. Needs its own case and review.

**Recheck**: build the parser behind `executable_text`, add every command above to
`human-confirmation-guard.py --self-test` (group 1 must-block, group 2 must-allow), and run
all command-guard self-tests.

Same class, `agent_policy_gates.commit_invocations` (review round 2, 2026-09-26): after the
fixed cases (newline, backslash paths, redirections, cd/Set-Location carry, env/VAR= prefixes)
a commit hidden in `bash -c "git commit"`, `sh -c`, `powershell -c`, or a git alias
(`git ci`) is still not seen, so the commit check does not run for it. One shared parser
closes both guards; recheck adds those commands to `test_agent_policy_commit_gate.py`.
