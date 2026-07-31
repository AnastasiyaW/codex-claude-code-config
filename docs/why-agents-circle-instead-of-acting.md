# Why an agent circles instead of acting

An agent that describes a fix instead of applying it is usually read as timidity. On a harness
where this was measured it turned out to be a gradient: describing was the only move with no
gate on it. This note records what was measured, what is inference, and what to change.

## The measurement

One machine, two agents, the same rules — the shared context file is byte-identical between
them, so the rules are not the variable. The gate configuration is:

| | Blocking gates | Where they sit | Default posture |
|---|---|---|---|
| Agent A | 11 of 54 hooks | **8 on `Stop`**, 3 on `PreToolUse` | gated |
| Agent B | pre-tool hooks present | — | `approval_policy = "never"`, `sandbox_mode = "danger-full-access"`, `trust_level = "trusted"` |

Agent B is configured to act without asking. Agent A has most of its blocking surface aimed at
*ending a turn*: red tests, open incident entries, knowledge-base drift, a missing handoff,
deferral phrasing.

## What follows from that shape

The Stop gates are good gates. Each one catches a real failure. But look at what they select
for, taken together with the rule surface:

- **Acting** passes through 3 pre-tool gates, plus explicit confirmation rules for deletion,
  destructive operations and anything irreversible — roughly six enumerated "confirm first"
  rules against one "reversible means act".
- **Ending** passes through 8 gates, all of which ask *how* the turn ended.
- **Describing a finding** passes through **none**. It is not a tool call, so no pre-tool gate
  sees it; and it partially satisfies the Stop gates, because something was reported.

So the cheapest path through the harness is to write about the work. Not because the agent is
cautious — because that is where the gates are not.

The asymmetry is sharper than the counts suggest. The prohibitions are **hooks**; the
permission is **prose**. Prose loses to task pressure — that is the whole reason the hooks
exist. So the enforcement asymmetry becomes a behaviour asymmetry, reliably.

## What is inference, not measurement

Two things I cannot demonstrate from this data and will not assert:

- that model-level training toward deference contributes. It plausibly does; nothing here
  isolates it from the harness effect.
- that the second agent's directness comes from its posture rather than its prompt. Both differ.
  The posture is what was measured; the prompt was not.

The honest claim is narrower: **a harness with more blocking gates on finishing than on acting
will produce agents that write instead of act, whatever the model does.**

## Countermeasures

**Close the zero-gate path.** A deferral guard that catches the *question* form ("what next?",
"shall I?") leaves the *indicative* form wide open — "X is hardcoded, raising it is nearly
free" is the same deferral in a statement. Same gate, extended to describing a cheap reversible
improvement without evidence of having applied it.

**Make the permission surface as concrete as the prohibition surface.** "Reversible means act"
loses to six enumerated confirmation rules because it is one sentence against six checklists.
Enumerate it the same way: restart, re-run, config edit with backup, unblocking a pipeline,
launching a job, deploying a reversible fix. A list argues with a list; a principle does not.

**Plan silently unless a plan was requested.** The failure is not planning — it is shipping the
plan *as* the deliverable. If the user asked for work, the plan is scaffolding and belongs in
the same turn as its execution.

**Let the gates that guard irreversibility keep their teeth.** None of this argues for fewer
confirmations on deletion or destructive operations. It argues for the reversible side being
enforced with the same mechanism rather than left to good intentions.

## How to tell it is working

Not by tone. The measurable signal is the ratio of turns that end with an applied-and-verified
change to turns that end with a described one, on tasks where the action was reversible and
already authorised. If that ratio does not move, the gate change did not work — which is itself
an instance of the rule that a fix is a hypothesis until measured.
