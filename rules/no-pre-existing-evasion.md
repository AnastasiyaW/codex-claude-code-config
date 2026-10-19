# Rule - No "pre-existing" evasion (Anti-Laziness)

> **Depth (pillars P1/P2/P4)** of the single work-discipline canon → [`finish-the-task.md`](finish-the-task.md).
> That file states the whole principle in one place; this one carries the 5-exception taxonomy + hooks.

Companion document to principle 26. Drop this into a project's
`.claude/rules/` directory or merge into `CLAUDE.md`.

## TL;DR

| Behaviour | Action |
|---|---|
| Found a bug while doing a task | Fix it in this session, or create a ticket with one of 5 reasons |
| First fix attempt failed | Diagnose and retry, do not punt to "next session" |
| "It's out of scope" | Only valid with explicit 5-exception match |
| "It's pre-existing" | Not a valid reason. Git blame does not absolve |
| "Continue in a new session" | Only if context >85% used; otherwise finish now |

## Forbidden phrases (without 5-exception ticket)

These phrases - and their paraphrases - cannot stand as the reason for
not fixing a discovered issue:

- "pre-existing"
- "out of scope" / "outside the current change"
- "known limitation" / "future work"
- "not caused by my changes"
- "deferred for separate refactor" / "needs its own PR"
- "good stopping point" / "natural checkpoint"

The point is not the wording. Phrase-detection alone catches these and
the agent moves to a synonym. The point is the underlying decision: did
you choose not to fix this? If yes, the decision must produce a ticket
with one of the five reasons.

## The five legitimate reasons to defer

Each requires an explicit `## YYYY-MM-DD HH:MM - <heading>` entry in
`PROBLEMS.md` with `**Status**: <reason>`:

1. **missing-data** - data/credentials/repo state needed for the fix
   is not currently obtainable
2. **missing-dep** - tool, library, or service is not installed and
   install requires user-level decision
3. **arch-decision** - resolution requires choice between several valid
   approaches; needs consensus beyond this session
4. **scope-explosion** - resolution grows past task boundaries (>10
   files, >2 systems, >2 hours)
5. **inaccessible-repo** - bug is in a codebase the agent cannot reach

"Complicated", "risky", "pre-existing" are **not** in this list.

## Mandatory artifacts (without them - task is not done)

Every bug-fix must have *durable proof*:

1. **Reproduction**: command or steps that show the bug exists before
2. **Failing check**: test/lint/build that fails before the fix
3. **Passing check**: same check passes after the fix
4. **No regression**: full suite remains green

Not "looks right". Not "should work". Command and output, in writing.

## WIP=1 + VCR Blocking (for projects using feature_list.json)

Source: Learn Harness Engineering, lectures 07-08. See principle 27 (Feature Tracking) for the full framework.

**WIP=1**: in projects with a `feature_list.json` (see `templates/long-run-project/`), at most **one** feature may have `status: "in-progress"` at any time. Starting a second feature while the first is still in progress is forbidden — even with the rationale "the first one is waiting on something." If it's waiting, mark it `blocked` with reason in `evidence`, then start the new one.

**VCR Blocking** (Verified Completion Rate): a feature cannot transition `not-started → in-progress` while a previous feature is still `in-progress`. The previous feature must reach `done` (with full evidence) or `blocked` (with a named blocker) first.

**Why this rule exists**: without WIP=1, agents under context pressure quietly open a second feature when the first hits friction. Days later, both are half-done and neither has verified evidence. WIP=1 forces an explicit choice: finish the current, block it formally, or roll it back to `not-started`. No fuzzy middle.

**Acceptable ways to switch features**:

1. Current feature is **technically blocked** → set `status: "blocked"` with the blocker named in `evidence`, then start a new one
2. **Priorities changed** (user redirected) → roll current back to `not-started`, note the pivot in handoff, start new
3. **Never** two `in-progress` simultaneously

**Connection to the 3-Layer Validation Gate**: `status: "done"` requires `evidence` referencing L1 (syntax/static), L2 (runtime/tests), and L3 (system/e2e) artifacts. VCR is the gate that enforces this — if evidence is empty, you don't get to mark `done`, and the next feature can't enter `in-progress`.

