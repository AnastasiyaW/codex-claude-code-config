# 02 - Proof Loop: Verification Through Durable Artifacts

**Source:** OpenClaw-RL paper (arxiv 2603.10165) + DenisSergeevitch/repo-task-proof-loop

> **Relationship to [principle 01 - Harness Design](01-harness-design.md):** Generator-Evaluator (principle 01) is the **general pattern** -- two agents, one builds and one judges, applied to any task. Proof Loop is its **specialization for tasks with testable outcomes**: it adds frozen acceptance criteria (spec freeze before build), strict 4-role decomposition (Spec-freezer, Builder, Verifier, Fixer), and a hard requirement that verification happens in a **fresh session** that never saw the build. Use principle 01 for subjective tasks (design quality, copywriting) where evaluation is judgment-heavy. Use principle 02 for tasks where "did it work" has a yes/no answer with a durable artifact (test pass, log entry, file content, API response). They compose: a Proof Loop can use Generator-Evaluator inside its Builder role for the implementation step.

> **Note on OpenClaw:** As of April 4, 2026, Anthropic subscriptions (Claude Pro/Max) no longer cover third-party harness tools including the OpenClaw CLI. The **pattern described here is independent of the tool** - the arxiv paper and the protocol are freely usable. If you want to run OpenClaw as a product, you now need a direct API key or a pay-as-you-go bundle. The Proof Loop pattern itself works with any agent infrastructure.

## Overview

The Proof Loop pattern ensures that AI agents cannot self-certify task completion. Instead of trusting an agent's claim that "it works," the pattern requires durable, verifiable artifacts -- test outputs, log files, verdict documents -- as evidence. A separate verifier in a fresh session (one that never witnessed the build process) examines the repository state and renders a verdict.

**Core principle:** Next-state signals are universal proof. Test results, tool outputs, user reactions -- these are all verification evidence. An agent cannot simply declare completion; it must produce artifacts that an independent party can verify.

### Why this matters: the April 2026 regression case study

