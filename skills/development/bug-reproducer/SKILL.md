---
name: bug-reproducer
description: Find likely software bugs in a codebase, rank concrete bug candidates, and prove or reject them with focused regression tests before proposing a fix. Also turn bug reports, stack traces, screenshots, failing behavior, support tickets, and regressions into minimal reproducible cases with red-to-green evidence. Use when Codex needs to hunt for unknown bugs, audit code for correctness defects, test suspicious edge cases, reproduce a reported failure, isolate root cause, or verify that an approved fix works without regressions. Honor explicit user authority for the requested fix; use approval gates only for authority that the request did not already grant or when scope materially changes. Do NOT use for ordinary implementation where no bug investigation or reproduction is needed.
---

# Bug Reproducer

Turn a codebase or bug report into evidence. When no bug is supplied, discover concrete candidates from the code and its contracts, then try to prove the strongest candidates with focused tests. Never present a suspicion as a confirmed bug.

## Honor existing authority, then apply missing gates

Invocation alone to hunt for unknown bugs is inspection-only. A direct request to fix or implement a reported bug, or to `find and fix` bugs in a named repository, authorizes the normal reversible reproduction tests and causal production edits inside that stated task. Record that authority and proceed through both evidence stages without stopping for duplicate confirmation, even when the exact responsible file is learned during diagnosis. Do not ask the user to approve the same scope twice.

If the user asked only to inspect, audit, find, isolate, or reproduce, do not infer permission to change production code. Before a gate that has not been satisfied, do not create or edit project files, install dependencies, run formatters or migrations, modify configuration, generate reports, create worktrees, or execute commands likely to mutate project state. Read source, configuration, documentation, existing tests, user-supplied logs, and Git history. Run an existing targeted test only when it is clearly safe and does not require project changes.

### Gate 1 — test the candidate

When the current request has not already authorized reproduction files and commands, present and stop at:

```markdown
## Bug candidates

| # | Candidate | Contract evidence | Trigger | Location | Confidence |
|---|---|---|---|---|---|
| 1 | ... | ... | ... | file:line | high/medium |

## Proposed bug test

- Candidate(s) to test:
- Why each could be a real bug:
- Exact files to create or edit:
- Minimal fixture/input:
- Test or harness command:
- Signal that will confirm each bug:
- Main risk or uncertainty:

No project files have been modified. Do you want me to create and run these tests?
```

List only candidates backed by a reachable code path, a defensible expected behavior, and a specific triggering input or state. Approval covers only the displayed reproduction files and commands. Test one strong candidate by default; batch at most three only when their files and commands are all explicit.

### Gate 2 — fix a proven bug

When the current request has not already authorized a causal production repair, present and stop at:

```markdown
## Proposed fix

- Reproduction status: REPRODUCED
- Proven bug:
- Root cause:
- Exact production files to change:
- Proposed transformation:
- Behavior that must remain identical:
- Regression and broader test plan:
- Main risk:

The bug is proven by a failing test, but no production fix has been applied. Do you want me to apply this exact fix?
```

Continue when the current request already covers the causal repair or after explicit approval. If the file list, dependencies, public behavior, risk tier, or approach materially changes beyond that authority, request fresh approval. Never bundle unrelated cleanup or another fix into the approved patch.

## Choose the workflow

- `hunt-and-prove` — Default when no specific bug is supplied. Discover, rank, and test likely correctness bugs.
- `reproduce-only` — Stop after a minimal failing case is proven. Use when the user asks only to find, reproduce, isolate, or write regression tests.
- `prove-fix` — Use for a reported bug or after a discovered candidate is proven and the user wants it fixed. Apply only gates not already satisfied by the current request, then prove red to green.
- `flaky` — Reproduce timing, ordering, seed, isolation, or concurrency-dependent failures across repeated controlled runs. Do not label one intermittent failure as reproduced.

## Run hunt-and-prove

### 1. Map the project read-only

