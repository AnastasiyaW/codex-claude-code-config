---
name: deep-review
version: 1.0.0
description: |
  Parallel competency-based code review. Launches independent Agent reviewers per competency
  (security, performance, architecture, database, concurrency, error-handling, frontend, testing),
  each with a focused checklist and isolated context. Synthesizes findings into unified report
  with FIX/DEFER/ACCEPT triage. Use when: "deep review", "thorough review", "parallel review",
  "review by competency", "full code review", or for large diffs (200+ lines) where /review
  may be too shallow. Complements /review (pre-landing) — this is for deep dives. Do NOT use just to
  orient in an unfamiliar codebase or get a structural symbol overview; use repo-map
  for that (this audits a concrete diff for defects, it is not a navigation map).
  Review is read-only unless the user explicitly asks to review and fix.
allowed-tools:
  - Bash
  - Read
  - Edit
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
  - TodoWrite
---

# Deep Review — Parallel Competency-Based Code Review

Inspired by Memento workflow engine's parallel review pattern.
Philosophy: one focused expert per domain > one generalist checking everything.

---

## Step 0: Determine scope

```bash
BASE=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@refs/remotes/origin/@@' || echo "main")
echo "BASE: $BASE"
BASE_REF=$(git rev-parse --verify --quiet "refs/remotes/origin/$BASE" 2>/dev/null || git rev-parse --verify --quiet "$BASE" 2>/dev/null || true)
if [ -z "$BASE_REF" ]; then
  echo "No locally available base ref for $BASE; cannot perform a read-only diff." >&2
  exit 2
fi
echo "BASE_REF: $BASE_REF"
echo "=== DIFF STATS ==="
git diff "$BASE_REF" --stat
echo "=== CHANGED FILES ==="
git diff "$BASE_REF" --name-only
echo "=== DIFF SIZE ==="
git diff "$BASE_REF" --shortstat
```

Store the BASE branch name, resolved local base ref, and list of changed files.
Report-only review does not run `git fetch`, `pull`, or another command that
updates Git state. If the accepted task explicitly requires a fresh remote base
and permits that preparation mutation, run `git fetch origin "$BASE" --quiet`
without suppressing failure before resolving `BASE_REF`; otherwise state that
the review used the locally available ref.

If there is no diff, stop: "Nothing to review — no changes against $BASE."

---

## Step 1: Scoping — select relevant competencies

Based on the changed files, select ONLY the competencies that are relevant. Do NOT run all 8 for a 3-file CSS change.

Default to a review-only task. Enter review-and-fix only when the user clearly
authorizes both review and implementation (for example, "review and fix"). In
either mode, the review phase remains read-only; review-and-fix continues with
the approved remediation in this same task after findings are triaged.

### Competency selection rules

| Competency | Trigger files/patterns |
|---|---|
| **security** | auth, middleware, routes handling user input, env files, CORS, JWT, crypto, passwords, tokens, API keys |
| **performance** | database queries, loops over collections, API endpoints, bundle config, image/asset handling, caching |
| **architecture** | new files/modules, cross-module imports, service boundaries, DI patterns, >5 files changed |
| **database** | migrations, schema changes, raw SQL, ORM queries, transactions, indexes |
| **concurrency** | queues, workers, locks, async/await patterns, shared state, cron jobs, webhooks |
| **error-handling** | try/catch blocks, error responses, validation, external API calls, file I/O |
| **frontend** | Vue/React components, CSS/Tailwind, composables/hooks, stores, routing, i18n |
| **testing** | test files changed OR >100 lines of logic changed without test changes |

Select every materially relevant competency and no others. Diff size is a
signal to inspect scope, not a reason to add unrelated reviewers. A single
competency is valid when the changed risk has one material dimension.

Output the selected competencies with a one-line justification each:
```
Selected competencies (4 of 8):
  ✓ security — auth middleware modified
  ✓ database — new migration + 3 query changes
  ✓ concurrency — BullMQ worker modified
  ✓ error-handling — 4 new try/catch blocks in API routes
  ✗ architecture — no new modules, existing patterns
  ✗ performance — no hot paths touched
  ✗ frontend — no UI changes
  ✗ testing — test files updated alongside logic
```

