# A finding is a work order

An audit that ends with “what is required now” but leaves no executable next
state is only a better-written wait. The failure is not solved by adding a
longer scheduled prompt: the prompt is a snapshot, while the finding is a
state transition.

## The small durable loop

Store an evaluator's accepted finding in a task-local `findings.json` with:

- one accepted requirement;
- one causal source or runtime boundary;
- one concrete next action;
- the exact proof sequence `focused_test -> runtime_proof -> independent_review`
  for internal work; and
- a named blocker plus last/next live-check timestamps **and a receipt path**
  for external work.

`scripts/task_cycle_controller.py reconcile` creates an idempotent work order
in `cycle.json`. A scheduled agent always runs `next` before it decides what
to do. Its result is one of:

| Result | Scheduler behaviour |
|---|---|
| `WORK` | Execute the returned bounded action, store real evidence, then record the proof. |
| `RECHECK_EXTERNAL` | Recheck the named outside dependency now; use `record-external-check` with its receipt and next check. |
| `WAIT_EXTERNAL` | No notification only when every blocker has a future recheck. |
| `ESCALATED` | Three failed proof attempts reached a new causal boundary; report it instead of retrying forever. |
| `ACCEPTED` | Every work order has its required evidence and fresh review. |

The controller never executes a command or infers a passing test. It requires
an evidence file under the task directory and a named fresh-context reviewer
for `independent_review`. A failed proof must include the next action and the
new causal boundary; after three such failures it escalates rather than
silently looping.

## Why structured findings

Chat prose is not an API. Automatically extracting a deployment, migration, or
VM action from an arbitrary sentence creates a dangerous guessing layer. The
evaluator or coordinator writes the small structured finding once; from that
point on the controller, not the model's memory, owns deduplication, queue
selection, retry limits, and the distinction between internal work and a real
external block.

## Heartbeat contract

The recurring prompt must be generic and stable:

1. Reconcile `findings.json` into `cycle.json`.
2. Read `next --json`; do only its returned action.
3. For an internal fix: implement, run the focused test, capture the required
   real runtime proof (a process/URL trace where relevant), then obtain an
   independent fresh review.
4. Record each result with its evidence path. A failure returns to `WORK` with
   a causal next action; it never becomes a prose HOLD.
5. Return a quiet result only on `WAIT_EXTERNAL` with future recheck times or
   on `ACCEPTED`.

This makes the schedule self-correcting: the queue changes the action at the
next wake, without rewriting a static “CURRENT FOCUS” paragraph.
