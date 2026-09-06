---
name: distill-feedback
description: Turn captured user-correction signals into durable rules (learn-from-corrections loop). Use when - /distill-feedback, "process feedback queue", "what corrections did I give you", "encode lessons from my corrections", session-feedback-capture queued sessions, "обнови правила по моим поправкам", "разбери очередь обратной связи". Reads ~/.claude/feedback/queue.jsonl, LLM-semantically detects durable corrections, proposes atomic rules, applies human-gated via delta-merge. Do NOT use to act on a single in-session correction (just apply the fix directly) or to hand-edit settings.json behaviors; this only mines the queued feedback backlog into durable rules.
---

# distill-feedback — close the learn-from-corrections loop

The Stop hook `session-feedback-capture.py` queues finished sessions into
`~/.claude/feedback/queue.jsonl`. This skill processes that queue: it finds the user turns
that were **durable corrections** of the agent's work and turns them into rules — so the same
correction never has to be given twice.

**Why semantic review:** standing preferences depend on context, not a trigger-word count.
The formerly cited private `effectiveness-test/RESULTS.md` was absent when checked on
2026-09-06; its F1 claims are withdrawn from this skill until the dataset, labels, model,
held-out split and raw predictions can be inspected. The rubric below is a review method,
not a demonstrated accuracy guarantee. Do not substitute another paper's scores for our own.

**Research and authority:** [ACE](https://arxiv.org/abs/2510.04618) studies evolving context;
[TRACE](https://arxiv.org/abs/2606.13174) studies compiling corrections into runtime checks.
Neither proves this local extractor's accuracy. The approval boundary comes from our
applicable user instructions and `autonomy-risk-tiers.md`, not an inferred paper mandate.
New standing rules are proposals; an already authorized correction to an existing rule
can be implemented within that exact authority. Codex memory changes also require the
separate explicit user request and supported memory-update channel.

## Procedure

### 1. Extract the queue (deterministic)
```bash
python ~/.claude/skills/distill-feedback/scripts/extract_feedback_queue.py --limit 8
```
Returns JSON: `{pending, sessions:[{session_id, cwd, ts, user_turns:[...]}]}`. `--limit` bounds
the LLM pass (billing: distillation is opt-in, not every-session). If `pending` is 0, stop — nothing
to do.

### 2. Detect durable corrections (LLM-semantic, prefer a fresh sub-agent)
For independence (Generator-Evaluator), spawn a sub-agent with the **rubric** below and the
extracted `user_turns`. Ask it to return, per genuine correction: `{quote, durable_rule,
applicability_condition, confidence, session_id}`. Pass only the turns — not your own reasoning.

**RUBRIC — a user turn is a DURABLE CORRECTION** if the user pushes back on / redirects the agent's
behavior in a way that implies a STANDING preference or a mistake to avoid in future:
- explicit pushback / redirection ("no, do X instead", "wrong file again")
- reminder of a prior agreement ("we agreed you'd ask first", "мы же договаривались сначала бэкап")
- standing-preference marker ("from now on / always / never / by default / в следующий раз / впредь")
- frustration at a REPEATED mistake ("опять", "again", "you keep")
- polite redirection phrased as a question ("could you not overwrite latest.pth each time?")
- revert with a reason ("верни как было, твоя версия хуже")
- **praise THEN correction — judge the whole turn** ("great it runs, but always pin versions" = YES)

**NOT a durable correction:** new feature/task request · diagnostic question ("why did the build
fail?", "почему-то падает") · factual/info statement even with "should be / by default / never"
("deploy should be done in 5 min", "по умолчанию там 8080") · agreement ("actually that makes
sense, go ahead") · reassurance ("don't worry about the tests") · praise-only · off-topic chatter.

### 3. Dedup + draft atomic rules
For each detected correction: write it as ONE atomic rule with an applicability condition. **Dedup
against existing rules/memory** (`grep` `~/.claude/rules/` and the project memory) — if it is already
a rule, skip or propose an EDIT, not a new ADD. Cluster duplicates across sessions into one rule.

### 4. Resolve authority for the exact change
Show the user a compact table: each proposed rule + its applicability condition + source quote +
target file + action (ADD new / EDIT existing / SUPERSEDE old / SPLIT). If that exact change
is not already authorized, ask for approval and retain the proposal. Do not repeatedly
request permission already given for the same in-scope correction. New always-on rules,
`SUPERSEDE` and `DELETE` require the applicable explicit authority.

### 5. Apply (delta-merge, never rewrite)
On approval, apply each accepted delta with the ACE discipline from `memory-maintenance.md`:
addressable ADD/EDIT only, dedup, preserve nuance (no full-file rewrite). Put it in the right home
(`file-organization-cohesion.md`): a global rule → `~/.claude/rules/`, a project-specific lesson →
that project's memory/CLAUDE.md. **If the rule is mechanically checkable** (file-name shape,
forbidden command, tool-call form), note that it should graduate to a hook/validator (deterministic
tier beats prose — `learn-from-corrections.md`).

### 6. Mark only reconciled sessions processed

First account for every selected queue item: inspected transcript, accepted/rejected
corrections and their resulting artifact, or an explicit unresolved evidence gap.
The extractor's `pending` is the selected window when `--limit` is used, not whole-queue
completion. A missing/unreadable transcript is not processed; locate the canonical
private chat archive by session id and inspect the recovered transcript before closing it.
Only ids actually reconciled in this pass go into the following command:
```bash
python ~/.claude/skills/distill-feedback/scripts/extract_feedback_queue.py --mark-processed <session_id> ...
```
Appends to `processed.jsonl` (append-only; the queue is never rewritten). The SessionStart nudge
count drops accordingly.

## Gotchas
- **Missing path is not lost history.** The extractor omits empty/unreadable sessions from its
  payload. Reconcile the selected queue ids against payload ids, search the existing private
  archive and leave unrecovered ids pending with the observed failure. Never mark an omitted
  id processed merely to silence the nudge.
- **Confidence is not authority.** Apply step 4 using the current user's actual authorization.
- **Praise-then-correction is the #1 miss.** "Спасибо, но впредь не трогай прод" IS a correction.
  The rubric handles it; don't let a praise-detector suppress it (that bug killed the keyword version).
- **Billing.** Distillation runs an LLM over user turns. Use `--limit`, run it on-demand (not a hook),
  and prefer a cheaper model for the detection sub-agent (the rubric is not hard reasoning).
- **One-off ≠ durable.** "переделай, я имел в виду src не dist" is a one-off fix, not a standing rule —
  the rubric's confidence + your judgment should drop these; only encode what generalizes.

## Troubleshooting
- *Nudge keeps showing, payload looks empty* → compare queue and payload ids; recover missing
  transcripts from the private archive. A skipped payload is not evidence of completed work.
- *Extractor prints `pending: N` but `sessions: []`* → all N transcripts are missing/unreadable;
  diagnose/recover those specific ids and retain unresolved ones; do not mark them processed.
- *Want to pause capture entirely* → `touch ~/.claude/.skip-feedback-capture` (or
  `CLAUDE_SKIP_FEEDBACK_CAPTURE=1`); the Stop hook then no-ops.

## Related
- `rules/learn-from-corrections.md` — the protocol + the evidence behind LLM-semantic + human-gate
- `rules/memory-maintenance.md` — the delta-merge (ACE) discipline step 5 reuses
- `hooks/session-feedback-capture.py` (Stop, capture) · `hooks/feedback-pending-show.py` (SessionStart, nudge)