Between February and April 2026, Claude Code underwent a quiet reasoning-quality regression: the ratio of `Read` calls to `Edit` calls dropped from 6.6 to 2.0 across 6,852 analyzed sessions. Agents stopped exploring code before modifying it. Edits-without-prior-Read rose from 6.2% to 33.7%. This was only visible because [one investigator](https://github.com/anthropics/claude-code/issues/42796) measured it with rigor - most users felt "something was off" but couldn't articulate what.

The Proof Loop pattern is structurally **immune** to this class of regression: the fresh-session verifier does not care whether the builder's reasoning was sharp, only whether the evidence proves every acceptance criterion. A regressed agent produces broken code; the verifier writes `verdict: FAIL`; the fixer iterates. Output quality is bounded by the spec, not by the model's current capacity.

Vendor-side regressions are inevitable across any agent's lifetime. Make correctness **structural** rather than depending on the model being sharp on any given day. See [alternatives/reasoning-regression-debugging.md](../alternatives/reasoning-regression-debugging.md) for detection and mitigation approaches when you cannot afford full Proof Loop everywhere.

---

## Execution Protocol

The protocol follows a strict sequence:

```
spec freeze --> build --> evidence --> fresh verify --> fix --> verify again
```

### Step 1: Spec Freeze

Define concrete acceptance criteria (AC1, AC2, ...) before any implementation begins. These criteria are:

- **Concrete** -- each criterion maps to a testable condition
- **Frozen** -- no changes once implementation starts
- **Enumerated** -- explicitly numbered for tracking

Example:
```
AC1: Login endpoint returns 200 with valid credentials
AC2: Login endpoint returns 401 with invalid credentials
AC3: Rate limiting kicks in after 5 failed attempts within 60 seconds
AC4: JWT token expires after 24 hours
```

### Step 2: Build

Implement the minimum safe changeset that addresses the acceptance criteria. The builder:

- Writes code to satisfy each AC
- Keeps changes minimal and focused
- Does NOT self-evaluate quality

### Step 3: Evidence Collection

After building, the builder switches to **read-only mode** and collects evidence:

- Runs the test suite, captures output to a file
- Captures relevant log output
- Documents the state of each AC (pass/fail with evidence)
- Stores evidence in the repository (e.g., `.agent/tasks/{task-id}/evidence/`)

**Critical:** The builder collects evidence but does NOT render a verdict. Evidence and judgment are separate responsibilities.

### Step 4: Fresh Verify

A **new session** -- one that has never seen the build process -- examines:

- The repository state (code changes)
- The evidence files
- The acceptance criteria

The verifier produces a `verdict.json`:
```json
{
  "task_id": "login-auth-flow",
  "verdict": "FAIL",
  "ac_results": {
    "AC1": "PASS",
    "AC2": "PASS",
    "AC3": "FAIL - rate limit triggers at 10 attempts, not 5",
    "AC4": "PASS"
  },
  "problems": ["Rate limit threshold is 10, AC3 requires 5"]
}
```

### Step 5: Fix

If the verdict is FAIL:

- Read `problems.md` or the verdict file
- Apply **minimal** fixes targeting only the failing ACs
- Regenerate evidence

### Step 6: Loop

Repeat steps 4-5 until the verdict is PASS across all acceptance criteria.

## Candidate-State Test Sequence

The Proof Loop does not mean running every expensive check after every line.
This is a universal testing sequence, not a VM-specific workflow:

```text
focused local slice -> risk-based review -> one full matrix -> conditional specialized proof
```

- **Focused local slice:** while changing code, run the smallest deterministic
  checks that exercise the changed behavior or reproduction. This is the loop's
  fast feedback and may run repeatedly.
- **Independent review:** for a boundary/high-risk change, a fresh evaluator
  checks the exact changed surface and records a verdict. More of the builder's
  own tests is not a substitute for independence.
- **Full matrix:** at the candidate commit/merge/release boundary, run the
  complete project matrix once on the final candidate. Do not attach this cost
  to every small commit or edit.
- **Conditional specialized proof:** only when the acceptance criteria depend
  on a VM, GPU, OS/ABI, browser, hardware, performance, stress, or another
  specialized environment, run that proof against the exact candidate commit
  or artifact digest. If none applies, record an explicit N/A. Any candidate
  change invalidates all candidate-bound evidence, so the changed candidate
  needs a fresh matrix and fresh specialized proof when applicable.

The shared `test-gate-stop-hook.py` enforces the first two boundaries: `fast` for
normal source changes, optional `integration` for high-risk changes, and a
path-keyed independent-review requirement. It intentionally excludes the
full/candidate matrix from automatic per-edit execution. `harness-load-advisor.py`
reports when a costly or specialized gate is misrouted into a lower-risk smoke.
Full-matrix and specialized-environment evidence are explicit candidate steps,
not silent repeated work.

---

## Four Sub-Agent Roles

Each role has strict boundaries to prevent contamination:

| Role | Reads | Writes | Cannot Do |
|---|---|---|---|
| **Spec-freezer** | Repository, requirements, existing tests | Acceptance criteria document | Touch code |
| **Builder** | Spec, codebase | Code changes, then evidence (read-only switch) | Render verdict |
| **Verifier** | Repo state, evidence, acceptance criteria | Verdict only | See build history, modify code |
| **Fixer** | Verdict, problems list, code | Minimal targeted fixes | Sign final approval |

### Why these boundaries matter

- **Spec-freezer** does not touch code because spec and implementation must be independent
- **Builder** switches to read-only for evidence because the same agent that wrote the code will be biased about its quality
- **Verifier** uses a fresh session because shared context creates shared blind spots
- **Fixer** cannot approve because the same entity that patches should not also certify

---

## Key Differences from Anthropic Harness

The Proof Loop extends the Harness Design pattern (see [01-harness-design.md](01-harness-design.md)) with important distinctions:

| Aspect | Anthropic Harness | Proof Loop |
|---|---|---|
| **Artifact storage** | Conversation history | Repository (`.agent/tasks/`) |
| **Verifier isolation** | Separate prompt in same session | Fresh session (separate context entirely) |
| **Spec mutability** | Sprint Contract can change mid-sprint | Spec frozen before build begins |
| **Evidence format** | Evaluator's judgment | Durable files (test output, logs, verdict.json) |
| **Recommended runtime** | Any LLM agent | Designed for Codex-class sub-agents, works in Claude Code |

### Why repository-based artifacts?

- Conversation history is ephemeral -- it disappears with the session
- Repository artifacts survive context resets, session changes, and model swaps
- Other agents (or humans) can independently verify the same artifacts
- Git provides versioning and audit trail for free

### Why fresh-session verification?

A verifier in the same session has seen:
- The builder's reasoning process
- The builder's confidence signals
- Intermediate states that may have been "fixed"

This creates anchoring bias. A fresh session sees only the final state and the evidence, judging purely on outcomes.

---

## Anti-Fabrication Rules

The Proof Loop includes explicit guards against agents fabricating completion:

1. **Tests passed?** -- Requires a file with actual output, not the text "tests passed"
2. **Review done?** -- Requires an artifact with specific findings, not "I reviewed it, looks good"
3. **Subtask complete?** -- Check the state file, do not trust the agent's claim
4. **Parallel/subagent tasks:** Before accepting results, verify that child processes actually completed -- do not trust status claims from sub-agents

---

## File Structure

A typical Proof Loop task directory in the repository:

```
.agent/tasks/
  login-auth-flow/
    spec.md                 # Frozen acceptance criteria
    evidence/
      test-output.txt       # Raw test runner output
      coverage-report.html  # Coverage artifact
      api-responses.json    # Captured API responses
    verdict.json            # Verifier's judgment
    problems.md             # Issues found (if FAIL)
    fix-log.md              # What the fixer changed and why
```

Starter files live in [`templates/agent-task/`](../templates/agent-task/). Copy them into `.agent/tasks/<task-id>/` for long-running, multi-agent, high-risk, or compaction-prone work.

---

## When to Use

**Good fit:**
- Production deployments where failure has real cost
- Tasks requiring audit trails (compliance, security)
- Multi-agent handoffs where trust boundaries are important
- Any task where "the agent says it works" is not sufficient

**Overkill:**
- Quick prototyping
- Single-file changes with obvious correctness
- Exploratory coding where the spec is still forming

---

## Revision Trajectories: Learning from Corrected Mistakes

**Source:** Agent-R (arxiv 2501.11425)

A key insight from Agent-R: **trajectories where mistakes are caught and fixed teach more than perfect trajectories.** The failed-then-fixed cycle is the most valuable learning material.

This maps directly to the Proof Loop:

1. **The fix -> verify again cycle is the most valuable part.** When the Builder produces code that fails Verifier checks, the resulting fix trajectory carries more information than a clean first-pass build.

2. **Capture error -> fix trajectories explicitly.** When a verdict is FAIL:
   - Log the exact failure point (which AC, which file, which assumption was wrong)
   - Log the reflection (why it failed -- root cause, not surface symptom)
   - Log the minimal fix applied
   - Log the re-verification result
   - This becomes `fix-log.md` with structured fields, not free-text narrative

3. **Structured Evaluator feedback.** Instead of "please fix these issues," the Verifier should provide:
   - **Cut point** -- the first file/decision where the implementation diverged from the spec
   - **Reflection** -- why the approach failed (e.g., "assumed synchronous execution but the API is async")
   - **Direction** -- what a correct approach looks like (not the solution, but the direction)

This format gives the Fixer a precise recovery point instead of a vague issues list.

### problems.md Schema

A structured format for the Verifier's problem reports:

```markdown
## Problem: AC3 - Rate limit threshold

- **Criterion:** AC3
- **Status:** FAIL
- **Reproduction:** POST /login 6 times with wrong password in 60s -> still returns 401, not 429
- **Expected:** 429 after 5 attempts
- **Actual:** 401 continues indefinitely
- **Affected files:** src/middleware/rateLimit.ts:42
- **Smallest safe fix:** Change threshold constant from 10 to 5
- **Root cause:** Default imported from config that uses a different rate limit context
```

---

## Reliability Metrics: Accuracy Is Not Enough

**Source:** [Towards a Science of AI Agent Reliability, arxiv 2602.16666](https://arxiv.org/html/2602.16666v1)

Standard benchmarks measure **accuracy** - did the agent pass this task once? Proof Loop historically has measured the same: did the AC list pass verification once? But recent evaluation of 14 agentic models across OpenAI, Google, and Anthropic shows a sobering pattern: **reliability grows slower than accuracy**. Frontier models climb steadily on accuracy benchmarks while showing only small reliability improvements on structured tasks and nearly flat progress on open-ended tasks.

The practical implication: a PASS verdict on a single proof loop run is weaker evidence than it appears.

### The Reliability Dimensions

The paper operationalizes reliability across four dimensions. Add at least one check from each to your Proof Loop verdict:

**Consistency** - does the agent succeed repeatedly?
- Outcome consistency: run the verifier on the same AC set 3-5 times. Variance in pass rate exposes flaky builds.
- Trajectory consistency: record the action sequence. Repeated runs should produce similar traces, not random wanders.

**Robustness** - does the agent survive small perturbations?
- Prompt robustness: paraphrase the AC list and re-run. A truly passing build handles paraphrased requirements.
- Environment robustness: re-run with a cleared cache, different CWD, or reordered inputs.

**Predictability** - is the agent calibrated?
- Calibration: ask the agent for its confidence before verification. Compare confidence to actual pass rate. Overconfident agents are dangerous.
- AUROC: can the agent distinguish its own successes from failures?

**Safety** - does the agent stay within boundaries?
- Compliance: count constraint violations per run.
- Harm severity: classify violations by consequence magnitude.

### Concrete Extension to the Proof Loop

Replace the single PASS/FAIL verdict with a tuple:

```markdown
## verdict.json
{
  "accuracy": "PASS",
  "consistency": {"runs": 5, "pass_count": 5, "variance": 0.0},
  "robustness": {"paraphrased_pass": true, "clean_cache_pass": true},
  "calibration": {"builder_confidence": 0.92, "actual_pass_rate": 1.0},
  "safety": {"violations": 0, "severity": "none"}
}
```

A verdict with `accuracy=PASS` but `consistency.variance > 0.2` is not a passing verdict - it is an unstable build that happened to pass once. Treat it as FAIL and loop again.

### Minimum Viable Adoption

If adding all four dimensions feels expensive, start with two:

1. **Multi-run consistency** - run the verifier 3x. If any run FAILS, the build is unstable.
2. **Prompt paraphrase** - rewrite the AC list in a second phrasing. If the paraphrased run fails, the build is accuracy-brittle.

These two checks alone expose most "lucky pass" builds that single-run verification misses.

---

## Relationship to Other Principles

- **Harness Design (01):** Proof Loop extends the Generator-Evaluator pattern with fresh-session verification
- **Autoresearch (03):** Autoresearch optimizes iteratively; Proof Loop verifies the final result. Failed experiments carry direction signals (Agent-R insight)
- **Deterministic Orchestration (04):** Anti-Fabrication is a shared concern -- both patterns insist on artifacts over claims
- **Codified Context (07):** The `.agent/tasks/` directory structure is codified context -- structured handoff artifacts
