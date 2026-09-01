# Task-cycle controller

`hooks/task-cycle-controller.py` turns a checked evaluator finding into a
durable work order. It owns only deterministic state transitions; a worker owns
code changes and must store real evidence before recording a transition.

## Contract

An `INTERNAL_FIXABLE` finding must name its accepted requirement, exact causal
boundary, next action, and this fixed proof order:

1. focused test;
2. runtime proof;
3. independent review with fresh context.

An `EXTERNAL_REQUIRED` finding must name the blocker, the last evidence, and
the next recheck time. `next` returns `RECHECK_EXTERNAL` as soon as that time
is due; a scheduled task therefore has work to do instead of waiting on stale
prose.

## Invocation

```text
python hooks/task-cycle-controller.py reconcile --task-dir .agent/tasks/<id>
python hooks/task-cycle-controller.py next --task-dir .agent/tasks/<id> --json
python hooks/task-cycle-controller.py record-proof --task-dir .agent/tasks/<id> \
  --finding F-001 --proof focused_test --result PASS \
  --evidence evidence/focused-test.receipt.json
```

`findings.json` is evaluator input. The controller writes `cycle.json`
atomically and rejects mutation of a finding's frozen contract under the same
ID. `--evidence` is a typed `agent-task-proof-receipt/v1` JSON receipt, not raw
stdout or a prose claim. It binds `finding_id`, proof, unique `attempt_id`, UTC
`recorded_at`, result, producer identity, a separate raw evidence path, and that
artifact's SHA-256. Command proofs name their argv. Independent-review receipts
instead name the reviewer and require `fresh_context: true` plus a verdict equal
to the recorded result. The controller re-hashes both receipt and raw evidence
whenever it validates the cycle.

Every internal order carries durable `max_attempts`, `max_tool_calls`, and
`max_wall_time_seconds` budgets plus a monotonic receipt history. Reusing an
attempt ID or receipt digest is rejected. A failed proof requires a new causal
boundary/action and clears later proof epochs; exhausted attempts, proof calls,
or wall time produce explicit `BUDGET_EXHAUSTED` with `completed: false`, never
`ACCEPTED` or `BLOCKED_EXTERNAL`.

Cycles accepted before typed receipts were introduced remain readable through an
explicit terminal-only `legacy_terminal_proofs` marker. Their evidence paths are
still required to exist, but they cannot accept another proof or return to active
work under the legacy shape. Every active or newly accepted order uses typed receipts.

Minimal command receipt shape:

```json
{
  "schema": "agent-task-proof-receipt/v1",
  "finding_id": "F-001",
  "proof": "focused_test",
  "attempt_id": "F-001-focused-001",
  "recorded_at": "2026-09-01T10:00:00Z",
  "evidence_path": "evidence/focused-test.raw.txt",
  "evidence_sha256": "<lowercase sha256>",
  "result": "PASS",
  "producer": {
    "type": "command",
    "identity": "pytest",
    "command": ["python", "-m", "pytest", "-q", "tests/test_focused.py"]
  }
}
```

## Heartbeat rule

Each wakeup runs `reconcile` then `next`. For `WORK`, it does exactly the
returned proof instruction and records its fresh artifact. For
`RECHECK_EXTERNAL`, it performs and records the named external check. For
`WAIT_EXTERNAL`, it leaves the task untouched until the controller's timestamp.
No heartbeat may substitute a static prose todo list for this result.

For a scheduled root containing several explicit task directories, use the
dispatcher rather than reimplementing that loop in an agent prompt:

```text
python scripts/task_cycle_heartbeat.py --tasks-root .agent/tasks --json
```

It considers only immediate subdirectories with `findings.json`, persists
`.agent/tasks/task-cycle-heartbeat.json`, and returns at most one actionable
next item (`WORK` or `RECHECK_EXTERNAL`). It never creates findings from chat,
executes a proof, or records a pass: those require the named work and evidence.

### Plan/source digest drift

A report that a plan pins one SHA-256 while the reviewed local source has
another is not an external blocker. Before a launch, write a real quiescence
receipt (no process and no output), then turn the observation into the next
internal work order rather than ending with prose:

```text
python hooks/task-cycle-controller.py register-plan-drift \
  --task-dir .agent/tasks/<id> --finding PLAN-DRIFT-001 \
  --plan <canonical-plan> --source <current-script> \
  --expected-sha256 <digest-recorded-in-plan> --output-root <expected-output-root> \
  --quiescence-evidence evidence/preflight-quiescent.json --json
```

The command proves that the plan actually pins the old digest, records the
observed digest, appends an `INTERNAL_FIXABLE` finding, reconciles it, and
returns `WORK`. With no output root it starts the successor
plan/preflight/review cycle. With an existing root it starts a separate
read-only migration assessment instead: it never rewrites the plan or calls
the mismatch external by default.

### Reconciliation gap

Do not report any verified desired/actual gap as a status. Store a structured
observation below the task first. It names the desired state and every item.
Each item must be `SATISFIED` with an existing local receipt,
`INTERNAL_FIXABLE`, or
`EXTERNAL_REQUIRED` with a named recheck. Then register the whole gap:

```text
python hooks/task-cycle-controller.py register-reconciliation-gap \
  --task-dir .agent/tasks/<id> --batch <immutable-observation-id> \
  --observation evidence/reconciliation-observation.json \
  --evidence evidence/reconciliation-probe.json --json
```

The controller writes one frozen work order for every unsatisfied item and
returns `WORK` for the first internal action. It does not perform a domain
side effect or give new authority. A fully receipted observation returns
`RECONCILIATION_SATISFIED`; a status paragraph is not a completion state. The
active Stop guard also rejects a structured observation until this registration
receipt binds its current SHA and every required finding, and then continues to
reject it until every bound internal order is `ACCEPTED` or every external order
has current `BLOCKED_EXTERNAL` recheck evidence.

### Legacy action migration

Only a pre-controller cycle where a failed proof overwrote its frozen
`next_action` needs `migrate-legacy-action`. It requires a receipt and an
explicit action that exactly matches `findings.json`; the heartbeat never calls
it. A mismatched evaluator action still fails loud and needs a new finding ID.
