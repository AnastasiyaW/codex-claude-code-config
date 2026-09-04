# Bug Discovery Playbook

Read this before ranking unknown bug candidates in a codebase.

## Establish a contract first

Treat a suspicious implementation as a candidate only when intended behavior can be defended from at least one source:

- existing tests or fixtures
- public types, schemas, or validation rules
- API docs, README examples, UI copy, or CLI help
- callers that rely on a specific result
- consistent behavior in adjacent branches or equivalent functions
- well-established platform behavior, when the project does not override it

Prefer two independent contract sources. If sources disagree, report the ambiguity instead of choosing the behavior that makes a test fail.

## High-yield correctness surfaces

### Boundaries and collections

- first, last, zero, empty, one-item, and maximum-size cases
- one-based versus zero-based indexes
- inclusive versus exclusive ranges
- duplicate handling, stable ordering, and accidental mutation
- pagination, batching, truncation, and partial pages

### State and lifecycle

- invalid transitions accepted or valid transitions rejected
- stale state retained across requests, users, tenants, or retries
- optimistic updates that are not rolled back
- cleanup skipped on early return or error

### Data and validation

- validation differs between create and update paths
- optional values become required downstream or required values are silently dropped
- serialized and in-memory shapes diverge
- falsey values such as `0`, `false`, or an empty string are mistaken for absence

### Time, numbers, and identity

- local time versus UTC, daylight-saving boundaries, and date-only parsing
- floating-point currency, rounding order, and integer overflow
- case sensitivity, Unicode normalization, and locale-sensitive comparison
- cache, map, or deduplication keys omit a field that changes identity

### Async and error paths

- missing `await`, premature return, double callback, or swallowed rejection
- race between read/check/write operations
- partial failure leaves inconsistent state
- retry duplicates a non-idempotent operation
- error mapping returns the wrong status or exposes a success shape

### Access boundaries

- object lookup omits user, role, organization, or tenant scope
- authorization happens after a side effect
- a protected UI action has no equivalent server-side check

Treat access-control candidates as high impact, but never exercise them against production or real user data.

## Candidate quality test

Keep a candidate only if all answers are yes:

1. Is there a specific reachable path?
2. Is there a valid triggering input or state?
3. Is expected behavior supported by evidence?
4. Can a focused test distinguish expected from actual behavior?
5. Would failure represent incorrect behavior rather than style, performance, or a new feature request?

## Avoid false positives

- Do not assume an exported function is publicly supported.
- Do not treat defensive behavior as broken merely because another design seems cleaner.
- Do not write an assertion that repeats a comment contradicted by all real callers.
- Do not mock away the branch or boundary being tested.
- Do not call unreachable code a reproduced product bug.
- Do not use typechecker, linter, or static analyzer warnings alone as proof.
- Do not interpret a test harness setup failure as a product failure.

## Rank consistently

Assign `high` confidence when contract, reachability, and deterministic trigger are all strong. Assign `medium` when one dimension has a stated uncertainty. Keep `low` candidates as notes only; do not spend the user's approved test scope on them while stronger candidates exist.
