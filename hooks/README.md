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

## Lifecycle Map

Install only the stages that solve a real project risk. The scripts are not one
mandatory preset.

| Stage | Typical handlers | What stays out of the hook path |
|---|---|---|
| `UserPromptSubmit` | `keyword-skill-router.py`, `open-items-are-work-orders.py` | Full history scans and index rebuilds |
| `SessionStart` | handoff, continuity, docs, and feedback checks | Reconstructing a whole past conversation |
| `PreToolUse` | safety, dependency, transfer, and scope guards | Broad best-effort review unrelated to the tool |
| `PostToolUse` | deletion/transfer proof and advisories | Declaring a result complete without observing it |
| `PreCompact` / `Stop` | handoff, test, tracked-work, and closure gates | Auto-inventing a trustworthy handoff |

See [runtime-wiring.md](../docs/runtime-wiring.md#hook-lifecycle-and-continuity)
for the full cross-client lifecycle, durable-state pattern, and proof boundary.

## What Is Enforced

| Concern | Primary scripts | Event |
|---|---|---|
| Destructive commands and Git operations | `destructive-command-guard.py`, `git-destructive-guard.py`, `human-confirmation-guard.py` | `PreToolUse` |
| Dependency freshness and artifact provenance | `dependency-currency-guard.py`, `dependency-provenance-guard.py` | `PreToolUse` |
| Shell injection and self-damage | `command-injection-guard.py`, `self-harm-guard.py` | `PreToolUse` |
| GitHub Actions workflow injection | `github-workflow-security.py` | `PreToolUse` |
| Git source-of-truth adoption | `git-source-gate.py` | `Stop` |
| Tests and code quality | `test-muting-guard.py`, `test-gate-stop-hook.py`, `over-engineering-advisor.py` | `PreToolUse` / `PostToolUse` / `Stop` |
| Measured outward facts | `outward-claim-evidence-guard.py`, `rules/no-guessing.md` | `Stop` / rule |
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

The dependency boundary is split deliberately. `dependency-currency-guard.py`
checks a manifest edit against the public registry: existence, release age,
adoption, and the slopsquat profile. `dependency-provenance-guard.py` runs at
the download boundary: it rejects direct wheels/archives/Git sources and extra
indexes, requires hash- or lock-aware install modes, and checks exact package
versions for explicit installs. A registry digest binds the fetched artifact to
the registry metadata; it does not prove that a maintainer account was never
compromised, so lockfile review and vulnerability scanning remain separate
controls.

Registry unavailability is fail-closed for new dependency edits and installs. A
24-hour verified provenance cache or an already reviewed lockfile with artifact
integrity may keep a known-good repeat install moving; otherwise use
`scripts/dependency-alternatives.py`, which searches official PyPI/npm metadata
and returns only age- and digest-verified candidates. It never installs or edits
the manifest automatically.

`outward-claim-evidence-guard.py` is deliberately narrow: it notices only
measurement-shaped claims such as a SHA-256 equality, exact file size, installed
version, or deployment state when the final answer lacks a probe/result line.
It cannot validate the command's truth and must never be presented as proof by
itself. General natural-language fact checking here would make every Stop noisy;
the authoritative process remains `rules/no-guessing.md`, a direct measurement,
and a fresh verifier for high-risk claims. Review its event count and false
positives before expanding its patterns.

See the current [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
for supported events, handler types, and result schemas.
