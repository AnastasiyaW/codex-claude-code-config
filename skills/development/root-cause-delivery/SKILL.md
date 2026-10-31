---
name: root-cause-delivery
description: Use for a reported bug, regression, crash, failed workflow, or substantive code change that must reach a verified candidate rather than a local patch. Map the affected layer, freeze a bounded plan, require incident reproduction red-to-green or planned-change contract proof, force re-triage after two failed attempts, and close only with verified or explicitly blocked evidence. Do not use for a spelling-only documentation correction or an exploratory question with no implementation.
---

# Root-Cause Delivery

The goal is not a green-looking diff. The goal is a candidate that fixes the
observed contract and can advance toward release without reopening already
proved work.

Use one durable case per substantive incident or code change:

```text
.agent/delivery-cases/<case-id>/
  case.json
  evidence/
```

The installed `root-cause-delivery-guard.py` hook records a matching intent
from an explicit bug/regression or substantive implementation request. It keeps
source edits behind a valid `PLAN_FROZEN` case and will not allow a changed
source tree to close while the case is incomplete. Harness records are never
treated as source, so they stay writable before a case is frozen: delivery cases,
`CONTINUITY.json`, `.agent/user-tasks/` and transfer contracts
(`hooks/harness_records.py`). A bare background-task `<task-notification>`
records no intent.

## Workflow

1. Create the case before changing source:

   ```text
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py init <case-id> \
     --kind incident --summary "short observed failure"
   ```

   Use `--kind change` for a feature or non-bug delivery task. The CLI binds the
   only active prompt intent automatically. If parallel sessions have active
   intents in the same repository, pass `--intent-id <id>` shown by the prompt
   receipt; it refuses to guess which session owns the case.

2. Fill `case.json` with observed facts, not a story:

   - `observed.expected` and `observed.actual` for an incident;
   - layer map: entrypoint, owning module, direct dependents, state or contract,
     tests/probes, and release boundary;
   - one causal hypothesis, bounded `fix_steps`, and a focused verifier argv.

   Scope the *layer*, not the whole repository. The map asks which boundary owns
   the defect and which direct contracts can break; it is not permission for a
   speculative rewrite.

3. For an incident, capture the failing reproducer before source edits:

   ```text
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py capture <case-id> \
     --phase before -- <exact test command and arguments>
   ```

   The command must fail. The helper stores argv, exit status, bounded raw output,
   and a digest under the case. Do not replace it with a different convenient test
   after the fix.

4. Freeze the plan, then implement:

   ```text
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py freeze <case-id>
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py begin <case-id>
   ```

   Make only the planned causal change. A cosmetic cleanup is allowed only when
   it is necessary to make the owning contract correct and is named in the plan.

5. If an attempt does not fix the reproducer, record it:

   ```text
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py record-failed-attempt \
     <case-id> --hypothesis "what this attempt tested" --changed-path src/module.py
   ```

   After two failed attempts, stop editing the same area. Expand the owner map,
   record why the previous hypotheses failed, use a fresh evaluator when risk is
   high, then record re-triage:

   ```text
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py retriage <case-id> \
     --expanded-owner-path src/owner.py \
     --causal-hypothesis "a new, evidence-backed explanation"
   ```

   A causal sentence that a measurement shows to be false does not need failed
   attempts first. Write the measurement into a repository file with a labeled
   `Observed:` line and pass it as `--measured-correction <file>`; the old
   hypothesis, new hypothesis, file path, and digest are recorded in the case
   `history`. A duplicate case for the same cause closes as terminal
   `SUPERSEDED` with `supersede <case-id> --by <canonical-case-id> --reason "..."`.
   The canonical case must be in the same repository, must not itself be
   SUPERSEDED, and must share a `layer.owner_paths` entry; chains are refused.