## Workflow when a bug is discovered mid-task

```
1. Record in PROBLEMS.md as OPEN if it cannot be fixed immediately.
2. Estimate scope:
   - Quick (<30 min, <3 files): fix in this session
   - Medium (30 min - 2h, <5 files): fix unless it blocks the current task
   - Large (>2h, >5 files): create ticket with one of 5 reasons
3. If creating a ticket, use one of the 5 valid Status values.
4. "Deferred" or "Skipped" without an entry is a violation.
```

## Mechanical enforcement

This rule is enforced at the Stop event by hooks:

- [test-gate-stop-hook.py](../hooks/test-gate-stop-hook.py) - blocks
  the Stop event if tests are red
- [problems-md-validator.py](../hooks/problems-md-validator.py) -
  blocks the Stop event if PROBLEMS.md has OPEN entries without
  5-exception status
- [stop-phrase-guard.py](../hooks/stop-phrase-guard.py) - detects
  the cardinal phrases (detective layer; agent can rephrase, this is
  back-up)

Hooks beat rules. Rules in CLAUDE.md compete with task-completion
priority and lose under instruction density: measured at 500 concurrent
instructions, the best frontier models hold about 68% accuracy, and the ones
stated earliest survive best (Jaroslawicz et al., "How Many Instructions Can
LLMs Follow at Once?", arXiv 2507.11538). The popular label "compliance decay"
is blog commentary, not the paper's term - do not cite it as such.
Hook-level enforcement runs regardless of
agent reasoning.

## Independent verifier (Layer 3, optional)

For high-stakes bug fixes, before the final commit spawn a
fresh-context agent and ask:

```
You are a verifier in fresh context. The generator just finished a
bug fix. Independently:
1. Read git diff <base..HEAD>
2. Read PROBLEMS.md
3. Read changed files in full

Check:
(a) Each mentioned bug actually fixed (artifact present)?
(b) No issue marked "pre-existing" without a 5-exception ticket?
(c) PROBLEMS.md updated for any genuinely deferred items?
(d) Were any noticed-but-unsummarised bugs missed?

Verdict: PASS / NEEDS_WORK / EVADED-WORK + 2-3 reasons. <200 words.
```

A `NEEDS_WORK` or `EVADED-WORK` verdict returns the task to the
generator. This is the [proof loop](../principles/02-proof-loop.md)
applied to bug-fix tasks specifically.

## Opus 4.7 calibration

Opus 4.7 follows instructions more literally than 4.6. Take advantage
of that by stating bug-fix scope explicitly in every prompt:

```
Constraints (mandatory, do not narrow scope):
- ALL bugs/quality issues encountered MUST be fixed in this session
- Do NOT label any finding as "pre-existing", "out of scope", or
  "separate refactor"
- "Risky" / "complicated" are not valid reasons to skip - they mean
  test more carefully or split into steps
- If a finding genuinely cannot be fixed now, add to PROBLEMS.md with
  one of: missing-data, missing-dep, arch-decision, scope-explosion,
  inaccessible-repo
- "Done" requires durable artifacts, not words
```

## Anti-patterns

- "I fixed A. I also noticed B and C, but those are pre-existing" -
  fix B and C, or create explicit tickets with one of the 5 reasons.
- "Test fails, but it's not from my changes" - still needs fixing;
  cause does not absolve responsibility.
- "Continue in a new session after context refresh" - only if context
  is genuinely >85% used; not "for hygiene".
- "I found 5 issues, I made TODOs for all of them" - TODOs are not
  tickets. Tickets are entries in PROBLEMS.md with valid Status.

## See also

- Principle: [26-no-pre-existing-evasion.md](../principles/26-no-pre-existing-evasion.md)
- Hooks: [test-gate-stop-hook.py](../hooks/test-gate-stop-hook.py),
  [problems-md-validator.py](../hooks/problems-md-validator.py),
  [stop-phrase-guard.py](../hooks/stop-phrase-guard.py)
- Related rule: [no-guessing.md](no-guessing.md) - independent verifier
  agent pattern (used in Layer 3)
