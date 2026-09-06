---
name: plan-swarm-review
description: |
  Iterative plan review using multisampling + focused decomposition.
  Launches parallel independent agents to find issues that single-pass
  review misses. Up to four bounded rounds: broad, multisample, focused,
  focused-plus-multisample. Use when: "swarm review", "review plan thoroughly",
  "multisample review", "deep plan review", "plan swarming", "stress test
  the plan", or when evidenced cross-component risk warrants deeper plan review.
  Size alone does not require a swarm or another review round. Do NOT use to
  design a multi-agent harness or Generator-Evaluator architecture from scratch;
  use harness-design for that. Ordinary code/diff review routes to deep-review;
  use this skill's code mode only when the user explicitly requests a swarm
  security/bug review of code.
metadata:
  user-invocable: true
  upstream-model-hint: opus
allowed-tools:
  - Read
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
  - TodoWrite
  - Edit
  - Write
---

# Plan Swarm Review

Iterative plan hardening through multisampling and focused decomposition.

## Scope and task ownership

The user's current task and selected model govern this review. Audit-only is
read-only unless changes are requested. In an already authorized implementation
or repair task, apply confirmed in-scope reversible fixes and run their focused
causal checks; do not ask again merely because a review round found the problem.
An optional deeper review does not block those fixes or the original milestone.
Stop expanding review when the current acceptance criteria are sufficiently
proved, then return to the owning task. Preserve actual external, deletion, and
irreversible boundaries. The four rounds are a bounded menu, not a required loop.

**Core insight**: a single agent misses issues due to attention budget limits.
Multiple independent agents reading the same document find different problems
(stochastic diversity). Focused decomposition further improves depth per aspect.
Iterative fix-then-re-review uncovers issues previously masked by other bugs.

Source: deksden (@deksden_notes) — "Plan Swarming" technique, April 2026.
Related: Anthropic Harness Design (Generator-Evaluator), deep-review (parallel competency code review).

Research backing:
- [2502.11027] Sampling diversity in LLM inference — diverse prompts beat identical: +10.8% reasoning, +9.5% code
- [2602.09341] AgentAuditor — reasoning tree audit beats majority voting, recovers 65-82% of minority-correct findings
- [2602.17875] MultiVer — 4 parallel agents hit 82.7% recall on vulnerability detection (beats fine-tuned models)
- [2510.00317] MAVUL — multi-agent vuln detection: +600% vs single-agent
- Anthropic Code Review (Mar 2026) — parallel agents raise substantive findings from 16% to 54%

## Modes

This skill works in two modes:

**Plan mode** (default): review design docs, specs, ADRs, RFCs before implementation.
**Code mode**: review code files for bugs and vulnerabilities when the user
explicitly requests a swarm code review. Merely supplying a diff or asking for
ordinary code review routes to `deep-review`. In code mode, aspects shift from plan-oriented (contracts,
completeness) to code-oriented (injection, auth bypass, race conditions, memory).

---

## Step 0: Identify the target document

Ask the user which document to review if not obvious from context.

**Plan mode**: PLAN.md, ADR, spec, design doc, RFC, or any structured
document describing what will be built and how.

**Code mode**: source code files, a module, or a directory. Best for
security audits, bug hunts, or pre-release quality checks.

```
Read the target document(s) fully. Note:
- Total size (lines, sections/files)
- Key components/modules described or implemented
- Interfaces between components
- Data flows and mutations
- External dependencies and trust boundaries
```

If the target is <100 lines with 1-2 simple components, suggest a single-pass
review instead — swarming is overkill for small targets.

---

## Step 1: ROUND 1 — Broad Review (single agent)

**Purpose**: catch obvious issues before spending tokens on multisampling.

Launch ONE Agent with this prompt:

