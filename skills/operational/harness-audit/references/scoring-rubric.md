# Scoring Rubric

The five-subsystem audit produces a score from 1 to 5 in each dimension. The numbers are anchored — they are not vibes.

---

## The Five Levels

### 5 — Exemplary

- All hard checks pass
- Most soft checks pass
- Convention is **documented** and its behavior is demonstrated by an inspectable current receipt
- Convention is **consistently followed** in a sample sized to the available evidence; do not require a fixed sample count
- **Mechanical enforcement** has evidence that it executes where applicable (hooks, scripts, schemas)

A 5/5 subsystem is one the user would point to as a model for other projects.

### 4 — Good, mostly complete

- All hard checks pass
- Some soft checks pass
- Convention is mostly documented with one or two bounded evidence gaps
- Available sampled artifacts and receipts substantially follow the convention
- Some mechanical enforcement is evidenced but not comprehensive

A 4/5 subsystem is functional and unlikely to be the bottleneck. Improvement is polish, not foundation.

### 3 — Adequate, covers basics

- Hard checks split: half pass, half fail
- Soft checks mostly miss
- Convention may be documented, but behavior evidence is partial, stale, or inconsistent
- Available sampled artifacts are inconsistent or insufficient to decide
- No mechanical enforcement

A 3/5 subsystem works but degrades over time and across handoffs. Adding structure here gives real returns.

### 2 — Weak, incomplete

- Most hard checks fail
- Soft checks irrelevant (the foundation isn't there)
- Convention only exists by accident (one person did it once)
- Sampled artifacts show it usually doesn't happen
- No enforcement

A 2/5 subsystem is a leak: every session has to rebuild it. This is almost certainly the bottleneck.

### 1 — Missing or actively harmful

- No hard checks pass
- The subsystem is structurally absent
- OR: the subsystem exists but is **actively wrong** (e.g., CLAUDE.md contains contradictory rules; init.sh runs `rm -rf node_modules` unconditionally)

A 1/5 subsystem must be fixed before any work in adjacent subsystems pays back.

---

## How to Pick Between Adjacent Scores

The hard part of scoring is 3 vs 4, or 4 vs 5. Use these tiebreakers, in order:

### 1. Documented vs Demonstrated

- If the convention is **only documented**, cap at 3 until an inspectable receipt demonstrates behavior.
- If documented and demonstrated but not consistently followed: cap at 4.
- Both documented AND demonstrated consistently: eligible for 5.

### 2. Mechanical Enforcement

- No evidence of enforcement execution: cap at 3.
- Soft enforcement (rule says "should") with observed adherence: cap at 4.
- Hard enforcement (hook blocks Stop, schema validates, CI fails) with an execution receipt: eligible for 5.

### 3. Sample Available Relevant Evidence

Inspect enough recent, relevant artifacts to establish a pattern without fabricating a sample size. Include a behavior receipt when the claim is about runtime, CI, or hooks. If evidence is absent or stale, report `unknown` and cap the score rather than inferring success.

Documentation can lie about reality; the audit must distinguish it from demonstrated behavior.

---

## Common Pitfalls

### Don't grade-inflate

The point of the rubric is signal. If every subsystem scores 4-5 by default, the user gets no actionable information. When in doubt, score lower. The user can correct ("actually we do X very well") and the conversation will be more productive than starting from "everything is fine."

### Don't grade-deflate

Conversely, don't score 1 when 2 fits. 1 is reserved for "structurally missing" or "actively harmful". A project with weak handoffs but no PROBLEMS.md is a 2, not a 1.

### Don't double-count

If `init.sh` is missing, that's a Verification problem (3/5 instead of 4/5). It's not also a Lifecycle problem (Lifecycle is about hooks and session boundaries, not about whether init.sh exists). Don't penalize the same gap twice.

### Don't reward metadata or intent

"They were going to add PROBLEMS.md" is not 3/5. Nor is a non-empty evidence field, configured hook, or existing `init.sh` a pass by itself. Score documented structure separately from inspectable behavior; do not turn missing proof into a PASS.

---

## Calibration Examples

### Example 1: Fresh prototype repo

- 1 CLAUDE.md file (50 lines, mostly project description)
- 1 test file
- No .claude/ directory
- Some recent commits

Scoring:

- Instructions: 2 (CLAUDE.md exists but is description, not guidance)
- State: 1 (no handoffs, no PROBLEMS.md, no feature_list)
- Verification: 2 (tests exist but no init.sh, no doc on validation gate)
- Scope: 2 (no scope rules, recent commits show drift)
- Lifecycle: 1 (no hooks, no settings.json)

Total: 8/25. Bottleneck: State (1/5) or Lifecycle (1/5) — tiebreaker: State (fixing it unlocks others).

### Example 2: Mature project with old conventions

- CLAUDE.md (400 lines, mostly current)
- `.claude/rules/` with 5 files
- `.claude/handoffs/` with 30 files going back 6 months, INDEX.md current
- No PROBLEMS.md, no feature_list.json
- A current CI or local receipt demonstrates the documented verification command (Makefile-based)
- `.claude/settings.json` has SessionStart + Stop hooks
- 3 hooks configured: auto_backup_git, stop-test-gate, remind_handoff

Scoring:

- Instructions: 4 (good CLAUDE.md, modular rules, slightly long)
- State: 3 (rich handoffs but missing PROBLEMS.md and feature_list)
- Verification: 4 (current receipt covers the required checks; 3-layer is not explicit but Proof Loop is referenced)
- Scope: 4 (no-pre-existing rule present; this project has no declared serialized lane, so WIP=1 is not a requirement)
- Lifecycle: 4 (hooks configured and one current execution receipt is available; remaining lifecycle behavior has bounded evidence)

Total: 20/25. Bottleneck: State (3/5). One concrete weakness in an otherwise mature project — and a fixable one.

### Example 3: Public OSS skill repo

A repo like `claude-code-skills` itself:

- CLAUDE.md, AGENTS.md, principles/, rules/, templates/, hooks/, MAINTENANCE.md
- UPDATES.md changelog
- Skills with their own SKILL.md following a schema
- No `feature_list.json` (this is a knowledge base, not a feature-delivering project)
- No `init.sh` (no build step)

Scoring (adjusted for project type):

- Instructions: 5
- State: 4 (UPDATES.md serves as a chronicle, but no PROBLEMS.md tracking active issues)
- Verification: 3 (validators exist in scripts/ but no init.sh entry point)
- Scope: 4 (no-pre-existing rule and a project-appropriate concurrency policy)
- Lifecycle: 3 (some hooks but not full lifecycle coverage)

Total: 19/25. Bottleneck: Verification (3/5). The skill repo would benefit from a documented command that runs its required validators and records a current receipt.

**Note**: Score each subsystem against the project's actual acceptance and concurrency model. Do not penalize a knowledge repo, independent lanes, or read-only work for omitting a serialized WIP=1 policy that they do not need.
