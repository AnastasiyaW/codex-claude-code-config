# Reproduction Playbook

Read this when choosing the smallest credible way to reproduce a reported bug.

## Deterministic logic bug

- Prefer a unit test that imports the real function or module.
- Use the smallest input that distinguishes expected from actual behavior.
- Preserve ordering, duplicates, nulls, precision, and mutation semantics when relevant.
- Assert the intended contract instead of copying current output.

## API or service bug

- Prefer an integration test at the handler or service boundary.
- Seed only the records required for the failure.
- Preserve authentication, authorization, tenancy, headers, status codes, and transaction behavior.
- Mock external systems only when they are not part of the suspected cause.

## UI bug

- Reproduce the user-visible state with a component or browser test at the narrowest credible layer.
- Record viewport, route, data state, interaction order, browser/runtime, and expected visual or accessible outcome.
- Prefer semantic assertions over fragile pixel checks unless appearance itself is the defect.
- When a screenshot is supplied, treat it as evidence of appearance, not proof of the underlying cause.

## Data, migration, or query bug

- Use a disposable local or test database with the minimal schema and seed data.
- Preserve constraints, indexes, time zones, collations, soft deletes, and tenant boundaries.
- Never run reproduction migrations or destructive queries against production.

## Flaky or concurrency bug

- Control seeds, clocks, task ordering, retries, worker count, CPU/network delay, and shared state where possible.
- Run enough repetitions to estimate frequency before and after.
- Reduce the trigger while retaining the race or ordering condition.
- A single failure without a stable trigger is evidence, not a completed reproduction.

## Environment or build bug

- Record runtime, OS/architecture, dependency and lockfile versions, environment flags, and build mode.
- Distinguish a missing setup step from a product defect.
- Use an isolated environment when dependencies or caches may contaminate the result.

## Validate the failure reason

A credible reproducer must:

1. Reach the relevant production path.
2. Use valid input or a clearly supported edge case.
3. Fail on the intended assertion or observable outcome.
4. Avoid unrelated setup, syntax, import, or dependency failures.
5. Pass after the causal fix without weakening the assertion.

Do not label a reproducer minimal merely because it is short. It must retain every condition necessary for the real failure and remove conditions that do not affect it.