```
You are a senior architect reviewing a plan document before implementation.
Your goal: find issues that would cause bugs, rework, or confusion during
implementation.

## Plan to review
{paste or reference the plan document path}

Read the entire plan. Then check for:

1. CONTRACTS — are interfaces between components fully specified?
   Types, error codes, required vs optional fields, versioning.
2. DATA FLOW — is data transformation described end-to-end?
   What happens at each boundary? Backward compatibility?
3. NEGATIVE SCENARIOS — what happens when things fail?
   Timeouts, partial failures, invalid input, race conditions.
4. CONSISTENCY — do different sections contradict each other?
   Same entity described differently in two places?
5. COMPLETENESS — are there gaps? Steps that say "TBD" or "later"?
   Scenarios mentioned but not covered?
6. DEPENDENCIES — is implementation order clear?
   Are blocking dependencies identified? Circular deps?
7. AMBIGUITY — could two engineers read a section and implement
   it differently? Vague terms like "handle appropriately"?

## Output format
For EACH finding:

FINDING: {one-line description}
SECTION: {which section of the plan}
SEVERITY: HIGH | MEDIUM | LOW
EVIDENCE: {quote the problematic text, max 2 lines}
FIX: {concrete change to the plan text}

If the plan is clean — output: "NO_FINDINGS — plan review clean."
Do NOT pad with praise. Only problems.
```

### After Round 1

Collect findings. If **0 findings** → finish this review scope and return to the
owning task; this is not proof that an implementation milestone is finished.

If findings exist:
1. Present findings to user grouped by severity
2. If fixes are already authorized, apply the confirmed scoped corrections and
   run their focused checks. Otherwise report them within the audit-only request.
3. Consider Round 2 only for a remaining concrete risk or an explicit depth request;
   do not bundle permission for optional review with already authorized fixes.
4. If user says stop → stop

---

## Step 2: ROUND 2 — Diverse Multisampling (N parallel agents, varied perspectives)

**Purpose**: stochastic diversity catches what one pass missed.

**IMPORTANT**: do NOT use identical prompts for all agents. Research [2502.11027]
shows identical prompts produce correlated errors — agents "cluster" on the same
issues and miss the same blind spots. Instead, give each agent a DIFFERENT
perspective while reviewing the same document.

Launch **3 agents in parallel** (or 5 for critical plans), each with a
**different reviewer persona**:

**CRITICAL**: launch all agents in a SINGLE message (parallel tool calls).
Each agent has isolated context — no cross-contamination.

### Plan mode perspectives

| Agent | Persona | Focus bias |
|---|---|---|
| 1 | **Skeptical implementer** | "I have to code this tomorrow — what's unclear, contradictory, or impossible?" |
| 2 | **Security auditor** | "Where are the trust boundaries? What happens with malicious input?" |
| 3 | **QA engineer** | "How do I test this? What edge cases aren't covered? What breaks at scale?" |
| 4 | **New team member** | "I just joined — what terms are undefined? What implicit knowledge is required?" |
| 5 | **Ops/SRE** | "What fails at 3am? What's the rollback plan? What's unmonitored?" |

### Code mode perspectives

| Agent | Persona | Focus bias |
|---|---|---|
| 1 | **Attacker** | "How do I exploit this? Injection, auth bypass, privilege escalation?" |
| 2 | **Concurrency specialist** | "What races, deadlocks, or ordering issues exist?" |
| 3 | **Performance engineer** | "What's O(n^2)? What allocates unbounded memory? What blocks the event loop?" |
| 4 | **Error recovery auditor** | "What happens when X fails? Is cleanup correct? Are resources leaked?" |
| 5 | **Integration tester** | "Do contracts match? Are types compatible? What breaks at boundaries?" |

```
You are a {PERSONA} reviewing {plan/code} before implementation/deployment.
Your perspective: {FOCUS_BIAS}

Review the ENTIRE document through your specific lens.
{same checklist and output format as Round 1}
```

### After Round 2

1. **Deduplicate**: group findings by section + issue type. When multiple
   agents find the same issue → mark as HIGH CONFIDENCE (consensus).
2. **Preserve minority findings**: a finding from only 1 of 5 agents is
   NOT automatically low-value. Research [2602.09341] shows minority-correct
   findings are often the most valuable — non-obvious bugs that only one
   perspective catches. Flag these as UNIQUE CATCH, do not discard.
3. **Synthesize**: produce merged report. Separate consensus vs unique catches.
4. Present to user with round report format (see Output Format below).
5. Apply already authorized scoped fixes; use Round 3 only for a concrete unresolved
   risk or an explicit depth request, not as a condition for continuing implementation.

