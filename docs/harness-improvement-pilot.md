# Bounded harness-improvement pilot

This is a small, deterministic adoption path inspired by
[Harness²](https://github.com/google-research/harness2): improve an agent's
environment while keeping model weights fixed. It is **not** a Harness² fork,
an agent runner, or permission for a model to rewrite active configuration.

Use it to compare one baseline and one candidate change to a prompt, skill,
script, or configuration. The command reads two frozen receipts and writes one
report. It never executes an agent, opens a network connection, edits either
input, installs a skill, changes hooks, or deletes code.

This keeps the useful part of the research method — an evidence-backed
comparison — while preserving the proof and review boundaries required by this
configuration. It also follows the small, evidence-led cleanup units described
by [OpenAI's maintenance guide](https://developers.openai.com/blog/maintaining-software-with-the-gpt-6-family),
not autonomous bulk changes.

## When to use it

Use a pilot only when all of these are true:

1. The task set is frozen and its exact input digest is known.
2. The candidate changes one bounded, non-safety component.
3. The evaluator can create mechanical per-case receipts.
4. At least one case is held out from the change proposal.

Do not use it to tune subjective output, to decide safety policy, or to make a
live installation. Those boundaries need the existing task-specific proof loop
and independent review.

## Receipt contract

Both JSON files use `harness-improvement-pilot/v1`, the same `suite.id`, the
same `suite.input_digest`, the same objective, and exactly the same case IDs
and partitions. A suite has at least three cases and contains both
`development` and `held_out` cases.

```json
{
  "schema": "harness-improvement-pilot/v1",
  "suite": {"id": "my-task-set", "input_digest": "sha256:..."},
  "objective": {"name": "outcome_pass_rate", "direction": "higher"},
  "cases": [
    {"id": "known-case-1", "partition": "development", "outcome_passed": true, "safety_passed": true, "tool_calls": 4, "elapsed_ms": 1200},
    {"id": "known-case-2", "partition": "development", "outcome_passed": true, "safety_passed": true, "tool_calls": 3, "elapsed_ms": 900},
    {"id": "held-out-case-1", "partition": "held_out", "outcome_passed": true, "safety_passed": true, "tool_calls": 3, "elapsed_ms": 950}
  ]
}
```

Supported objectives are `outcome_pass_rate` / `higher`, `mean_tool_calls` /
`lower`, and `mean_elapsed_ms` / `lower`.

## Run and interpret

```bash
python scripts/harness_improvement_pilot.py \
  --baseline evidence/baseline.json \
  --candidate evidence/candidate.json \
  --report evidence/comparison.json
```

`ACCEPT` requires a strict improvement of the chosen metric, no lower outcome
pass rate, every candidate safety assertion passing, and every candidate
held-out case passing. Mismatched suite digests, case IDs, partitions, or
objectives are input errors and fail closed. `REJECT` is a normal experimental
result: keep the prior configuration and record why the candidate was not
adopted.

An accepted report is evidence for review, not deployment. Before changing an
active skill or configuration, use the existing delivery/proof workflow,
independent reviewer, and installation/parity checks appropriate to that
specific boundary.