---

## Step 2: Get the diff content

```bash
git diff "$BASE_REF"
```

Read the full diff. You need it to construct focused prompts for each competency agent.

Also identify which files are relevant to each selected competency — each agent should receive ONLY the files relevant to its domain, not the entire diff.

---

## Step 3: Launch parallel competency reviews

For each selected competency, launch an Agent tool call **in parallel**. Each agent:
- Gets ONLY the files relevant to its competency
- Has a focused checklist (from the competency definitions below)
- Returns findings in structured format
- Works in isolated context (no bias from other competency reviews)

**CRITICAL**: Launch ALL agents in a SINGLE message (parallel tool calls). Do NOT launch them sequentially.

If a reviewer must run tests, give it an isolated writable worktree and a unique
writable scratch directory. Capture `git status --porcelain=v1`,
`git diff --exit-code`, and `git diff --cached --exit-code` before and after the
review. Do not place a test-running reviewer in an OS-level read-only sandbox:
pytest and similar tools legitimately create temporary files. If only a strict
read-only sandbox is available, provide immutable test receipts for inspection
and say that the reviewer did not execute the tests.

### Agent prompt template

For each competency, use this prompt structure (fill in {COMPETENCY}, {CHECKLIST}, {FILES}):

```
You are a {COMPETENCY} specialist reviewing code changes. Your ONLY job is {COMPETENCY} — ignore everything else.

## Review authority and writable scratch
Repository root: {REPO_ROOT}
Scratch directory: {REVIEW_SCRATCH}

You are a reviewer, not an implementer. Do not create, modify, delete, format,
or install anything in {REPO_ROOT}; do not alter Git or worktree state. If a
review command genuinely needs a file, write only under {REVIEW_SCRATCH}.
Return findings in the required response format; do not create a project report
or patch. If tests cannot run without writing elsewhere, inspect the supplied
immutable test receipts and label execution NOT_RUN.

## Changed files to review
{list each relevant file path}

Read each file listed above using the Read tool. Then apply this checklist:

## Checklist
{CHECKLIST from competency definitions below}

## Output format
For EACH finding, output exactly:

FINDING: {one-line description}
FILE: {path}:{line}
SEVERITY: CRITICAL | HIGH | MEDIUM | LOW
EVIDENCE: {quote the problematic code, max 3 lines}
FIX: {concrete fix suggestion, not vague advice}
CONFIDENCE: HIGH | MEDIUM | LOW

If you find NOTHING — output: "NO_FINDINGS — {COMPETENCY} review clean."

Do NOT pad with compliments. Do NOT report things that are fine. Only problems.

## Admission — screen each candidate BEFORE you publish it

A suspicion is a candidate, not a finding. Put each one through these five before it
reaches the report, and drop it silently if it fails any:

- **Authority** — does a real contract, spec, invariant or accepted requirement say
  this is wrong? "I would have written it differently" is not authority.
- **Reachability** — can the bad path actually be reached by a supported input or
  state? Show how. Unreachable code is at most a tidiness note.
- **Materiality** — if it happens, what breaks for a user or an operator? If the
  answer is "nothing observable", it is not a finding at this severity.
- **Evidence** — can you quote the lines that prove it, without inference? If your
  proof is "this pattern is usually a bug", you have a hypothesis.
- **Remedy cost** — is the fix smaller than the harm? A finding whose remedy is a
  rewrite needs the harm to justify a rewrite.

Report the count you dropped and why, in one line: "screened out 4: 2 unreachable,
1 no authority, 1 immaterial". That line is the evidence you screened at all.

The failure this prevents is specific and tempting. A candidate that generalises your
finding to a second case makes the report sound weightier, and nobody downstream will
check the second case. Verifying it and dropping it costs you one paragraph; leaving
it in costs the reader their trust in the other findings.
```

### Competency checklists

Use the checklist content from the files in `competencies/` directory. Read each relevant file before constructing the agent prompt.

