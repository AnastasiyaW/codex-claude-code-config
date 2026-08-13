---
name: proof-verify
description: Plan-based verification - freeze acceptance criteria before building, then verify after with an independent fresh-context agent (the builder must not verify their own work). For multi-stage work, seal accepted inputs with commit/tree, contract, input/output digests, and a fresh verdict so downstream stages do not reopen them. Use when - "verify against plan", "proof check", "independent review", "check the implementation", or confirming a feature built from a plan meets spec. Do NOT use for quick one-off checks with no plan, or for letting the builder self-verify.
---

# Proof Verify

Plan-based verification: freeze acceptance criteria BEFORE building, verify AFTER with independent agents.

## When to Use

- After completing a feature/fix that was built from a plan
- When you need independent confirmation that work meets spec
- When the builder should NOT verify their own work
- Trigger phrases: "verify against plan", "check the implementation", "proof check", "independent review"

## The Pattern

```
PHASE 1: PLAN (before any code)
  Create .proof/PLAN.md with numbered acceptance criteria
  Each AC: testable, specific, has a verification command or check
  Plan is FROZEN - no changes during build

PHASE 2: BUILD (normal work)
  Implement against the plan
  Mark progress in .proof/PROGRESS.md
  Builder does NOT self-verify

PHASE 3: VERIFY (after build, independent agent)
  Fresh agent reads PLAN.md (never saw the build process)
  Walks through each AC, runs verification commands
  Writes .proof/VERDICT.md with PASS/FAIL per criterion
  If any FAIL → .proof/PROBLEMS.md with specific fixes

PHASE 4: FIX (if needed)
  Builder reads PROBLEMS.md, makes minimal fixes
  Back to PHASE 3 (re-verify)
  Loop until all PASS
```

## Stage Ledger - only when proof feeds another stage

For a release, integration, migration, hardware, signer, or other multi-stage
task, a green check is not enough. The next stage needs a stable input, not a
summary that the previous stage once looked good.

1. Freeze the stage contract and its scope before building it.
2. Run the focused proof and obtain the fresh verdict as usual.
3. Write the stage to `.proof/stage-ledger.json` as `VERIFIED` or `SEALED`.
   A sealed stage records its source commit/tree, contract digest, named input and
   output digests, fresh verdict digest, and invalidation keys.
4. A downstream stage names the sealed parent and exact output digest it consumes.
   It must not consume a merely `VERIFIED` or `BLOCKED` stage.
5. If an external dependency is missing, record `BLOCKED` with the exact missing
   prerequisite. Do not invalidate the sealed upstream code.
6. If code, contract, or an input digest changes, add a `SUPERSEDED` successor and
   re-run proof for that successor; do not overwrite the old receipt.

Validate the ledger deterministically:

```text
python skills/development/proof-verify/scripts/validate_stage_ledger.py \
  .proof/stage-ledger.json
```

The ledger is not a signing ceremony for every edit. Use it only when an accepted
result crosses a real project boundary. Full format, status semantics, and examples:
`references/proven-stage-contracts.md`.

## Phase 1: Create Plan

Create `.proof/PLAN.md` in the project root:

```markdown
# Verification Plan

**Created:** YYYY-MM-DD HH:MM
**Task:** [one-line description]
**Builder:** [session ID or "current"]
**Status:** FROZEN

## Acceptance Criteria

### AC1: [short name]
**Description:** [what must be true]
**Verify:** [exact command or check to run]
**Expected:** [what success looks like]

### AC2: [short name]
**Description:** [what must be true]
**Verify:** [exact command or check to run]
**Expected:** [what success looks like]

### AC3: [short name]
...

## Out of Scope
- [explicitly what this plan does NOT cover]

## Constraints
- [time, resource, or technical constraints]
```

Rules for good ACs:
- **Testable** - there is a command or check that produces PASS/FAIL
- **Specific** - "function returns correct value" not "code works"
- **Independent** - each AC can be verified without the others
- **3-8 ACs** - fewer than 3 = loopholes, more than 8 = checklist gaming
- **Frozen** - once written, do not modify during build

## Phase 2: Build

Normal implementation. The only additions:

1. Create `.proof/PROGRESS.md` as you work:

```markdown
# Build Progress

### AC1: [name]
- [x] Implemented in `src/foo.py:42`
- Files changed: `src/foo.py`, `tests/test_foo.py`

### AC2: [name]
- [x] Implemented in `src/bar.py:18`
- Files changed: `src/bar.py`
- Note: chose approach B because [reason]
```

2. After build is complete, write `.proof/EVIDENCE.md`:

```markdown
# Evidence

### AC1: [name]
**Command:** `pytest tests/test_foo.py -v`
**Output:**
\```
tests/test_foo.py::test_returns_correct PASSED
tests/test_foo.py::test_handles_edge PASSED
\```
**Result:** PASS

### AC2: [name]
**Command:** `grep -c "TODO" src/bar.py`
**Output:** `0`
**Result:** PASS
```

