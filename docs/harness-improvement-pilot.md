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
  "candidate": {"component": "prompt", "diff_sha256": "sha256:...", "lesson": {"cue": "...", "lesson": "...", "evidence": "...", "confidence": "medium"}},
  "cases": [
    {"id": "known-case-1", "partition": "development", "runs": [true, true, false], "safety_passed": true, "tool_calls": 4, "elapsed_ms": 1200},
    {"id": "known-case-2", "partition": "development", "runs": [true, true, true], "safety_passed": true, "tool_calls": 3, "elapsed_ms": 900},
    {"id": "held-out-case-1", "partition": "held_out", "runs": [true, true, true], "safety_passed": true, "tool_calls": 3, "elapsed_ms": 950}
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

## One change, repeats, and the lesson ledger

Three rules follow [Harness²](https://github.com/google-research/harness2):
one change per candidate, judgement on repeated runs, and one recorded lesson
or none. The `candidate` block and `runs` lists are only read when the
candidate is compared; the baseline receipt needs neither.

1. **One change per candidate.** The candidate receipt names one
   `candidate.component` from `prompt`, `rule`, `skill`, `hook`, `script`,
   `memory`, `tool-guidance`, `subagent`, `plugin`, and the digest of the
   reviewed diff in `candidate.diff_sha256`. A missing component or digest is
   "not checked": the command exits 2 and writes nothing. A list naming more
   than one distinct component is `REJECT`.
2. **Repeats, not single lucky runs.** Each case carries `runs`, a list of at
   least three booleans. A case passes on a strict majority of its runs; a
   defect seen in one of k runs is noise. The older single `outcome_passed`
   boolean still reads as one run. If the claimed improvement rests on a case
   with fewer than three runs (a case whose majority outcome flipped, or every
   case for a numeric objective), the verdict is `CONFOUNDED`. It is treated as
   `REJECT` and writes no lesson.
3. **One lesson or NO_ENTRY.** `--report` also appends one JSON line to
   `evidence/harness-lessons.jsonl` (override with `--lessons`). If the
   candidate has a `lesson` object (`cue`, `lesson`, `evidence`, `confidence`),
   the line holds the date, verdict, component and that lesson. Otherwise, and
   for a `CONFOUNDED` verdict, the line is `{"date", "verdict", "entry": "NO_ENTRY"}`.
   The file is append-only: earlier lines are never rewritten.

Reading the verdict, as an edit table:

| Verdict | Edit outcome | Meaning |
|---|---|---|
| `ACCEPT` | helped | strict improvement, no regression |
| `REJECT`, safety, held-out or pass-rate reason | hurt | the change lost coverage it must keep |
| `REJECT`, "did not strictly improve" | no-effect | nothing measurable changed |
| `CONFOUNDED` | confounded | the gain rests on too few runs; rerun before judging |

Exit codes are unchanged: `0` ACCEPT, `1` REJECT or CONFOUNDED, `2` input error.

## Candidate: evidence-backed visual workflow

Assessed 2026-10-25 from [OpenVLHarness](https://github.com/uclanlp/OpenVLHarness).
Take the patterns, not the stack. Use them only when a task is visual (frames,
crops, masks, OCR, labelling). Upstream provides addressable task memory, a
`run_manifest.json`, redacted configs and `--resume` with config validation; the
schemas below are our adaptation, not upstream formats.

- **Typed evidence, not prose.** A perception tool returns an object with an
  addressable artifact, for example (our schema) `{"kind": "crop", "ref":
  "artifact://<task>/crop-3.png", "source_ref": "...", "bbox": [x, y, w, h],
  "value": ..., "provenance": {"tool": ..., "version": ...}}`. Frames, crops,
  masks and numbers in one task point at each other by `ref`.
- **An explicit capability set.** A disabled tool is absent from the model's
  schema. A failure or reduced mode comes back as `{"status": "degraded",
  "capability": ..., "reason": ...}` (our schema) and lands in the receipt.
  Upstream counts its degradation as a fallback to raw content; we go further:
  silently switching to another tool is not allowed.
- **A run manifest.** Record the effective config without secrets, service and
  model versions, the input digest, the tool-call trajectory and a resume key.
  Resume only when the digest and versions match.

Do not adopt: executing model-written Python on the host (the upstream
[security policy](https://github.com/uclanlp/OpenVLHarness/blob/main/SECURITY.md)
states that the "execution timeout is not a sandbox"), its GPU/router/search infrastructure, or its
benchmark numbers as proof of value for unrelated work. Prove value with this
pilot: baseline against the typed-evidence version on the same inputs, with a
held-out case. Start with local crop/zoom; add OCR, grounding or depth only
after a measured gap.
