---
name: verify-this
description: Prove a concrete behavior, performance, UI, CLI, API, or memory claim with fresh baseline-versus-treatment evidence and one explicit verdict. Use when asked to verify, prove, compare before and after, show evidence, or confirm that a fix works. Do not use for vague claims such as cleaner code, a full plan-based release verification, or a known bug that needs a red-to-green reproducer.
---

# Verify This

Verification is a falsifiable comparison, not a recap of what the agent believes
it changed. Turn one claim into a measurable check and preserve enough evidence
for another agent to repeat it.

## Workflow

1. Restate the claim as a condition, metric, and threshold. If the claim cannot
   be measured, ask for a measurable form or classify it as `INCONCLUSIVE`.
2. Select the smallest local surface that can disprove it.
3. Capture a baseline from the parent commit, merge base, current failing
   reproducer, or unchanged fixture.
4. Capture treatment with the same command, data, warmup, environment, and
   measurement method.
5. Compare raw artifacts: test output, timings, screenshots, HTTP responses,
   traces, profiles, or heap snapshots. Do not compare summaries alone.
6. Return exactly one verdict: `VERIFIED`, `NOT VERIFIED`, or `INCONCLUSIVE`.

## Evidence Contract

Record:

- claim and threshold;
- revision or baseline identity for both runs;
- exact commands and input fixture;
- environment differences and skipped checks;
- artifact paths or hashes, with sensitive payloads kept outside public Git;
- the verdict and one short explanation of confounders.

For durable project work, use the repository's existing proof artifact location,
for example `.agent/tasks/<task-id>/verification/<claim-slug>/`. Temporary or
sensitive evidence may stay outside the repository; retain only safe metadata and
hashes in the project. Never put credentials, private prompts, customer data, or
heap contents in a public checkout.

## Verdict Rules

- `VERIFIED`: baseline and treatment move in the predicted direction, meet the
  stated threshold, and have no material confound.
- `NOT VERIFIED`: behavior is unchanged, moves the wrong way, or misses the
  threshold.
- `INCONCLUSIVE`: there is no valid baseline, the signal is too noisy, the
  command failed, or the environments are not comparable.

Use this output shape:

```text
VERIFIED | NOT VERIFIED | INCONCLUSIVE
Claim: <falsifiable claim>
Evidence:
<artifact or metric>: baseline=<...>, treatment=<...>, delta=<...>, threshold=<...>
Reasoning:
<one tight paragraph naming evidence and confounders>
```

## Boundaries

- Use `proof-verify` when the work has frozen multi-criterion acceptance
  criteria and needs a fresh-context verifier.
- Use `bug-reproducer` when a concrete defect needs a minimal red-to-green test
  and separate approval gates.
- Use `testing-strategy` to choose test levels before running this comparison.
- A single green test is not enough for a performance, release, UI, or memory
  claim unless it is the stated evidence surface.

## Gotchas

- A different fixture, warm cache, compiler, or machine can invalidate a
  baseline comparison; report it instead of smoothing it away.
- A missing baseline is not a passing baseline. Use `INCONCLUSIVE`.
- A test can pass while user-visible behavior remains wrong; use the real CLI,
  browser, API, or artifact boundary when that is the claim.
- Do not turn a failed comparison green with retries, wider tolerances, or a
  changed workload unless the claim itself was explicitly re-scoped.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| No comparable baseline | Parent state or repro is unavailable | Report `INCONCLUSIVE`; capture a new baseline before changing the claim |
| Results vary between runs | Warmup, shared state, timing noise, or nondeterminism | Fix isolation and repeat with a fixed workload; record variance |
| Treatment passes but claim is still doubtful | Wrong evidence surface | Move to the real boundary or add one focused integration/UI/CLI check |
| Evidence contains sensitive data | Raw artifact is not suitable for Git | Keep it private and record only safe metadata or a hash |

## Source

Adapted from Cursor Team Kit's MIT-licensed `verify-this` workflow:
https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/verify-this