- Identify runtime, entry points, public interfaces, data boundaries, test framework, existing commands, and high-change or high-risk modules.
- Derive intended behavior from tests, types, schemas, documentation, callers, UI copy, API contracts, and invariants. Prefer explicit contracts over personal style preferences.
- Inspect recent changes only when repository history is available; do not assume old code is correct.
- Read `references/bug-discovery-playbook.md` before ranking candidates.

### 2. Generate concrete candidates

- Trace user-controlled or boundary inputs through real reachable paths.
- Look for falsifiable defects: off-by-one boundaries, inverted conditions, missing empty/null handling, unsafe state transitions, ordering or deduplication errors, stale cache keys, permission gaps, precision/time-zone mistakes, async races, inconsistent validation, and error paths that violate the surrounding contract.
- For every candidate, identify the exact path, triggering input/state, expected result, likely actual result, and evidence for the expectation.
- Reject vague possibilities such as “this could be null” unless the codebase permits null and the path mishandles it.
- Do not call security posture, performance, formatting, maintainability, or missing features a bug unless they violate a concrete product contract.

### 3. Rank before testing

Rank candidates using:

1. Contract strength — Is expected behavior explicit in tests, types, docs, schemas, callers, or consistent nearby behavior?
2. Reachability — Can a real caller or valid input reach the path?
3. Reproducibility — Can a small deterministic test distinguish correct from incorrect behavior?
4. Impact — Does it affect outputs, data, permissions, crashes, or a user-visible workflow?

Show no more than five candidates and label confidence `high`, `medium`, or `low`. Do not propose testing low-confidence candidates while a stronger one exists. If no candidate survives this filter, return `NO_BUG_PROVEN` and identify the next useful evidence instead of inventing a bug.

### 4. Resolve Gate 1 authority

- If the request already authorized reproduction work, record the matching task scope and continue.
- Otherwise show the ranked shortlist and exact test plan for the strongest one to three candidates.
- Name every file and command that approval would cover.
- State that no project files have been modified, then stop and wait.

### 5. Test approved candidates

- Create only the approved test or harness.
- Use deterministic inputs and the smallest fixture that reaches the real production path.
- Assert the intended contract, not the current implementation.
- Capture the narrow command with `scripts/capture_command.py` when appropriate:

```bash
python3 scripts/capture_command.py --label reproduced --output reproduced.json -- npm test -- path/to/regression.test.ts
```

- Confirm that a failure matches the predicted behavior and cause. Syntax errors, missing dependencies, invalid fixtures, unrelated failures, and assertions built on an unsupported assumption reject or invalidate the candidate.
- Return `REPRODUCED`, `NOT_REPRODUCED`, or `INCONCLUSIVE` for each tested candidate. Delete or clearly separate rejected speculative tests unless the user asks to retain them.
- Stop after evidence when the user requested discovery or reproduction only. Do not slide into production changes.

### 6. Isolate and resolve Gate 2 authority

- Trace a reproduced failure to the smallest responsible condition and distinguish root cause from the line where it surfaces.
- If the current request already authorized the causal fix, record how the patch remains inside it and continue.
- Otherwise show Gate 2 with exact production files, transformation, preserved behavior, checks, and risk, then stop and wait for separate approval.

### 7. Apply only the approved fix

- Preserve the regression test unless the user explicitly requests a temporary harness.
- Change only the approved production files and necessary test expectations.
- Prefer the smallest causal fix over symptom suppression.
- Do not weaken assertions, catch and ignore errors, add arbitrary retries, disable tests, or broaden tolerances merely to turn the test green.

### 8. Prove red to green

- Run the exact same targeted command used for failing evidence.
- Run the broadest relevant suite, typecheck, lint, or build.
- Capture and classify the fixed run:

```bash
python3 scripts/capture_command.py --label fixed --output fixed.json -- npm test -- path/to/regression.test.ts
python3 scripts/compare_evidence.py reproduced.json fixed.json result.json --reproduction confirmed --full-suite passed
```

- Classify a passing targeted test with a failing relevant suite as `FIX_REGRESSION`.
- Classify a passing targeted test without broader evidence as `FIX_UNVERIFIED`, unless the project genuinely has no broader checks and that limitation is explicit.