6. For an incident, run the exact same reproducer after the fix. For a planned
   change, run the frozen `focused_argv` after implementation. In either case,
   use the exact argv written in `plan.focused_argv`:

   ```text
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py capture <case-id> \
     --phase after -- <the same test command and arguments>
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py verify <case-id>
   ```

   Before `verify`, a fresh reviewer who did not build the fix writes a receipt
   inside the repository and records it:

   ```markdown
   Case: <case-id>
   Verdict: PASS
   Baseline cause: <exactly plan.causal_hypothesis>
   Owner boundary: <one exact path from layer.owner_paths>
   Reproducer: <the exact JSON argv observed before and after, or planned for a change>
   After result: the same argv exits 0 and the changed boundary is exercised
   ```

   ```text
   python ~/.claude/claude-code-config/hooks/root-cause-delivery-guard.py record-independent-review \
     <case-id> --reviewer <fresh-session-id> --evidence .agent/delivery-cases/<case-id>/independent-review.md
   ```

   The helper hashes the receipt and rejects a self-named review, a baseline cause that
   differs from the frozen hypothesis, an unmapped owner boundary, or a reproducer that
   differs from the captured red argv (or frozen change argv). The fresh reviewer starts
   from the case contract and repository state, not the builder's explanation or evidence.
   For an incident it must check that the red case failed for the claimed reason, rather
   than merely observing a nonzero exit.

7. Select the rest of the evidence by boundary and risk using
   `testing-strategy`. Run focused checks while iterating; run the complete
   candidate matrix once at the commit/merge/release boundary. Use
   `proof-verify` for a fresh verifier, and its stage ledger only when the
   accepted result feeds a real release, migration, signer, VM, or external
   service stage.

## What Counts as Done

- `VERIFIED`: the incident red-to-green proof or planned-change focused proof is
  captured, the layer map and bounded plan are present, a fresh reviewer has checked
  the relevant boundary and argv, and the selected risk-based checks passed.
- `SEALED`: `VERIFIED` plus immutable candidate commit/tree and fresh verdict
  where a downstream stage must consume the result.
- `BLOCKED`: a real external prerequisite and its captured external evidence are
  recorded. It is not a synonym for "hard", "pre-existing", or "needs cleanup".

## Guardrails

- Do not infer a root cause from a plausible reading of one file. Separate
  observations, hypotheses, rejected hypotheses, and measured evidence.
- A red guard alone is insufficient: it can be red because setup, a wrong
  assertion, or an unrelated exception failed. A green suite written by the
  builder is useful evidence, but it is not independent certification of the
  defect class. Require the paired independent receipt above.
- Do not run the full suite after every edit. Focused reproduction first,
  then risk-based review, then one candidate matrix and any actually relevant
  specialized environment.
- Do not rewrite a file repeatedly when the same repro remains red. The second
  failed attempt is a signal to inspect the next owner boundary, not a reason to
  expand the diff.
- A passing unit test does not prove a release. A release blocker does not erase
  already sealed source or artifact proof.
- The local hook records session identity but cannot cryptographically authenticate a
  distinct reviewer. Treat an independent receipt as a workflow contract; use a real
  fresh agent, PR reviewer, or evaluator service where reviewer identity matters.
- A `BLOCKED` status is not success. It needs a receipt with `External prerequisite:`
  exactly matching the recorded blocker plus a measured `Observed:` condition. The hook
  can bind that receipt to the status but cannot determine whether the external condition
  is truthful without a real evaluator or service probe.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `freeze` refuses the case | Layer map, causal hypothesis, focused argv, or incident baseline is missing | Add observed evidence and a bounded plan; do not edit source first |
| Baseline passes | The incident is not reproduced or the test is wrong | Re-triage the report; do not manufacture a red-to-green claim |
| After proof uses different argv | The test no longer proves the original failure or planned contract | Restore the frozen argv or record a genuine external blocker |
| Two attempts failed | Local file edits are not reaching the causal owner | Add a new owner boundary and changed causal hypothesis, then re-freeze the plan; do not resume the same rewrite loop |
| Release stage is unavailable | Upstream source may already be proved | Keep that proof, record the external stage as `BLOCKED`, and use the `proof-verify` stage ledger for promotion |

## Sources

- [Anthropic: Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [PROBE: failure-anchored structured recovery](https://arxiv.org/abs/2605.08717)
- [Traceability study of automated program repair agents](https://arxiv.org/abs/2506.08311)
