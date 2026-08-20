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
  --finding F-001 --proof focused_test --result PASS --evidence evidence/test.txt
```

`findings.json` is evaluator input. The controller writes `cycle.json`
atomically and rejects mutation of a finding's frozen contract under the same
ID. Evidence paths must already exist under the named task directory. A failed
proof requires a new causal boundary/action and clears later proof epochs; after
three failures the finding escalates rather than looping forever.

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

### Legacy action migration

Only a pre-controller cycle where a failed proof overwrote its frozen
`next_action` needs `migrate-legacy-action`. It requires a receipt and an
explicit action that exactly matches `findings.json`; the heartbeat never calls
it. A mismatched evaluator action still fails loud and needs a new finding ID.
