---
name: cross-harness-continuation
description: "Use when work moves between Claude Code and Codex, a session resumes from a handoff, or an agent may rewrite an existing implementation. Loads the shared CONTINUITY.json contract, preserves accepted decisions, checks Git baseline and scope, and requires explicit replan mode for intentional redesign. Do NOT use for fresh work with no prior agent's decisions to preserve, for a single-harness session that no one else is continuing, or as a general handoff-writing helper (see the session-handoff rule); this skill governs the contract between agents, not the notes one agent leaves itself."
---

# Cross-Harness Continuation

Use this skill when a task continues after another agent, especially when the
handoff is Claude -> Codex, Codex -> Claude, or a plugin has already received
several partial fixes.

## Operating contract

The repository is the source of truth for code. The continuation contract is
the source of truth for intent that Git cannot express:

`<repo>/.claude/continuity/CONTINUITY.json`

The canonical shape is in `references/CONTINUITY.example.json`. It must contain:

- `mode`: `continuation` for incremental work, `new` for greenfield work;
- `baseline`: branch, commit, and paths that were already dirty at handoff;
- `scope.files`: the files explicitly claimed for the current slice;
- `preserve`: accepted design decisions and invariants;
- `do_not_redo`: approaches already tested or deliberately rejected;
- `verification`: commands and evidence status;
- `scope.enforce` and `scope.protect_unlisted` when the slice must be strict.

## Required sequence

1. Read `CONTINUITY.json`, the newest handoff, `AGENTS.md`/`CLAUDE.md`, and
   the current Git status. Treat the live checkout as authoritative over stale
   prose.
2. Verify the baseline commit, branch, dirty paths, and the claimed files.
   Preserve existing changes unless a test or the contract proves they are
   wrong.
3. Make one focused continuation change. Use `Edit` for existing files. Do not
   replace a whole file merely because another implementation is easier to
   write.
4. Run the smallest relevant test, then the independent verifier for a
   non-trivial or cross-module change. Record commands and outcomes in the
   contract or handoff.
5. Update the contract with what was preserved, what changed, what failed, and
   the single next step. Commit a clean, descriptive checkpoint when the
   project workflow allows it.

## Replan boundary

Replanning is valid when measured evidence shows the current design is wrong,
the requirements changed, or an explicit user decision authorizes a redesign.
Declare it in the process that launches the agent:

```text
AGENT_CONTINUITY_MODE=replan
AGENT_CONTINUITY_REASON=<specific evidence and intended redesign>
```

The reason is required. Without it, the guard blocks whole-file overwrites,
out-of-scope edits, and near-whole-file replacements. A replan must also be
recorded in the decision log/handoff; an environment flag alone is not proof.

## Plugin cleanup

Do not revert a plugin because its code “looks different”. First classify the
diff as intentional, unverified, or conflicting; reconstruct the baseline from
Git; run the plugin's focused tests and a fresh read-only verifier; then repair
only confirmed regressions. Keep the old implementation available through Git
or an isolated worktree until the replacement passes its acceptance checks.

## Gotchas

- A handoff without baseline and changed-file facts is context, not a merge
  contract. Do not infer scope from prose alone.
- A clean Git tree does not prove semantic compatibility. Run the focused test
  and inspect the dependency boundary before declaring continuation complete.
- Parallel agents need isolated worktrees and an integration verifier; this
  skill protects serial handoff and cannot resolve a concurrent merge for you.
- `CONTINUITY.json` is intentionally small. Put long research and transcripts
  in the private archive or project docs and link them from the contract.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No CONTINUITY.json found` | The prior session left only prose handoff | Create the contract from the current Git baseline before editing existing code |
| `scope violation` | The task expanded beyond the claimed slice | Finish the slice or update scope with a recorded reason |
| `blocks Write over existing tracked file` | Whole-file overwrite would erase prior intent | Use a focused `Edit`, or explicitly enter replan mode |
| `near-whole-file replacement` | An edit is acting like a rewrite | Split the edit and test each step, or replan with evidence |
| Claude and Codex disagree | No shared decision/evidence was recorded | Re-read `preserve`, `do_not_redo`, tests, and Git; do not “pick a side” by intuition |
