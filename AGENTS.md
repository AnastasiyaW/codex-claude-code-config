# AGENTS.md

This is a configuration system repository for AI coding agents, not an application. It collects battle-tested architectural principles, security hardening, and decision frameworks that any coding agent can drop into any project.

## Purpose

- `principles/` - architectural principles, each preventing a specific failure mode
- `alternatives/` - side-by-side comparisons of 2-5 approaches per problem
- `hooks/` - ready-to-use Python hook scripts (session management, safety guards); installer: `scripts/install_hooks.py`
- `templates/` - starter CLAUDE.md and REVIEW.md files for different project types
- `skills/` - domain-specific knowledge bundles (loaded on demand)
- `rules/` - drop-in `.claude/rules/` files (agent-harness design rules live on-demand in the `agent-harness-design` skill, not always-on)
- `workflows/` - dynamic-workflow commands + cost lessons
- `scripts/` - utilities (hook installer, config drift validator, KV-cache stats, public-repo sync)
- `CLAUDE.md` - Claude Code-specific overlay (extends this file)

## How agents should use this repo

When the user asks you to "set up this project" or "apply these principles":

1. Read `README.md` first - it maps principles to the problems they solve
2. Read `principles/README.md` for the maturity-level map (L1 -> L2 -> L3)
3. Do NOT bulk-copy everything. Pick what matches the user's actual project:
   - Any project: Principle 09 (Supply Chain Defense), Principle 10 (Agent Security), Principle 11 (Documentation Integrity)
   - Long sessions expected: Principle 07 (Codified Context) + `alternatives/context-management.md`
   - Long-running project: `templates/long-run-project/`, a Git worktree with an `origin` remote, and an agent-facing KB before creating `feature_list.json` (that marker enables the completion gates)
   - Multi-agent work: Principle 01 (Harness Design) + Principle 06 (Multi-Agent Decomposition)
   - Iterative optimization: Principle 03 (Autoresearch)
4. Before copying a principle, verify the user's stack matches the examples
5. After setup, run `scripts/validate_config.py --strict` and the relevant hook self-tests to catch drift in the freshly assembled config

## Reasoning Policy: Selection Before Expansion

Core rule: **a sufficient solution is a reason to stop expanding, not an invitation to
add optional improvements.**

Within the discretion left to you, keep any material solution you create or choose as a
candidate until its necessity, sufficiency, material consequences, and total ownership
cost support it as the simplest known way to satisfy the requested outcome and required
contracts.

Once a sufficient solution exists, do not propose or add improvements by inertia. Treat
every additional mechanism, abstraction, safeguard, edge-case handling, future-proofing
measure, or process as a separate candidate. Include it only when an accepted
requirement, an applicable constraint, or an evidenced material risk justifies its total
implementation, verification, and ownership cost. Possible usefulness, best practice, or
a desire for greater completeness is not sufficient justification.

If an additional mechanism compensates for a weakness introduced by the base solution,
first revise or simplify the base candidate. Stop when the outcome and required contracts
are satisfied. Do not include optional improvements or rejected candidates unless the
user explicitly asks for them.

This gate does not authorize reopening accepted requirements, explicit operator
decisions, or governing sources.

Written in English deliberately: these instructions are read by models that reason in
English first, so a Russian original risks being applied through a translation nobody
reviewed.

**Relation to the two advisories in `hooks/`.** `over-engineering-advisor` asks whether a
change is the smallest solution; `module-shape-advisor` asks whether a file has outgrown
its shape. This policy is the reasoning-level rule they enforce mechanically at opposite
ends, and it is what keeps them from being read as contradicting each other: neither
argues for more or less code as such, both ask whether the next addition has earned its
cost.

## Style conventions for this repo

- Principles are standalone files in `principles/NN-name.md`
- Each principle has: Overview, The Paradigm, The Mechanism, Case Study, Sources
- Alternatives follow the 5-approach comparison format with a decision table
- Skills are `skills/<category>/<name>/SKILL.md` with an optional `references/` folder
- Descriptions must be model triggers, not human summaries
- Keep SKILL.md under 5000 words; detail goes in `references/`

## Do not touch

- `principles/` existing files: edit only to fix drift, not to restructure
- `scripts/validate_config.py`: any change requires re-testing against the full repo
- `LICENSE`, `UPDATES.md` commit history: append only

## Commands

This repository has no application build or deploy step. Its verification suite checks documentation, skills, hook behavior, and live runtime wiring:

```bash
python scripts/validate_config.py --strict
python scripts/generate_skills_lock.py --check
python scripts/generate_skills_catalog.py --check
python evals/hooks/run_hook_evals.py
python scripts/test_lifecycle_hook_contracts.py
python scripts/test_dependency_provenance_guard.py
python scripts/dependency-alternatives.py --self-test
```

After installing into a local Codex/Claude environment, also run
`python scripts/test_task_completion_hooks.py` and consult
[`docs/runtime-wiring.md`](docs/runtime-wiring.md).

## Context engineering notes

This file is designed for KV-cache efficiency and the 150-line AGENTS.md standard:

- Under 80 lines - fits in a single cached prompt prefix
- No timestamps or dynamic content
- Stable section order - do not shuffle
- Append-only edits preferred over restructuring
- For Claude Code-specific behaviors (hooks, skills automation), see `CLAUDE.md` as an overlay

## Related standards

- [AGENTS.md specification](https://agents.md) - Linux Foundation / Agentic AI Foundation
- [How to write a great AGENTS.md](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/) - GitHub best practices from 2500+ repos
- See `CLAUDE.md` for Claude Code-specific extensions to this file

## Optional RTK Output Compression

When a verified RTK executable is available, use it only for repetitive,
diagnostic shell output such as `rtk git status`, `rtk git diff`, `rtk git log`,
`rtk read`, and supported test runners. Preserve raw output for exact evidence,
novel commands, destructive operations, and logs where ordering matters. RTK
does not replace safety hooks or test gates; its failure mode must be pass-through.
