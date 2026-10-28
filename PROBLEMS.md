# PROBLEMS


## 2026-08-29 - PUBLIC PUSH BLOCKED: THE SEMANTIC LEG OF THE PRE-PUSH SCAN CANNOT RUN

**Status**: RESOLVED 2026-10-28 - waiting commit 89aef8c is in origin/main; the semantic leg runs again (Agent B rotates registered logins on quota), e.g. the push of PR #31 printed "Agent A passed, invoking Agent B ... on 1 chunk(s)" and "both agents passed".

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

**Re-measured 2026-10-28** (branch fix/delivery-guard-problems). The copy is not in this repo:
`%USERPROFILE%\.claude\hooks\` is outside any git tree. Now 43308 bytes, mtime 2026-10-13,
sha256 prefix 56f5d9080209fc7b; the wired copy is 35ce545a90d30e62 on main 4940341.
- No harness registers it: `settings.json` (3 hook entries), `~/.codex/hooks.json` (3) and
  `claude-code-private/machines/Happyin/{settings,codex-hooks}.json` (3 each) all name
  `claude-code-config/hooks/root-cause-delivery-guard.py`. The live root-cause-delivery skill in
  `~/.claude/skills`, `~/.codex/skills`, `~/.agents/skills` and this repo uses the wired path too.
  The only file reference left is `~/.claude/.skill-trees-backup-2026-08-23/` (a backup).
- But it IS run: `logs/safety.log` has 52 commands calling `python ~/.claude/hooks/root-cause-delivery-guard.py
  verify|capture|...`, the latest 2026-10-26. The cause was the wired guard itself: its "no
  PLAN_FROZEN case" block message told agents to run the CLI at `~/.claude/hooks/`. Fixed here:
  the message now names the running file (`Path(__file__)`), tested in
  `hooks/tests/test_delivery_guard_machine_messages.py`.

**Remaining owner decision**: delete `%USERPROFILE%\.claude\hooks\root-cause-delivery-guard.py`
(or replace it with a loader of the wired file). Safe to act once this branch is merged and
pulled into the live folder; before that, agents still get the old message. Agents already
holding the old command in a handoff would then fail loudly instead of running stale case logic.

## 2026-09-15 - DELIVERY GUARD STILL CLASSIFIES PEER AND CODEX MACHINE MESSAGES

**Status**: RESOLVED 2026-10-28 - owner's rule given with the task: messages from other agents, sessions, Codex and harness notifications never count as her request. `owner_text` removes closed `<cross-session-message>`, `<agent-message>` (incl. `[Subagent hand-back]`), `<subagent_notification>` and `<system-reminder>` elements, and drops whole "Stop hook feedback:" prompts and rendered "Another Claude session sent a message:" prompts; unclosed tags still classify (fail closed). Still reproduced on main 4940341: 22 live intents in `~/.claude/state/root-cause-delivery` have the digest of these shapes (15 bare peer elements, 4 behind a linked-sessions reminder, 2 agent-message hand-backs, 1 task notification plus plugin reminder; latest 2026-10-23), plus 4 from "Stop hook feedback:" in August. Codex hands `<subagent_notification>` over as a user-role message (65 of 65 closed, 250 newest rollouts); whether Codex fires UserPromptSubmit for it is still unmeasured, so it is stripped defensively. Evidence: `.agent/delivery-cases/delivery-guard-machine-messages-20261028/evidence/` - test red on main (22 of 36 wrong) and green after (36/36), run_guard_regressions 349/349, mutation_probe 15/15 killed, transcript replay: peer 195 -> 0 intents, no owner-word loss. Independent fresh-context review: PROCEED (its tag-name finding fixed; quadratic-regex and pasted-wrapper ceilings documented in the code). Ceiling: a teammate's real incident report no longer opens an intent by itself; the receiving agent opens one through the owner or `init`.

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

**Status**: RESOLVED 2026-10-28 - waiting commit b892835 is in origin/main; both scan legs ran on every public push today (PRs #23-#31).

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

**Status**: RESOLVED 2026-10-28 on branch `fix/stop-guard-false-positives` (also closes
REQ-1536EA2F40F5). The WIP this entry waited for is on main. `hooks/stop-phrase-guard.py`:
1. An English directive (`_USER_WORK_DIRECTIVE`, and `_INSTRUCTION_VERB` in the shape window)
   counts only in an imperative slot: opening its clause after a break, bullet or lead adverb,
   or right after "please"/"you [modal]…"/"don't forget to"/"тебе нужно"; never when Russian
   follows it ("; open вопросов"), nor a count on a line that already speaks Russian ("4 set",
   ", run 41 passed"; "Run 3 times" still counts). Russian forms stay position-free.
2. A whitespace-free backticked span (repo, branch, path) is judged by its own clause only, not
   by a verb or "Пользователь" elsewhere in the 260-char window.
3. A directive inside a quoted command is that command's word; the span is judged as a shape,
   and a verb inside it no longer flags it when its clause reports it ("`Open https://…`
   returns", "возвращал"); `_REPORT_PREDICATE` learned the Russian past/3rd-person forms that
   `_REPORT_LEAD` already had.

