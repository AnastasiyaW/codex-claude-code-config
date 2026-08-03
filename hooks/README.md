# Hook Scripts

This directory contains shareable Python handlers for Claude Code and Codex.
The scripts are the implementation; the client configuration decides which ones
run. Do not treat a script merely existing here as proof that it is active.

## Install And Verify

For Claude Code, merge the selected handlers into `~/.claude/settings.json`:

```bash
python scripts/install_hooks.py --global --extras
```

For Codex desktop, use the `hooks` object in its user hook configuration. After
installing or changing either runtime, verify the live contract:

```bash
python scripts/test_task_completion_hooks.py
python evals/hooks/run_hook_evals.py
```

`build_hook_catalog.py` creates a JSON inventory of the actual Codex hooks and
their visible status labels. It is useful when the settings UI shows generic
entries such as `Hook 1`.

`keyword-skill-router.py` is advisory: it suggests a curated skill or built-in
workflow, but the agent client's semantic skill loader performs the actual
implicit invocation. Check both boundaries with:

```bash
python scripts/audit_skill_hook_wiring.py --strict
```

When a session reports an overloaded gate, inspect the aggregate feedback
without opening transcripts:

```bash
python scripts/harness_feedback_report.py
```

## What Is Enforced

| Concern | Primary scripts | Event |
|---|---|---|
| Destructive commands and Git operations | `destructive-command-guard.py`, `git-destructive-guard.py`, `human-confirmation-guard.py` | `PreToolUse` |
| Shell injection and self-damage | `command-injection-guard.py`, `self-harm-guard.py` | `PreToolUse` |
| GitHub Actions workflow injection | `github-workflow-security.py` | `PreToolUse` |
| Git source-of-truth adoption | `git-source-gate.py` | `Stop` |
| Tests and code quality | `test-muting-guard.py`, `test-gate-stop-hook.py`, `over-engineering-advisor.py` | `PreToolUse` / `PostToolUse` / `Stop` |
| Readable architecture and module shape | `architecture-first` skill, `architecture-quality` skill, `module-shape-advisor.py`, `scripts/architecture_audit.py` | router / `PostToolUse` / explicit audit |
| Harness scope and overload feedback | `harness-load-advisor.py`, `harness-feedback` skill | `Stop` / router |
| Documentation and long-run state | `docs-staleness-guard.py`, `kb-validate-gate.py`, `feature-list-validator.py` | `SessionStart` / `Stop` |
| Completion and handoff quality | `handoff-closure-audit-guard.py`, `precompact-handoff-guard.py`, `session-handoff-reminder.py`, `stop-phrase-guard.py` | `PreToolUse` / `PreCompact` / `Stop` |
| Deletion proof and secret exposure | `verify-deleted-guard.py`, `api-key-leak-detector.py`, `secret-leak-guard.py` | `PostToolUse` / `PreToolUse` |
| Session continuity | `session-handoff-check.py`, `conversation-history-capture.py` | `SessionStart` / `Stop` |

The full cross-client contract, including which checks are deliberately scoped
to long-running projects, is documented in
[runtime-wiring.md](../docs/runtime-wiring.md).

## Handler Semantics

A blocking hook must return a valid blocking decision or use the client-defined
blocking exit code. A successful process exit by itself is not enforcement.
Keep handlers small, deterministic, and independently testable. Do not combine
unrelated policies in one handler; run related checks as separate hooks.

Plugin hook files and user settings use different top-level schemas. Claude Code
plugins may include metadata such as `description`; the current Codex desktop
plugin loader accepts only the `hooks` wrapper. Use
`scripts/repair_codex_plugin_hook_schema.py --fix` if a plugin update introduces
that incompatibility, then rerun the task-completion test.

The architecture signal is intentionally split. `architecture-first` decides the
seams before a new system exists; `architecture-quality` keeps those seams readable
while web/service code grows; `module-shape-advisor.py` is a live advisory hook after
code edits; and `architecture_audit.py` is a deterministic repository-level report.
The hook is not a substitute for project-specific dependency contracts.

See the current [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
for supported events, handler types, and result schemas.