If competency files don't exist yet, use the inline checklists below:

**security**:
- SQL/NoSQL injection (parameterized queries?)
- XSS (user input escaped in output?)
- Auth bypass (middleware on all protected routes?)
- CSRF (tokens validated?)
- Secrets in code (API keys, passwords, tokens hardcoded?)
- Trust boundary violations (LLM/external output used unsanitized?)
- Path traversal (user-controlled file paths?)
- Rate limiting on sensitive endpoints?
- CORS configuration (too permissive?)
- JWT validation (expiry, algorithm, issuer checked?)

**performance**:
- N+1 queries (loop with DB call inside?)
- Missing indexes on filtered/joined columns?
- Unbounded queries (no LIMIT on user-facing endpoints?)
- Memory leaks (event listeners not cleaned up? growing collections?)
- Bundle impact (new dependencies? tree-shaking?)
- Caching opportunities missed?
- Expensive operations in hot paths?
- Pagination on list endpoints?
- Image/asset optimization?

**architecture**:
- Separation of concerns (business logic in controllers?)
- Circular dependencies between modules?
- God objects/functions (>200 lines, >5 responsibilities?)
- Abstraction level consistency (mixing HTTP and business logic?)
- Interface contracts (types/schemas for cross-module communication?)
- DRY violations (copy-pasted logic that should be shared?)
- Layer violations (UI calling DB directly?)
- Configuration vs hardcoding?

**database**:
- Migration safety (reversible? data-preserving? locks?)
- Query performance (JOINs, subqueries, full table scans?)
- Transaction boundaries (operations that should be atomic?)
- Data integrity (constraints, foreign keys, NOT NULL where needed?)
- Index coverage for new queries?
- Connection management (pool exhaustion risk?)
- Schema evolution (backward compatible?)
- Default values for new columns?

**concurrency**:
- Race conditions (read-modify-write without lock?)
- Deadlock potential (multiple locks in inconsistent order?)
- Idempotency (can the operation be safely retried?)
- Queue handling (ack/nack, retry policy, DLQ?)
- Shared state access (multiple workers writing same resource?)
- Distributed locking (Redis/DB advisory locks where needed?)
- Timeout handling on external calls?
- Graceful shutdown (in-flight requests drained?)

**error-handling**:
- Swallowed errors (empty catch blocks?)
- Error propagation (errors from dependencies surfaced correctly?)
- User-facing error messages (informative but not leaking internals?)
- Partial failure handling (what if step 3 of 5 fails?)
- Retry logic (exponential backoff? max retries? circuit breaker?)
- Cleanup on failure (resources released? partial writes rolled back?)
- Validation at boundaries (API input, file uploads, webhook payloads?)
- Logging on error paths (enough context to debug? not too noisy?)

**frontend**:
- Reactivity correctness (Vue: ref vs reactive, computed vs watch?)
- Component responsibility (>300 lines = split candidate?)
- Accessibility (ARIA labels, keyboard nav, contrast?)
- Loading/error states handled?
- Memory leaks (subscriptions, intervals, event listeners cleaned up?)
- i18n (hardcoded strings?)
- Responsive design (mobile breakpoints?)
- XSS in template rendering (v-html with user data?)

**testing**:
- Logic changed without test update?
- Happy path only (no error/edge case tests?)
- Mocking too much (testing mocks instead of behavior?)
- Test isolation (tests depend on execution order?)
- Assertions quality (testing implementation details vs behavior?)
- Missing integration tests for cross-module changes?
- Flaky patterns (timing, network, random data?)
- Coverage gaps for critical paths (auth, payments, data integrity?)

---

## Step 4: Collect and synthesize

After ALL agents complete, collect their findings and synthesize:

### 4a: Deduplicate

Multiple competency reviewers may find the same issue. Group findings by file:line and merge duplicates. When merged, note which competencies flagged it (higher confidence when multiple domains agree).

### 4b: Triage each finding

For each unique finding, assign a triage:

