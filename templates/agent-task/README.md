# Agent Task Artifact Template

Use this directory as the starting shape for `.agent/tasks/<task-id>/` when a task is long-running, multi-agent, high-risk, or likely to cross a context compaction boundary.

Copy the files into the project task directory, then fill in placeholders. Keep large outputs in `evidence/` and reference them from `trace.jsonl`, `state.json`, and `handoff.md`.

## Files

| File | Purpose |
|---|---|
| `spec.md` | Frozen objective, acceptance criteria, and global constraints |
| `state.json` | Machine-readable task state for resumption |
| `findings.json` | Structured evaluator findings that become work orders |
| `cycle.json` | Controller-owned queue; generated from `findings.json` |
| `scratchpad.md` | Human-readable working notes; keep current, not exhaustive |
| `trace.jsonl` | Append-only event log with evidence pointers |
| `evidence/` | Raw test output, screenshots, logs, diffs, verifier outputs |
| `verdict.json` | Fresh verifier judgment |
| `problems.md` | FAIL findings that need fixes |
| `fix-log.md` | Fixer changes and why they were made |
| `handoff.md` | Compact transfer note for another chat/session |

## Context Rule

Treat the model context window as RAM and this folder as disk. The chat should carry only the current state, next action, and pointers to evidence, not every raw observation.

## Scheduled work loop

For a task that must keep moving between sessions, use the controller from the
configuration repository rather than embedding a changing prose backlog in the
scheduled prompt:

```text
python scripts/task_cycle_controller.py reconcile --task-dir .agent/tasks/<task-id>
python scripts/task_cycle_controller.py next --task-dir .agent/tasks/<task-id> --json
```

The heartbeat treats `WORK` as its exact current focus. It stores real test,
runtime, and fresh-review artifacts before calling `record-proof`. `WAIT_EXTERNAL`
is legal only when every external work order names both its last live check and
the next scheduled recheck; an overdue one returns `RECHECK_EXTERNAL` instead.