**Review stop criteria**: no unresolved finding affecting current acceptance or
safety. A severity count is not proof: two material medium findings still need
resolution. End this review branch without abandoning the owning task.

---

## Step 3: ROUND 3 — Focused Review (decompose into aspects)

**Purpose**: narrow scope = deeper analysis per aspect.

### Step 3a: Determine focus aspects

Based on the target content, select 3-7 aspects.

### Plan mode aspects

| Aspect | When to include |
|---|---|
| **Contracts & Interfaces** | Plan describes >2 interacting components |
| **Data Flow & Migrations** | Plan involves data transformation, DB changes, or state migration |
| **Negative Scenarios** | Plan describes user-facing features or distributed systems |
| **Consistency** | Plan is >300 lines or written by multiple authors |
| **Completeness** | Plan references external systems or has phased rollout |
| **Security & Trust** | Plan involves auth, user input, or external APIs |
| **Dependencies & Order** | Plan has >5 implementation steps or parallel workstreams |

### Code mode aspects (for bug/vulnerability hunting)

**Before launching agents:** read `references/vulnerability-kb.md` for condensed detection
heuristics per CWE class. Feed the relevant CWE heuristics into each agent's prompt.
Full Vul-RAG entries with code examples: `knowledge-vault/docs/security/cwe/`.

Based on MultiVer [2602.17875] and VulAgent [2509.11523] patterns:

| Aspect | What to trace |
|---|---|
| **Injection & Input Validation** | SQL/NoSQL/command/LDAP injection, XSS, path traversal, template injection |
| **Auth & Access Control** | Auth bypass, privilege escalation, IDOR, missing authorization checks |
| **Concurrency & State** | Race conditions, TOCTOU, deadlocks, shared mutable state, atomicity violations |
| **Memory & Resources** | Buffer overflows, use-after-free, resource leaks, unbounded allocations |
| **Error Handling & Recovery** | Swallowed errors, info leakage in errors, incomplete cleanup, missing rollback |
| **Cryptography & Secrets** | Weak algorithms, hardcoded secrets, improper random, timing attacks |
| **Business Logic** | State machine violations, numeric overflow in prices, missing validation of business rules |

Present selected aspects to user: "I'll focus review on these {N} aspects: ..."

### Step 3b: Launch focused agents

For each aspect, launch ONE Agent with a FOCUSED prompt:

```
You are reviewing a plan document with a SINGLE focus: {ASPECT_NAME}.
Ignore everything outside your focus area — other reviewers handle those.

## Your focus: {ASPECT_NAME}
{ASPECT_DESCRIPTION — 2-3 sentences explaining what to look for}

## Plan to review
{reference the plan document path — the latest version with all prior fixes}

Read the ENTIRE plan but analyze ONLY through the lens of {ASPECT_NAME}.
Go deep: trace every {aspect-relevant thing} end-to-end. Check that every
scenario is complete, every interface is specified, every edge case is handled.

## Output format
FINDING: {one-line description}
SECTION: {which section}
SEVERITY: HIGH | MEDIUM | LOW
ASPECT: {ASPECT_NAME}
EVIDENCE: {quote, max 2 lines}
FIX: {concrete change}

If clean — output: "NO_FINDINGS — {ASPECT_NAME} review clean."
```

**Launch ALL aspect agents in a SINGLE message** (parallel).

### After Round 3

Same dedup + synthesis. Present focused report.

Use the same acceptance-bound review stop criteria. Optional Round 4 is a separate
depth decision; already authorized fixes and delivery do not wait for it.

---

## Step 4: ROUND 4 — Focused + Multisampling (optional, expensive)

**Purpose**: maximum depth. Only for critical plans where Round 3 still found high-severity issues.

**Gate**: ask user explicitly: "Round 3 still found {N} high-severity issues.
Round 4 will launch {aspects x 2-3} agents (~{estimate} tokens). Continue?"

For each aspect from Round 3 that had findings, launch **2-3 agents** with
the same focused prompt. Same parallel launch pattern.

### After Round 4

