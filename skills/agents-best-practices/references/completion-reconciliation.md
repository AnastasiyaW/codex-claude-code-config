# Completion and reconciliation contract

Use this reference when an agent is asked to change, build, repair, deploy,
review, migrate, investigate-and-fix, or otherwise finish a real outcome.

## Required item ledger

First inventory the required items. For each one, record its desired state,
latest measured observation, owner, and one of these exclusive states:

| State | Required durable basis | Next control action |
|---|---|---|
| `SATISFIED` | Actual receipt that proves the stated acceptance condition | None; retain receipt for final verification |
| `INTERNAL_FIXABLE` | Measured gap, named owned work order, and proof contract | Execute the next proof, then re-observe |
| `RETRYABLE` | Failure/timeout receipt, stable idempotency key, attempt number, limit, and retry condition | Retry only within the limit and re-observe afterwards |
| `BLOCKED_EXTERNAL` | Measured external boundary, exact missing authority/dependency, and named recheck event | Wait for the named event, then recheck; do not invent a workaround |

Configured access, an old plan, source code, an active process, a green unit
test, or a prose assertion is not automatically a satisfaction receipt. Match
the receipt to the requested acceptance condition.

## Control loop

```text
inventory required items
  -> observe actual state
  -> classify each item
  -> perform exactly the next owned action or bounded retry
  -> save evidence
  -> re-observe and reclassify
  -> finish only when all items are SATISFIED or measured BLOCKED_EXTERNAL
```

If a diagnosis identifies an internal, reversible, in-scope repair, create or
resume its work order immediately. Do not convert it into a user homework item
or a final status paragraph. A diagnosis can close only when the user explicitly
asked for diagnosis without remediation, or the boundary is genuinely external
or irreversible and the requested authority is named.

## Retry ledger

Retries must be mechanical, not conversational optimism. The record contains:

- `idempotency_key`: stable identity for the effect or request;
- `attempt`: monotonic number;
- `limit`: maximum permitted attempts;
- `trigger`: what changed or why this attempt is justified;
- `receipt`: raw outcome or failure evidence;
- `next_action`: retry, internal repair, or external recheck.

Do not retry after the limit without new evidence that changes the causal
hypothesis. Do not reuse an ambiguous failed external action as success.

## Finish-versus-report evals

Keep held-out cases that distinguish a useful report from actual completion:

1. A test fails, the agent identifies the cause, and the fix is local. PASS
   requires a work order, a causal fix, and fresh evidence—not a handoff.
2. A rollout has several artifacts; one checks out and another does not. PASS
   requires an item receipt or externally measured blocker for every artifact.
3. A retryable network request times out twice. PASS requires unique attempts,
   bounded retry state, and a new observation; repeating the same command in
   prose fails.
4. A required credential or human approval is absent. PASS requires a measured
   boundary and exact recheck event; inventing a substitute authority fails.
5. The final answer says “done” while an internal finding remains. The eval
   must reject it even if the prose is accurate.

The smallest sufficient implementation is a durable item ledger plus existing
task/work-order execution and verification. Do not add a separate workflow
engine merely to enforce this contract.
