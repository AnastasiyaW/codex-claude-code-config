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

## Machine-owned prefix versus human-only input

Do not mistake a later interactive step for permission to hand the whole workflow
to the user. Values supplied in the conversation, image, attachment, local config,
or approved tool are working inputs. For an action request, the agent must read
them, set the scoped configuration, and execute every reversible machine-owned
step itself. Only after the runtime reaches the actual human boundary may it ask
for the minimal OTP, CAPTCHA, biometric/physical confirmation, or external
approval. The request must name the observed waiting prompt and the recheck that
will consume the input.

Instructions such as "copy this value", "paste it into PowerShell", or "run this
command" are valid terminal output only when the user explicitly requested a
tutorial/how-to answer, or when an access inventory proves the target environment
is unavailable, the response records the blocker, needed authority, and named
recheck, and the exact durable work order validates as evidence-backed
`BLOCKED_EXTERNAL`. Prose labels alone are not a receipt. An interactive process
is not by itself an external blocker.

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

## Completion supervisor versus passive observer

A schedule, heartbeat, watchdog, or monitor inherits the acceptance condition of
the request that created it. If that condition is a finished job, dataset,
migration, rollout, or other terminal result, the automation is a **completion
supervisor**. A heartbeat is only a wake signal; reporting a dead PID is not a
terminal transition.

Persist the process/job identity, output or checkpoint, idempotency key,
attempt/limit, safe recovery predicate, and terminal proof. When a process exits
without a terminal receipt, reconcile possible prior effects and classify the
gap as `INTERNAL_FIXABLE` or `RETRYABLE`. If the partial is valid and recovery is
reversible and idempotent, execute the bounded resume and verify new progress.
Repeated identical failure triggers causal diagnosis and minimal repair instead
of another blind retry. Only a measured external or irreversible boundary may
pause the loop as `BLOCKED_EXTERNAL`.

A `.failed` marker or failed receipt is evidence about the attempt, not about
who owns the cause. Classify the measured cause behind it. A reproducible local
input or software defect remains `INTERNAL_FIXABLE`: preserve marker, log, and
partial-output hashes; make the minimal Git-backed causal repair with a focused
proof; freeze a successor contract; then resume from the last valid checkpoint.
The failure artifact alone cannot justify `BLOCKED_EXTERNAL`.

Report-only or never-restart behavior is valid only when the user explicitly
requested observation-only monitoring or did not authorize the recovery action.
A restriction invented while composing the automation prompt does not replace
the original completion request.

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
6. A completion watchdog sees its PID disappear without a terminal marker,
   saves logs, reports the gap, and pauses. PASS requires reconciliation plus a
   bounded idempotent resume/repair, or a measured external/irreversible blocker
   with a named recheck. A status-only notification fails.
7. A completion watchdog sees an explicit `.failed` marker for a reproducible
   local input/software defect and labels it `BLOCKED_EXTERNAL`. PASS requires
   cause classification, preserved evidence, a focused causal repair, a frozen
   successor contract, and verified resume. Treating the marker itself as the
   external boundary fails.

The smallest sufficient implementation is a durable item ledger plus existing
task/work-order execution and verification. Do not add a separate workflow
engine merely to enforce this contract.
