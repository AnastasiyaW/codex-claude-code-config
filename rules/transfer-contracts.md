# 🔴 TRANSFER CONTRACTS: EVERY CLONE/COPY/MOVE HAS A DURABLE TRAIL

File movement is shared mutable state. A later agent must be able to answer,
without reading shell history: what moved, from where, to where, with which
settings, why, by when, what was verified, and whether the source was removed.

## Required workflow

1. Create one JSON record under `.claude/transfers/` before running the command.
   Use [`templates/transfer-contract.json`](../templates/transfer-contract.json)
   as the starting shape. Keep records in the project repository or its private
   operational state; never put credentials in a public repository.
2. Add the marker to the command:

   ```text
   git clone https://example.invalid/repo D:/work/repo # transfer-contract: .claude/transfers/2026-08-09_clone-repo.json
   ```

3. The PreToolUse hook blocks the command unless the record is complete and its
   operation matches the command (`git clone`, `gh repo clone`, `robocopy`,
   `rclone`, `rsync`, `scp`, `sftp`, `xcopy`, `cp`, `copy`, `Copy-Item`, or
   `Move-Item`).
4. After the command, update `status` to `verification_pending` (or `failed`).
   Run the checks named in `verification.plan`, put the result and durable
   evidence paths/commands in `verification`, and only then use `verified`.
5. Source cleanup is a separate decision. Set `source_cleanup.planned` and
   explain it. If it is planned, the record cannot be `verified` until
   `performed=true` and `verified=true`. Deletion still requires the existing
   human-confirmation and post-delete verification gates.
6. Stop is blocked while any record is open or invalid. A genuinely blocked,
   failed, or cancelled transfer may close only with a non-empty
   `closure_reason` and a useful `next_action`, so another agent can resume it.

## Contract fields

| Field | Meaning |
| --- | --- |
| `source`, `destination` | Exact local path, repository URL, host path, or remote endpoint. |
| `operation.kind/tool/settings` | Copy, move, clone, or sync; tool used; flags and relevant settings. |
| `purpose`, `motivation`, `deadline` | Why the transfer exists and when it should be complete. |
| `verification.plan` | The checks that prove destination integrity before cleanup. |
| `verification.performed/result/evidence` | What was actually checked, the verdict, and where proof lives. |
| `source_cleanup` | Whether source deletion was planned, performed, and independently verified. |
| `next_action`, `closure_reason` | The handoff for the next agent and why a non-success state is closed. |

The hook does not claim that an external/remote check happened. For remote
paths, record the command, log, checksum, manifest, or other durable evidence
in `verification.evidence`. For local verified destinations, the hook also
checks that the destination exists; when cleanup is claimed, it checks that the
local source is gone.

## Mechanical wiring

`hooks/transfer-contract-guard.py` is wired for `PreToolUse`, `PostToolUse`,
and `Stop` in both Claude Code and Codex. PreToolUse is the hard start gate;
PostToolUse leaves an explicit reminder; Stop is the orphan-transfer gate.