4. Performance (the hook has no timeout): slot, verb, addressee and I/we positions are indexed
   once per message; `agent_owns_phrase` is asked only of instructions and skips sentences with
   no I/we. Measured old -> new: 12k "the run" 21 s -> 0.09 s, 12k "please run" 32 s -> 0.1 s,
   5000 bare spans 4.6 s -> 0.09 s; four timed self-test cases pin it.

Evidence: the new self-test cases give 17 FAIL lines on the old functions (controls there fail
only by a different trigger label: old still caught them) and pass now; controls (`Run \`npm
test\` in your terminal`, "Please copy this into PowerShell.", "Запусти у себя \`python x.py\`",
"Set \`FOO=1\` and run it.", "You will need to run …", "Run 3 times …", a dash, a task box)
are caught; guard regressions 289/289; `scripts/mutation_probe.py`: new helpers 30/30 killed;
`shape_is_instruction` + `agent_capable_user_homework` + `agent_owns_phrase` 71/92, the 21
survivors are the ones the same functions had before the change (untouched lines). Replay of
3000 real assistant messages: 201 verdicts dropped (sampled: factual reports), 0 added. A
fresh-context Opus review (HOLD) found a quadratic span path, the digit rule and lost
phrasings; all fixed, its 70-case probe now loses only "Once that is done run the installer."
(no clause break; accepted). Still blocked by old and new alike: "Run time: 3 seconds.", "Open
questions: none." (a label noun at clause start). The scratch-cwd gap moved to its own entry.
An independent re-review of 4052e3a (HOLD) found that the Russian-follows rule read past a
masked one-word command ("Затем run `make` чтобы …", "Please run `setup.ps1` у себя."): six
hand-offs that main blocks passed. The follow-up commit checks only what directly follows the
verb; the six are must-block self-test cases (red on 4052e3a, green now).

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

## 2026-10-28 - STOP-GUARD: HAND-OFFS NEITHER MAIN NOR PR #40 CATCHES

**Status**: arch-decision

Found by the independent re-review of PR #40. Measured 2026-10-28: `agent_capable_user_homework`
returns None for each line on origin/main and on the PR branch alike (probe
`D:/tmp/claude/stopfp/gaps.py`):

- "You can now push with `git push`." (`git push` is not a shape and "push" is not listed)
- "Осталось только выполнить у себя `make release`." / "Нужно будет руками запустить
  `setup.ps1`." (an infinitive after "осталось/нужно" hands work over; the listed forms
  "выполни/запусти" do not match the infinitive "-ить")
- "Перезапусти `nginx` и проверь." / "Сделай `npm ci` перед стартом." (Russian singular
  imperatives outside the list; `_RU_IMPERATIVE` takes only "-ите/-йте/-ьте" because "-и/-й"
  collide with plural nouns and adjectives)
- "Your turn: `make release`." (a lead-in that assigns without a verb)
- "I'll continue in the next session." (a deferral, not a command; belongs to `scan_phrases`)

The choice needed: a Russian imperative/infinitive grammar that does not reopen the noun
collisions, or a short list of hand-off lead-ins. Not fixed in PR #40, whose scope is false
positives.

**Recheck**: each line above as a must-block self-test case, with the report controls of PR
#40 staying silent.

## 2026-09-30 - STOP-GUARD: EVIDENCE-BOUND ORDER NOT FOUND FROM A SCRATCH CWD

**Status**: arch-decision

Split out of the entry above on 2026-10-28; unchanged since 2026-09-30 (`b10aeb3` session).
`has_evidence_bound_external_task` looks only under
`repo_root(Path.cwd())`, so a session whose cwd is a non-git scratch workspace can never
bind its valid BLOCKED_EXTERNAL order. Measured in
`.agent/user-tasks/REQ-5B886CC0BC3A/gate-smoke.log`: bound=False from the scratch cwd,
bound=True from this repo. Smallest split: keep the gate, and when the cwd has no git root,
also look in the repositories the session actually changed (the transcript's Edit/Write
paths), never in arbitrary ones.

