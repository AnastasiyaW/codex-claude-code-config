---
name: control-cli
description: Drive and inspect an interactive CLI or TUI with a repeatable local harness, deterministic input, transcripts, and optional profiling. Use for CLI UX checks, prompt flows, startup regressions, hangs, interrupts, resize behavior, or memory growth. Do not use for a non-interactive command that a normal test can cover.
---

# Control CLI

Exercise an interactive terminal program through a small, repeatable harness.
Prefer a repository-native demo or test harness; only assemble a temporary PTY
or terminal session when the project has no suitable one.

## Harness Loop

1. Identify the command, smallest fixture, expected ready marker, and cleanup
   condition.
2. Discover existing package scripts, PTY helpers, expect scripts, demo
   recorders, or TUI tests.
3. Launch in an isolated environment with deterministic variables and local
   disposable data.
4. Capture the initial screen or transcript.
5. Send one action at a time and wait for a concrete prompt or screen marker.
6. Capture the resulting transcript and any requested profile artifact.
7. Stop the process and remove temporary sessions, ports, and profiles.

On Windows, prefer the project's own test runner or a checked-in Python/Node
probe. Use ConPTY or an already-installed PTY helper when available; do not add
a dependency just to run a one-off probe. On other systems, `tmux`, `pty`, or a
repository-supported terminal harness may be appropriate.

## Evidence

For a bug fix or regression, run the same deterministic interaction against the
baseline and treatment and pass the captures to `verify-this`. For a hang, keep
the last screen, process exit state, timeout, and a stack/CPU sample when
available. For memory growth, use equal repetitions and record before/after
snapshots or a bounded allocation metric.

Prefer stable text markers and accessibility-aware terminal probes over sleeps.
If a sleep is unavoidable, state why and keep it bounded.

## Safety

- Never send credentials, destructive commands, or production paths into the
  controlled session.
- Do not rely on stale screen state after navigation, resize, or a prompt change.
- Do not hard-code paths, ports, or commands from another repository.
- Keep transcripts and profiles private when they contain prompts, source, or
  user data.

## Gotchas

- A process that exits successfully before receiving input is not proof that the
  interactive flow works; assert the ready marker and the expected state change.
- Fixed sleeps hide race conditions and make a green run non-repeatable.
- A terminal transcript can miss rendering defects; use a real UI surface for
  graphical claims.
- Cleanup must be verified, especially after a timeout or forced interrupt.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Harness hangs | Wrong ready marker or child process owns the terminal | Capture the screen, inspect the process tree, then terminate cleanly |
| Input is ignored | Program is not in the expected prompt state | Wait for a fresh marker and send one action only |
| Works manually, fails in harness | Hidden environment, terminal size, or timing dependency | Record env/size and replace sleeps with state-based waits |
| Transcript is empty | Output is on another stream or the PTY was detached | Capture stdout and stderr through the repo-native harness and verify file size |

## Source

Adapted from Cursor Team Kit's MIT-licensed `control-cli` workflow:
https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/control-cli
