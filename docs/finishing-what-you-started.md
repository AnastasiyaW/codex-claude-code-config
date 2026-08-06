# The deferral moves to whichever form is not guarded

Research question: what harness machinery makes a coding agent finish what it started,
instead of stopping and writing the rest into a handoff? Someone must have built this.

Several people have. The useful part is not the mechanisms — it is what happened to each
of them, and what the enforcement history in one repository shows about where the
behaviour goes when you close a door.

## The prior art, and the shape of its failure

**Block the stop.** [`blader/taskmaster`](https://github.com/blader/taskmaster) is a Stop
hook that keeps the agent working until the run is complete, where complete means the
assistant emitted `TASKMASTER_DONE::<session_id>`. Without the token, Stop is blocked and
a compliance prompt is injected. A done token suppresses injection for that turn only.

**What blocking the stop costs.**
[anthropics/claude-code#55754](https://github.com/anthropics/claude-code/issues/55754) is
the same idea in production: a Stop hook returning `{"ok": false}` while the agent was
legitimately waiting on background agents. The skill in use forbade tool calls during the
wait, so every turn was text-only, every turn was graded incomplete, and the loop ran
>100 times over ~50 minutes until the session quota was gone. The author's proposed
guardrails are worth reading as a checklist: enforce `stop_hook_active`, cap the
continuations, expose pending async work to hooks, and let async-by-design skills opt out.

The general form is old — [Microsoft's Agent Framework
harness](https://learn.microsoft.com/en-us/agent-framework/agents/harness) re-invokes the
agent until a `LoopEvaluator` is satisfied (a completion marker, a predicate, or a judge),
with a todo list and plan/execute mode built in; [loop-harness](https://github.com/lSAAGl/loop-harness)
runs the loop in an isolated worktree with a second agent verifying before anything ships;
Claude Code ships `/loop`. And the failure it addresses is documented too:
[#6159](https://github.com/anthropics/claude-code/issues/6159), "stops mid-task and fails
to complete its own plan".

So: forcing continuation is solved, and its own failure mode — an agent forced to continue
when it cannot act — costs a session. Any implementation needs a hard cap. That guardrail
already exists here as a stop-budget: a blocking gate refuses at most three times, then
yields, so a stuck gate cannot lock a session shut.

## What the enforcement history actually shows

This repository has been closing this door for a while, and the record is more instructive
than any of the mechanisms:

1. **Phrases.** `stop-phrase-guard` blocks a final message containing "next session",
   "out of scope", "good stopping point". Deferral by wording became impossible.
2. **Reasons.** `no-pre-existing-evasion` replaced the wording with a taxonomy: work may
   be deferred only under one of five named reasons, recorded in `PROBLEMS.md`.
3. **Audits.** `handoff-closure-audit-guard` refuses a handoff that does not state whether
   the primary request is complete, what adjacent work was checked, and where anything
   unfinished is tracked.

Measured on this hub on 2026-08-05: **51 open entries, 27 of them `arch-decision`.** One of
the five legitimate reasons carries 53% of everything deferred. Median age 8 days.

That number is the finding. Every layer closed a *form* of deferral, and the behaviour
moved to the next form that was not checked: from a sentence, to a label, to a label that
means "someone must decide" and is never followed by a decision. Nothing here was cheating;
each entry looks correct in isolation. The distribution is what gives it away.

## What follows from that

A gate that reads the label cannot catch this, because the label is now the disguise. The
gate has to read a fact instead. The narrowest fact available: **a ticket opened today, in
this handoff's own project, still open, and not mentioned in the handoff.** That is a
finding this session made and walked away from — not a backlog, not another team's work.

Two bounds matter, and both came from measuring rather than reasoning:

- **Same-day alone is wrong.** On a hub with a dozen concurrent sessions it holds every
  handoff responsible for every ticket opened that day. Over the full handoff history it
  would have blocked **98 of 102**. A gate that stops everything gets switched off.
- **With project attribution it blocks 7** — and those 7 include `PROJECT-CANCEL-01/02`
  passing unmentioned through four consecutive handoffs from two different sessions. That
  is the exact behaviour the gate exists for, and it was invisible until counted.

It fires when a handoff is written, not at Stop, so it cannot produce the #55754 loop:
there is no turn to re-block, only a file write to refuse.

## What this does not fix

- **The backlog it inherits.** 27 `arch-decision` entries stay open; nothing here closes
  them, and a gate on today's tickets will never touch them. They need deciding, and the
  measurement above is the argument for doing it, not a substitute.
- **Tickets without an identifier.** Matching is on an explicit uppercase id; an entry
  titled in prose is skipped rather than matched fuzzily, so a session can still evade by
  not naming its ticket. That is a known hole, left open deliberately: a fuzzy match that
  blocks the wrong handoff is worse than a gap.
- **Whether the work was actually done.** The gate proves the handoff *mentions* the
  ticket. Mentioning is not finishing — the next disguise, if this holds, will be a
  mention that says nothing. The pattern above predicts it.