Builder collects evidence but does NOT write the verdict. That is the verifier's job.

## Phase 3: Verify (Independent Agent)

This is the critical phase. The verifier MUST be:
- A **fresh agent** (new session or subagent) that never saw the build
- Given ONLY: `PLAN.md` + access to the codebase
- NOT given: `PROGRESS.md`, `EVIDENCE.md`, or any build context

### Verifier prompt template

```
You are an independent verifier. Your job is to check whether
the implementation meets the acceptance criteria in .proof/PLAN.md.

Rules:
1. Read .proof/PLAN.md first. This is your ONLY specification.
2. For each AC, run the verification command yourself.
3. Do NOT read .proof/PROGRESS.md or .proof/EVIDENCE.md
   (those are the builder's claims - you verify independently).
4. Write your verdict to .proof/VERDICT.md in this format:

# Verification Verdict

**Verifier:** [your session ID]
**Date:** YYYY-MM-DD HH:MM
**Plan hash:** [first 8 chars of md5 of PLAN.md]

## Results

### AC1: [name]
**Status:** PASS | FAIL
**Evidence:** [what you saw when you ran the check]
**Notes:** [any observations]

### AC2: [name]
...

## Summary
- Total: N criteria
- Passed: X
- Failed: Y
- **Overall:** PASS | FAIL

5. If any AC fails, also create .proof/PROBLEMS.md:

# Problems

### AC2: [name]
**Expected:** [from PLAN.md]
**Actual:** [what you found]
**Suggested fix:** [smallest change that would fix it]
**Affected files:** [list]

6. Do NOT fix anything. You are read-only. Report only.
```

### How to spawn the verifier

**Option A: Subagent (same session)**
```
Agent({
  description: "Independent verification against plan",
  prompt: "[verifier prompt above]",
  mode: "plan"  // read-only first
})
```

**Option B: Fresh session (stronger isolation)**
Write handoff with instruction: "Start by reading .proof/PLAN.md and running verification."

**Option C: Multiple verifiers (highest confidence)**
Spawn 2-3 verifiers independently. If they disagree on any AC, that AC needs investigation.

## Phase 4: Fix Loop

If VERDICT.md shows any FAIL:

1. Builder reads `PROBLEMS.md`
2. Makes **minimal** fixes (not refactoring, not "while I'm here")
3. Updates `EVIDENCE.md` with new evidence for failed ACs
4. Verifier runs again (Phase 3)
5. Loop until all PASS

Typical: 1-2 fix rounds. If 3+ rounds on same AC → the AC itself might be wrong. Revisit PLAN.md.

## File Structure

```
.proof/
  PLAN.md        # frozen acceptance criteria (Phase 1)
  PROGRESS.md    # builder's notes (Phase 2)
  EVIDENCE.md    # builder's evidence (Phase 2)
  VERDICT.md     # verifier's verdict (Phase 3)
  PROBLEMS.md    # verifier's findings (Phase 3, if failures)
  stage-ledger.json # only for multi-stage work; accepted inputs and blockers
```

## Gotchas

- **Builder reads VERDICT, not the reverse.** Verifier never sees builder's evidence. This prevents confirmation bias.
- **"PASS with concerns" is FAIL.** Either it passes or it doesn't. No soft passes.
- **Plan hash in verdict.** If someone edited PLAN.md mid-build, the hash won't match. Catch.
- **A later blocker is not retroactive failure.** A missing VM, signer, or account
  blocks its own stage. It does not turn a sealed source or artifact into a failed one.
- **Do not reuse stale proof.** A changed contract, source tree, or recorded input
  requires a successor stage and a fresh verdict.
- **Time limit.** If verification takes >30 min, the ACs are too vague. Rewrite them.
- **Don't verify style.** ACs should be functional ("function returns X"), not stylistic ("code is clean"). Style is for code review, not proof loop.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Verifier passes everything | ACs too vague | Rewrite with specific commands |
| 3+ fix rounds on same AC | AC is wrong or untestable | Revisit PLAN.md |
| Verifier disagrees with builder's evidence | Different env or stale state | Both run from clean state |
| Builder keeps editing PLAN.md | Not frozen | Hash check catches this |
| A new audit says an old stage is "missing" | It mixed an unavailable next prerequisite with already-proven scope | Check `.proof/stage-ledger.json`; record the external `BLOCKED` stage separately |
| Downstream proof cannot identify its input | The prior result was a chat claim, not a sealed receipt | Seal the prior stage with commit/tree, digests, and fresh verdict before proceeding |

## Sources

- [Proof Loop (Principle 02)](../../../principles/02-proof-loop.md) - the theoretical foundation
- `references/proven-stage-contracts.md` - immutable stage promotion, provenance, and local ledger contract
- [OpenClaw-RL](https://arxiv.org/abs/2603.10165) - spec freeze → build → fresh verify
- [Agent-R](https://arxiv.org/abs/2501.11425) - failed-then-fixed trajectories
- oh-my-claudecode Ralph - PRD-driven persistence (practical inspiration)