| Triage | Criteria |
|---|---|
| **FIX** | CRITICAL or HIGH severity, HIGH confidence, clear fix available. Must be resolved before merge; review-and-fix may implement it in this task. |
| **DEFER** | MEDIUM/LOW severity or LOW confidence. Real issue but can be addressed later. Create backlog item. |
| **ACCEPT** | Intentional trade-off, or finding is incorrect after cross-checking context. Document why it's acceptable. |

### 4c: Output the synthesis report

```
══════════════════════════════════════════════════
  DEEP REVIEW: {branch} → {base}
  {N} findings across {M} competencies
══════════════════════════════════════════════════

COMPETENCIES REVIEWED: {list with ✓}
DIFF SIZE: {N insertions, M deletions, K files}

── FIX ({count}) ─────────────────────────────────
  1. [CRITICAL/security+concurrency] file:line
     Problem: {description}
     Evidence: {code quote}
     Fix: {concrete suggestion}

  2. [HIGH/database] file:line
     ...

── DEFER ({count}) ──────────────────────────────
  3. [MEDIUM/performance] file:line
     Problem: {description}
     Why defer: {rationale}

── ACCEPT ({count}) ─────────────────────────────
  4. [LOW/architecture] file:line
     Finding: {description}
     Why accept: {rationale}

══════════════════════════════════════════════════
  VERDICT: {PASS / PASS_WITH_CAVEATS / NEEDS_FIXES}
══════════════════════════════════════════════════
```

---

## Step 5: Continue only for explicit review-and-fix

For review-only requests, stop after the synthesis report. Do not edit source,
format files, alter Git state, install dependencies, or create a patch; report
which FIX findings must be resolved before merge.

For an explicit review-and-fix request, continue in this same task after the
read-only synthesis. Preserve the selected scope and verify each remediation
with the smallest causal check:

For each FIX finding:

1. If the fix is mechanical (add missing `await`, add index, add LIMIT, fix typo) — apply it directly. Output: `[FIXED] file:line — {what}`
2. If the fix requires judgment — present via AskUserQuestion with options:
   - A) Apply recommended fix
   - B) Fix differently (describe)
   - C) Move to DEFER
   - D) Accept as-is

After all FIX items are resolved, output final status:
```
DEEP REVIEW COMPLETE:
  {N} findings total
  {X} auto-fixed
  {Y} fixed with user input
  {Z} deferred
  {W} accepted
```

---

## Gotchas

- **Agent tool limitation**: subagents cannot launch sub-subagents. Each competency agent runs inline tools only (Read, Grep, Glob, Bash).
- **Context size**: each agent gets focused file list, not full diff. If a competency touches >20 files, prioritize the most critical ones and note "N additional files not reviewed."
- **False positives**: parallel agents don't share context, so they may flag things that are addressed in other files. The synthesis step (4a-4c) catches these through cross-referencing.
- **Cost**: launching 5 parallel agents costs ~5x a single-pass review. This is the trade-off for depth. For quick checks use `/review` instead.
- **Timing**: parallel agents complete at different speeds. Wait for ALL before synthesizing.
- **Read-only is a role, not a filesystem**: reviewers do not edit source. A reviewer asked to execute tests still needs isolated writable scratch and a writable runtime.

## Troubleshooting

- **`pytest` reports no usable temporary directory or `Access is denied` before collection**: the reviewer was launched with a contradictory execution contract. Relaunch it in an isolated writable worktree with `{REVIEW_SCRATCH}`, or have it inspect immutable test receipts and report `NOT_RUN`; never count the failed command as test evidence.
- **Reviewer may have changed the repository**: compare the before/after `git status --porcelain=v1`, `git diff --exit-code`, and `git diff --cached --exit-code` receipts. Any new tracked/staged change invalidates the review until reconciled.

## When to use /deep-review vs /review

| Scenario | Use |
|---|---|
| Pre-landing quick check | `/review` |
| Large diff (200+ lines) | `/deep-review` |
| Security-sensitive changes | `/deep-review` |
| Before major release | `/deep-review` |
| Small bugfix | `/review` |
| New feature with DB+auth+frontend | `/deep-review` |
| Refactoring within one module | `/review` |