Final synthesis. At this depth, the plan should be clean.
If still finding high-severity issues → the plan likely needs structural
rework, not just polish. Tell the user.

---

## Output Format (used after each round)

```
====================================================
  ROUND {N}: {BROAD | MULTISAMPLE | FOCUSED | FOCUSED+MULTISAMPLE}
  Agents: {count}  |  New findings: {count}  |  Dupes removed: {count}
====================================================

-- HIGH ({count}) ------------------------------------
  1. [{aspect}] {description}
     Section: {section reference}
     Evidence: "{quoted text}"
     Fix: {concrete change}
     Confidence: {HIGH if found by multiple agents, MEDIUM otherwise}

-- MEDIUM ({count}) ----------------------------------
  2. [{aspect}] {description}
     ...

-- LOW ({count}) -------------------------------------
  3. ...

====================================================
  CUMULATIVE: {total_high} high / {total_medium} medium / {total_low} low
  RECOMMENDATION: CONTINUE -> Round {N+1} | STOP - plan is clean
====================================================
```

---

## Step 5: Final summary

After the last round (wherever the process stops):

```
====================================================
  PLAN SWARM REVIEW COMPLETE
====================================================
  Rounds executed: {N}
  Total agents launched: {count}
  Total findings: {count} ({fixed} fixed, {deferred} deferred)

  By severity:
    HIGH:   {count found} -> {count fixed}
    MEDIUM: {count found} -> {count fixed}
    LOW:    {count found} -> {count fixed}

  Round breakdown:
    R1 (broad):       {findings_count} findings
    R2 (multisample): {findings_count} findings
    R3 (focused):     {findings_count} findings
    R4 (focus+multi): {findings_count} findings

  VERDICT: {HARDENED | IMPROVED | NEEDS_REWORK}
====================================================
```

Verdicts:
- **HARDENED** — no unresolved acceptance-critical finding in the reviewed scope;
  this is not a blanket safety or runtime certification
- **IMPROVED** — significant issues found and fixed, some medium deferred
- **NEEDS_REWORK** — structural issues remain, plan needs major revision

---

## Gotchas

- **Token cost**: Round 4 with 7 aspects x 3 samples = 21 agent launches.
  Always confirm with user before expensive rounds.
- **Plan mutations between rounds**: after applying fixes, the plan changes.
  Each new round MUST read the UPDATED plan, not the original.
  Reference the file path, not inline text, so agents always read current version.
- **Subagent depth**: use the actual host's supported delegation limits. For this
  workflow, reviewers inspect their assigned scope directly rather than silently
  expanding the coordinator's agreed review budget.
- **Diminishing returns**: Round 4 typically finds 1-3 medium issues.
  If Round 3 found 0 high, skip Round 4.
- **False positives**: multisampling creates duplicates. The dedup step (after
  each round) is critical — don't count the same issue from 3 agents as 3 issues.
- **Routing**: ordinary code/diff review uses /deep-review. This skill's code mode
  is for an explicitly requested swarm security/bug review, not automatic expansion.

## Troubleshooting

- A review finds a fix but the user already asked for implementation: keep ownership,
  apply the scoped reversible correction and its causal check, then continue the
  original task. Do not turn an optional next round into a permission blocker.
- Review keeps generating unrelated improvements: bind each proposed round and
  finding to current acceptance or an evidenced material risk; omit optional polish.

## When to use this vs other review skills

| Scenario | Use |
|---|---|
| Quick architecture check | /plan-eng-review |
| CEO-level scope challenge | /plan-ceo-review |
| Design/UX review | /plan-design-review |
| Code diff review (pre-merge) | /review or /deep-review |
| **Thorough plan hardening before implementation** | **/plan-swarm-review** (plan mode) |
| **Plan with many interacting components** | **/plan-swarm-review** (plan mode) |
| **High-stakes plan (infra, security, payments)** | **/plan-swarm-review** (plan mode) |
| **Explicit swarm security audit of a module/codebase** | **/plan-swarm-review** (code mode) |
| **Explicit swarm pre-release vulnerability hunt** | **/plan-swarm-review** (code mode) |
| **Ordinary bug hunt or code review** | **/deep-review** |
