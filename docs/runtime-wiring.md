# Runtime Wiring And Verification

This repository is the source of truth for shareable rules, hook scripts, and
skills. Each agent client has its own small runtime configuration that points to
those files. A rule is not considered adopted until its wiring and its test both
pass.

## Policy Boundaries

- Git first: durable project code, documentation, plans, proofs, and handoffs
  belong in a repository. New operational repositories are private unless the
  user explicitly requests public visibility.
- Documentation is mandatory for a project that adopts the long-run harness.
  `feature_list.json` without a KB blocks session completion; a project KB
  validator also blocks completion when agent docs no longer match its code.
- Git source-of-truth setup is mandatory for the same adopted projects:
  `git-source-gate.py` blocks completion until the project has a Git worktree
  and an `origin` remote. It deliberately does not force commits for an
  arbitrary dirty tree, because a global hook cannot safely classify another
  person's changes.
- Scratch folders are not documentation-gated. The long-run marker is the
  explicit boundary that turns the gate on.
- Client-specific or private-only overlays may add local handlers, but this
  public repository documents and tests only handlers it actually contains.
- Raw session archives and operational credentials are private-only and are not
  part of this public repository.
- High-frequency runtime reports are regenerable operational state. Route them
  with `--report-dir` outside a project worktree; keep durable conclusions in a
  handoff, chronicle, test artifact, or commit instead.

## Runtime Contract

| Concern | Codex desktop | Claude Code | Proof |
|---|---|---|---|
| Destructive-operation guards | `PreToolUse` | `PreToolUse` | hook eval cases |
| Handoff completeness | `PreToolUse`, `Stop`, `PreCompact` | `PreToolUse`, `Stop`, `PreCompact` | `test_task_completion_hooks.py` |
| Handoff to memory continuity | `SessionStart` | `SessionStart` | `test_review_handoff_memory_loop.py` |
| Claude/Codex continuation contract | `PreToolUse`, `SessionStart` | `PreToolUse`, `SessionStart` | `scripts/test_continuity_contract.py` |
| Agent-doc freshness | `SessionStart` advisory + `Stop` gate | `SessionStart` advisory + `Stop` gate | hook self-tests |
| Git source-of-truth setup | `Stop` for long-run projects | `Stop` for long-run projects | `test_lifecycle_hook_contracts.py` |
| Skills availability | active skill directory | `~/.claude/skills` | `sync_skills_to_codex.py --check` and `skills-lock.json` |
| Skills survive a machine/account move | active skill directory | `~/.claude/skills` | `recover_skill_trees.py --report` |
| Optional RTK output compression | instruction-level (`AGENTS.md`) | native `PreToolUse` hook | `scripts/test_rtk_integration.py` plus pinned binary verification |

Codex's current plugin loader accepts only a top-level `hooks` object in cached
plugin hook files. `repair_codex_plugin_hook_schema.py --fix` safely removes the
otherwise harmless Claude-compatible `description` field and preserves a backup.

## Skill routing layers

There are two deliberately separate routing layers:

1. The agent client's semantic loader reads each skill's `SKILL.md` frontmatter
   (`name` and `description`) and decides which skill body to inject. A skill's
   `agents/openai.yaml` may set `policy.allow_implicit_invocation: false`; the
   default is `true`. This is the mechanism that handles the full skill catalog.
2. `hooks/keyword-skill-router.py` is a small, curated `UserPromptSubmit`
   advisory. It catches only high-confidence phrases and prints a suggestion;
   it does not inject a skill and must not become a second copy of the whole
   semantic catalog.

A skill the loader cannot read is absent no matter how correct the routing is.
After a machine or account move, verify the catalog itself before trusting either
layer: dangling cross-profile links, empty directory shells and a UTF-8 BOM each
hide a skill without producing an error. See
[skill-tree-recovery.md](skill-tree-recovery.md).

```bash
python scripts/recover_skill_trees.py --report
```

Run the live boundary audit after changing either side:

```bash
python scripts/audit_skill_hook_wiring.py --strict
```

The audit checks active and source skill metadata, implicit-invocation flags,
all configured hook command targets, the live UserPromptSubmit wiring, and every
curated router target. Duplicate nested plugin copies are reported as warnings;
they are not silently treated as one canonical skill.

## Verification

Run the following after changing the public configuration. The final two commands
also prove the locally installed runtime, so run them after installation.

```bash
python scripts/validate_config.py --strict
python scripts/generate_skills_lock.py --check
python scripts/generate_skills_catalog.py --check
python evals/hooks/run_hook_evals.py
python scripts/test_lifecycle_hook_contracts.py
python scripts/test_task_completion_hooks.py
python scripts/sync_skills_to_codex.py --check
```

For a plugin update that causes a hook-schema error:

```bash
python scripts/repair_codex_plugin_hook_schema.py --fix
python scripts/test_task_completion_hooks.py
```

The standard Claude Code hook format and lifecycle are documented in the
[Claude Code hooks reference](https://code.claude.com/docs/en/hooks). Codex and
Claude are intentionally verified separately because their configuration parsers
and available tool names differ.

## What The Evidence Means

Skill linting, the portable lockfile, and synchronization prove that a skill is
valid, versioned, and available to the client. The lock normalizes UTF-8 text
newlines, so the same checkout verifies on Windows and Linux. Router evals prove
selected automatic suggestions; the wiring audit proves that those suggestions
cannot point at missing skills. Neither proves that every piece of advisory
knowledge improves every task. Promote a skill to a mandatory route only after
a task-specific before/after evaluation with a measurable acceptance criterion.

## Continuation Contract

When a project declares `mode: continuation` in `CONTINUITY.json`, the guard
protects existing tracked files from silent whole-file rewrites and can enforce
the claimed scope. Intentional redesign requires `AGENT_CONTINUITY_MODE=replan`
and a non-empty `AGENT_CONTINUITY_REASON` recorded in the handoff.