## Handle an existing bug report

When the user supplies a symptom, error, screenshot, stack trace, or failing behavior:

1. Restate expected behavior, actual behavior, trigger, environment, frequency, and last-known-good version.
2. Separate observed facts from assumptions and remove secrets or personal data.
3. Map the report to likely paths and existing test conventions.
4. Skip broad discovery; preserve reproduction integrity and red-to-green proof, but do not repeat Gate 1 or Gate 2 when the reported-bug fix request already satisfies them.
5. Read `references/reproduction-playbook.md` when selecting the smallest credible layer.

## Use evidence labels precisely

- `REPRODUCED` — A focused case fails deterministically for the predicted or reported reason.
- `NOT_REPRODUCED` — The approved case does not produce the predicted failure.
- `NO_BUG_PROVEN` — Read-only discovery or approved candidate tests did not prove a correctness defect.
- `INCONCLUSIVE` — Environment, nondeterminism, missing access, or ambiguous signals prevent a conclusion.
- `STILL_FAILING` — The same reproducer continues to fail after an attempted fix.
- `FIX_UNVERIFIED` — The reproducer passes, but broader correctness evidence is missing.
- `FIX_REGRESSION` — The reproducer passes or changes, but relevant correctness checks fail.
- `FIX_PROVEN` — The same reproducer goes red to green and relevant broader checks pass.

Never claim a bug from code inspection alone. Never claim a fix without red-to-green evidence.

## Create the native report

After a completed approved workflow, create:

- `outputs/bug-reproducer-evidence.json` — captured test evidence and classification.
- `outputs/bug-reproducer-report.md` — native report that opens directly in Codex and renders on GitHub.

Prepare context JSON following `references/report-schema.md`, including discovery scope and ranked candidates when using `hunt-and-prove`, then run:

```bash
python3 scripts/generate_report.py result.json context.json outputs/bug-reproducer-report.md
```

Include discovery evidence, tested candidates, minimal reproduction, root cause, approvals and scope, changed files, red/green commands, broader checks, limitations, and residual risks. Link the Markdown report in the final response.

## Hand off

Lead with the strongest evidence label, then report:

1. Scope inspected and candidates considered
2. Candidate tests and outcomes
3. What reproduced and why the failure is credible
4. Root cause, if proven
5. Approved fix and red-to-green evidence, if requested
6. Broader checks, limitations, and residual risk
7. Link to `outputs/bug-reproducer-report.md`

If no bug is proven, preserve the project and say so plainly. A clean hunt is evidence about the inspected scope, not proof that the entire codebase has no bugs.

## Local operating rules

- On Windows, prefer an explicit verified Python executable in capture commands
  when the `python` launcher is slow or resolves to a store shim. Record the
  runtime in the evidence JSON.
- Treat `--reproduction confirmed` and `--full-suite passed` as operator input,
  not independent proof. The agent or a fresh verifier must inspect the captured
  command, exit codes, output, and broader-suite evidence before accepting the
  status.
- Do not use the upstream installer when the destination may already exist: it
  force-removes the destination. Install only into an absent or separately
  backed-up directory, then verify the resulting file list.

## Gotchas

- A passing focused test before a fix means `NOT_REPRODUCED`, even if the code
  looks suspicious.
- A syntax error, missing dependency, invalid fixture, or unrelated failing
  suite invalidates the reproduction; it is not a product bug.
- A clean hunt covers only the inspected scope. It never proves that the whole
  repository is bug-free.
- `compare_evidence.py` classifies recorded evidence; it does not prove causal
  root cause or independently run the broader suite.

## Troubleshooting

- **capture command hangs on Windows**: replace the launcher with the explicit
  verified Python executable, reduce the timeout, and rerun the same command.
- **FIX_UNVERIFIED**: run the broadest relevant suite and capture its result;
  do not upgrade the label by hand.
- **INCONCLUSIVE**: check that before and after commands are byte-for-byte the
  same and that the failure signal matches the predicted assertion.