## 2026-09-30 15:58 - PUBLIC PUSH BLOCKED: SEMANTIC SCAN CLI OUT OF WEEKLY QUOTA (b10aeb3)

**Status**: RESOLVED 2026-10-28 - waiting commit b10aeb3 is in origin/main; both scan legs ran on every public push today (PRs #23-#31).

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

## 2026-10-15 23:59 - stop/kill approvals read free text heuristically
**Status**: RESOLVED 2026-10-16 - owner left the choice to me; middle option: her own stop requests keep free text, a bare "да" approves only a command I offered with a first-person verb or «Остановить?» right before it (OFFER_LEAD allow-list). Probes hcg-review1..7: 0 unexpected approvals; self-test approve=41 refuse=231.
Six independent reviews of the autostart change (commit "owner can ask to remove a unit from autostart") showed
that word lists never close the free-text classes: the disable path was moved to a whole-message grammar and a
fixed first-person proposal template, after which every probe is refused. The older stop/kill path still uses
heuristics, and a bare "да" approves `kill 4242` after my explanation ("Команда `kill 4242` остановит воркер"),
after instructions for the owner ("выполни у себя: `kill 4242`"), and on "Убить процесс 4242 рано."
(review probe rows STOP expl / STOP for owner / STOP inf).
Options that were weighed: (a) the same strict grammar for stop/kill (safe, but natural phrasings like
"убей 4242, он висит" stop passing) or (b) keep heuristics and accept these classes. The resolution
above is the middle path between them; the three probe rows are now refused.

## 2026-10-28 09:30 - transfer-contract-guard reads a git commit message as a transfer command

**Status**: arch-decision

`git commit -m "... Copy-Item/robocopy ..."` is blocked as a transfer: the quoted
message is data, but `safety_common.executable_text` masks quoted arguments only
for search/print commands. Masking commit messages there is a decision for every
guard that shares the helper (a command substitution inside double quotes still
executes, so the mask must keep it). Workaround: `git commit -F <file>`.
Same class in human-confirmation-guard: a commit message containing the word
`rmdir` was blocked as a deletion (commit e923e33 had to go through -F).
Found by session 71b3da3f while committing 8a36515.

## 2026-10-28 09:30 - handoff Closure Audit and PROBLEMS.md are prose that machines parse

**Status**: RESOLVED (branch feat/handoff-json-sidecar, owner go-ahead 2026-10-28)

Proposal from the mindfulmodeler review (session 71b3da3f): a small JSON sidecar
next to each handoff (status, slug, closure-audit enums, next step, unfinished
items with tracker links) and JSONL entries for PROBLEMS.md, so agent_roster.py
and handoff-closure-audit-guard.py read fields instead of regexes.

Done: optional `X.json` next to handoff `X.md` (`hooks/handoff_sidecar.py`: schema,
validator, `write`/`check` helper). The guard validates it on either file's write and
still accepts prose-only handoffs; agent_roster.py matches by its `session_id` and takes
its `project` first. PROBLEMS.md was not turned into JSONL: the gap was two hooks with
their own parsers and status lists, so `hooks/problems_md.py` now holds the parser and
the status values for problems-md-validator.py and the handoff guard. Accepted
difference for the guard's ticket list: it now reads the validator's looser `Status:`
line (unbolded, indented) and requires `## ` before the date; on 548 real PROBLEMS.md
files x 106 dates both lists matched exactly. Tests:
`hooks/tests/test_handoff_sidecar.py` (in run_guard_regressions.py).

## 2026-10-28 12:30 - harness-load-advisor reads a product's "false positives" as harness overload

**Status**: RESOLVED 2026-10-28 (PR AnastasiyaW/codex-claude-code-config#32, merge 3564cba;
live hook hash 4ef2a06 equals origin/main; 38 tests OK, 26/26 mutants killed, reviewer PROCEED
on f61883f). Remaining known misses: a complaint whose feedback word is more than 40 characters
from the subject; "the gate flags/reports false positives".

The `explicit-feedback` signal matches `ложн\w* срабатыван\w*` / `false positive` anywhere in
the final reply, and `_profile()` labels it `staging-smoke` when "smoke" appears anywhere (here
the file name `click_smoke.py`). A report on a Crossweft sandbox run ("ложных срабатываний про
кнопки не было", the click test `click_smoke.py`) blocked Stop three times although no gate or
profile of ours ran in that session. Fix direction: require a harness/gate subject in the same
sentence for `explicit-feedback` (as `declared-overload` does) and skip negated forms ("не было
ложных срабатываний"). A public-repo hook change needs a red/green test and an independent
reviewer, so it is not patched in passing.
