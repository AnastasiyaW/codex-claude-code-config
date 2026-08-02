# Claude Code + Codex Agent Configuration System

[![OKF v0.1 compliant](https://img.shields.io/badge/OKF-v0.1%20compliant-4285F4)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)

A practical configuration kit for Claude Code, Codex, and other coding agents. It contains architectural principles, enforcement hooks, skills, drop-in rules, starter templates, and dynamic-workflow commands. Drop the relevant parts into a project so the agent starts from verified working patterns instead of rediscovering them every session.

This is not a collection of tips. It is a **system** that teaches your agent *how to work* - when to use one agent vs many, how to verify its own output, how to manage context across long sessions, how to not get poisoned by malicious packages.

## Notes

Write-ups of the incidents that produced a rule or a hook here. Each states what was measured,
what is inference, and what the fix does not cover.

| | |
|---|---|
| **[Starting from what you remember](docs/starting-from-what-you-remember.md)** | Why a brand-new project arrives years out of date, why an invented package name is now a security problem rather than a 404, and where a dependency check has to sit to catch either. Ships as [`hooks/dependency-currency-guard.py`](hooks/dependency-currency-guard.py). |
| **[Why an agent circles instead of acting](docs/why-agents-circle-instead-of-acting.md)** | Two agents, identical rules, different gate shapes. Describing a fix instead of applying it turned out to be the only move with no gate on it. |
| **[Gates that cannot bootstrap themselves](principles/30-gates-that-cannot-bootstrap.md)** | A check that only arms once the thing it checks for already exists will never arm. The failure looks exactly like compliance. |
| **[Nine skills, one skeleton, and nobody reaching for them](docs/skills-organised-by-author.md)** | Nine architecture skills existed and one was reachable — the one arguing for less code. How a one-sided advisory becomes a ratchet toward monoliths, and why filing knowledge by source book makes it unreachable. |

---

## Installation

Three paths depending on what you need:

### Option 1: Claude Code plugin (fastest)

```bash
claude plugin install https://github.com/AnastasiyaW/claude-code-config
```

Then in your Claude Code chat:

```
Read AGENTS.md and pick the principles, hooks, and skills that match my project.
```

### Option 2: Global install (hooks + skills available in every project)

```bash
git clone https://github.com/AnastasiyaW/claude-code-config ~/claude-code-config

# Copy the always-on safety hooks to your global config
python ~/claude-code-config/scripts/install_hooks.py --global

# Claude Code: copy a selected skill directory, not its parent category
mkdir -p ~/.claude/skills
cp -r ~/claude-code-config/skills/ai-ml/ml-research-lab ~/.claude/skills/

# Codex desktop: sync all public skills with backups for changed local copies
python ~/claude-code-config/scripts/sync_skills_to_codex.py --apply
```

`~/.claude/hooks/` stores the hook scripts; `~/.claude/settings.json` is where they are registered. The install script merges safe defaults into your existing settings.

### Option 3: Project-local (hooks/skills only in this project)

```bash
cd /your/project
git clone https://github.com/AnastasiyaW/claude-code-config .claude-config
python .claude-config/scripts/install_hooks.py --local
cp -r .claude-config/skills .claude/skills
```

This keeps everything under `.claude/` in your repo, nothing global.

### Choosing what to install

| Project type | Minimum viable set |
|---|---|
| **Any project** | 5 safety hooks (destructive-command, secret-leak, git-destructive, git-auto-backup, session-drift-validator) + Principles 09 (Supply Chain), 10 (Agent Security), 11 (Documentation Integrity) |
| **Web app** | above + `frontend-design` skill + Principles 04 (Deterministic Orchestration), 05 (Structured Reasoning) |
| **ML / data pipeline** | above + `flux2-*`, `diffusion-engineering`, `vlm-segmentation` skills + Principles 03 (Autoresearch), 12 (Low-Signal Training) |
| **Multi-agent / parallel sessions** | above + [mclaude](https://github.com/AnastasiyaW/mclaude) + Principles 01 (Harness), 06 (Multi-Agent), 18 (Multi-Session Coordination), 19 (Inter-Agent Communication) |
| **Library / package** | above + Principles 08 (Skills Best Practices), 17 (DBS Skill Creation) |
| **More than one CLI agent (Claude + Gemini / Codex)** | above + [rules/cross-harness-agents-md.md](rules/cross-harness-agents-md.md) (one `AGENTS.md` per project, no symlinks) + `gemini-delegate` skill |

See [AGENTS.md](AGENTS.md) for the procedure an agent follows after install,
[HOW-IT-WORKS.md](HOW-IT-WORKS.md) for the mechanics of each layer, and
[docs/runtime-wiring.md](docs/runtime-wiring.md) for the live verification contract.

Moved the config to a new machine or account and most skills stopped being
offered? Nothing raises an error when that happens — see
[docs/skill-tree-recovery.md](docs/skill-tree-recovery.md) and run
`python scripts/recover_skill_trees.py --report`.

---

## What This Gives You

**Architectural Principles** - each one prevents a specific failure mode observed in real agent workflows:

- **Self-evaluation bias?** Separate Generator and Evaluator agents ([Harness Design](principles/01-harness-design.md))
- **Agent claims "done" but it's broken?** Require durable proof artifacts ([Proof Loop](principles/02-proof-loop.md))
- **Need to improve a prompt/skill/config?** Automated Read-Change-Test loop ([Autoresearch](principles/03-autoresearch.md))
- **LLM skips steps in complex workflows?** Shell scripts for mechanical tasks, one step at a time ([Deterministic Orchestration](principles/04-deterministic-orchestration.md))
- **Wrong debugging conclusions?** Structured Premises-Trace-Conclusions format ([Structured Reasoning](principles/05-structured-reasoning.md))
- **Task too big for one agent?** Coordinator + specialized sub-agents ([Multi-Agent Decomposition](principles/06-multi-agent-decomposition.md))
- **Context degrades in long sessions?** Treat CLAUDE.md as runtime config, not docs ([Codified Context](principles/07-codified-context.md))
- **Supply chain attack?** Two config lines block packages younger than 7 days ([Supply Chain Defense](principles/09-supply-chain-defense.md))
- **Prompt injection via repo/MCP/web?** Six-layer defense with real CVEs ([Agent Security](principles/10-agent-security.md))
- **Docs reference files that no longer exist?** SessionStart hook validates every reference ([Documentation Integrity](principles/11-documentation-integrity.md)) - ships with a working validator script
- **Multi-agent infrastructure overhead?** Separate brain from hands with lazy provisioning ([Managed Agents](principles/14-managed-agents.md))
- **Agent cuts corners on critical rules?** Absolute prohibitions with incident history ([Red Lines](principles/15-red-lines.md))
- **Long-running project lost its history?** Condensed timeline per project, alongside handoffs ([Project Chronicles](principles/16-project-chronicles.md))
- **Skill is a monolithic wall of text?** Split into Direction, Blueprints, Solutions ([DBS Framework](principles/17-dbs-skill-creation.md))
- **Parallel chats fight over GPUs or overwrite each other's state?** Append-only handoffs + lock-file coordination ([Multi-Session Coordination](principles/18-multi-session-coordination.md))
- **One chat needs to send a specific request to another?** File-based mailbox with email-style threading and delivery receipts ([Inter-Agent Communication](principles/19-inter-agent-communication.md))
- **AI-assisted code review findings get rediscovered next PR?** Review finding → regression test → invariant → cross-reference ([Knowledge Base Enforcement](principles/21-knowledge-base-enforcement.md))
- **Zero-day vulnerabilities buried in source tree?** LLM + rules + SAST pipeline ([Vulnerability Detection Pipeline](principles/20-vulnerability-detection-pipeline.md))
- **User needs to choose between visual options (UI, design, diagrams)?** HTML fragment server + file-based event queue ([Visual Context Pattern](principles/22-visual-context-pattern.md))
- **Output keeps reverting to generic defaults (Inter font, SELECT *, etc.)?** Anti-attractor procedure + three-layer enforcement ([Anti-pattern as Config](principles/23-anti-pattern-as-config.md))
- **Merge conflict resolved "by logic" and lost half the work?** Two-agent isolated reconciliation + verified-data priority ([Merge Conflict Resolution](principles/24-merge-conflict-resolution.md))
- **Built a coordination primitive from scratch?** Map it to the classical analog first (Chubby lease, WAL, SMTP) and inherit 30 years of failure-mode literature ([Coordination Primitives Mapping](principles/25-coordination-primitives-mapping.md))
- **Bug fix detoured into "this was already broken before me"?** Five valid deferral reasons + mandatory durable proof artifacts ([No-Pre-Existing Evasion](principles/26-no-pre-existing-evasion.md))
- **Long-run project's scope and progress scattered across 30+ handoffs?** Three-artifact harness (PROBLEMS.md + feature_list.json + init.sh) with WIP=1 invariant and L1/L2/L3 evidence requirements ([Feature Tracking](principles/27-feature-tracking.md))
- **Feature rationale evaporates into git log after 6 weeks?** Three-tier KB (Global -> Layer -> Feature narrative) with ULTRAPACK-style task.md, auto-allocated F-NNN ID, hyperlinked invariants ([Feature-Layer Architecture](principles/28-feature-layer-architecture.md))
- **Model collapses to "predict zero" on residual/delta tasks?** Traps and fixes for low-signal training (overlay maps, denoise deltas, color-correction residuals), from 4 rounds of real failure ([Low-Signal Residual Training](principles/12-low-signal-residual-training.md))
- **Deep research results evaporate with the conversation?** Save structured findings to an incoming folder -> review -> knowledge base pipeline ([Research Pipeline](principles/13-research-pipeline.md))
- **Need a human-browsable memory view without a second source of truth?** Use an optional Obsidian-compatible Markdown hub over the private archive ([Obsidian Mind adoption note](docs/research/obsidian-mind-adoption-2026-07-28.md))
- **Building a brand-new agent and not sure what to decide first?** 15-section MVP blueprint: autonomy level -> tool risk classes -> permission matrix -> budgets -> evals -> release checklist ([MVP Agent Blueprint](principles/29-mvp-agent-blueprint.md))

**Need smaller diagnostic command output?** The optional RTK integration is
pinned, checksum-verified, fail-open, and tested separately from safety hooks.
See [docs/rtk-integration.md](docs/rtk-integration.md) and
`scripts/rtk_integration.py`; it is never a substitute for raw evidence.

**Ready-to-use hooks** that enforce rules mechanically, not probabilistically (install via [scripts/install_hooks.py](scripts/install_hooks.py); full map with bypass keys in [rules/safety-hooks.md](rules/safety-hooks.md)):

| Hook | Event | What It Does |
|---|---|---|
| [session-drift-validator](hooks/session-drift-validator.py) | `SessionStart` | Validates file references in CLAUDE.md at session start |
| [destructive-command-guard](hooks/destructive-command-guard.py) | `PreToolUse` | Blocks `rm -rf`, `git push --force`, `DROP TABLE` |
| [secret-leak-guard](hooks/secret-leak-guard.py) | `PreToolUse` | Prevents committing API keys, tokens, passwords |
| [session-handoff-reminder](hooks/session-handoff-reminder.py) | `Stop` | Reminds to write handoff before closing long sessions |
| [session-handoff-check](hooks/session-handoff-check.py) | `SessionStart` | Shows recent handoffs from previous sessions (latest per project) |
| [handoff-closure-audit-guard](hooks/handoff-closure-audit-guard.py) | `PreToolUse` | Blocks handoff writes that lack a closure audit for the primary task and related/scope-adjacent tasks |
| [stop-phrase-guard](hooks/stop-phrase-guard.py) | `Stop` | Detects behavioral-regression phrases (ownership dodging, permission-seeking, premature stopping, deferral-via-"what next?") |
| [keyword-skill-router](hooks/keyword-skill-router.py) | `UserPromptSubmit` | Detects natural-language keywords and suggests matching skills (bilingual RU/EN) |
| [api-key-leak-detector](hooks/api-key-leak-detector.py) | `PostToolUse` | Scans tool output for exposed API keys, tokens, secrets |
| [command-injection-guard](hooks/command-injection-guard.py) | `PreToolUse` | Blocks shell substitution with non-trivial commands |
| [git-destructive-guard](hooks/git-destructive-guard.py) | `PreToolUse` | Blocks `git reset --hard`, `push --force`, `branch -D` |
| [git-auto-backup](hooks/git-auto-backup.py) | `PreToolUse` | Creates backup branch before destructive git operations |
| [self-harm-guard](hooks/self-harm-guard.py) | `PreToolUse` | Prevents agent from killing its own process, locking SSH, bare reboot |
| [test-muting-guard](hooks/test-muting-guard.py) | `PreToolUse` | Blocks adding `@skip`, `.only()`, `@Ignore` to existing tests |
| [backup-retention-cleanup](hooks/backup-retention-cleanup.py) | `Stop` | Cleans up old backup branches (14-day retention) |
| [file-cohesion-guard](hooks/file-cohesion-guard.py) | `PreToolUse` | Advisory: warns when a durable file is written to a scratch location (home root, Desktop, Downloads, /tmp) instead of the project structure |
| [human-confirmation-guard](hooks/human-confirmation-guard.py) | `PreToolUse` | Requires explicit user confirmation before any deletion-intent command |
| [ask-question-guard](hooks/ask-question-guard.py) | `PreToolUse` | Blocks deferral/menu `AskUserQuestion` ("what next?", "which of these?") on reversible work — decide and proceed instead |
| [over-engineering-advisor](hooks/over-engineering-advisor.py) | `PostToolUse` | Advisory nudge when an edit adds a large code block or a new dependency — "is this the minimal solution?" (never blocks) |
| [activity-journal-guard](hooks/activity-journal-guard.py) | `PreToolUse` | Enforces the shared activity journal — blocks a mutating command on a tracked shared resource that does not log to its journal |
| [coord-claim-guard](hooks/coord-claim-guard.py) | `PreToolUse` | Claim-before-edit gate for multi-session / coord-enabled repos (blocks editing a file without an active claim) |
| [continuity-contract-guard](hooks/continuity-contract-guard.py) | `PreToolUse` | Protects Claude/Codex continuation: no silent whole-file Write, out-of-scope edits, or near-whole-file replacement |
| [continuity-session-check](hooks/continuity-session-check.py) | `SessionStart` | Surfaces the shared `.claude/continuity/CONTINUITY.json` contract and its preserve/do-not-redo decisions |
| [cyrillic-bash-guard](hooks/cyrillic-bash-guard.py) | `PreToolUse` | Blocks raw non-ASCII (Cyrillic/CJK) in Windows Bash commands — encoding-corruption guard |
| [feature-list-validator](hooks/feature-list-validator.py) | `Stop` | Validates feature_list.json discipline (WIP=1; `done` needs evidence) — companion to problems-md-validator |
| [handoff-resume-gate](hooks/handoff-resume-gate.py) | `SessionStart` | Resume freshness-gate — complements session-handoff-check by gating on stale/unacknowledged handoffs |
| [long-run-detector](hooks/long-run-detector.py) | `SessionStart` | Auto-detects a long-running project and nudges adopting the [LONG-RUN] harness (feature_list.json / init.sh) |
| [verify-deleted-guard](hooks/verify-deleted-guard.py) | `PostToolUse` | Verifies a destructive operation actually completed (object really gone) |
| [db-snapshot-guard](hooks/db-snapshot-guard.py) | `PreToolUse` | Auto-snapshots the database before bypassed destructive SQL |
| [claude-attribution-guard](hooks/claude-attribution-guard.py) | `PreToolUse` | Blocks commits/PRs carrying `Co-Authored-By: Claude` footers (see [rules/no-claude-attribution.md](rules/no-claude-attribution.md)) |
| [pre-push-claude-attribution](hooks/pre-push-claude-attribution.py) | git `pre-push` | Final attribution gate before commits reach the remote |
| [precompact-handoff-guard](hooks/precompact-handoff-guard.py) | `PreCompact` | Demands a fresh handoff before context compaction; writes an AUTO-DRAFT fallback if none exists |
| [test-gate-stop-hook](hooks/test-gate-stop-hook.py) | `Stop` | Blocks closing a session while tests are red |
| [problems-md-validator](hooks/problems-md-validator.py) | `Stop` | Blocks closing with OPEN problems lacking a valid deferral reason |
| [task-inbox-show](hooks/task-inbox-show.py) | `SessionStart` | Surfaces pending tasks from `.claude/task-inbox/` |
| [plan-gate](hooks/plan-gate.py) | `UserPromptSubmit` | Non-blocking nudge: substantive build/refactor ask + no plan artifact in the project -> one-line "freeze acceptance criteria first" reminder (max once/day) |

**Supporting hooks and shared utilities** (wire these when the project needs the corresponding workflow):

| Hook | Event | What It Does |
|---|---|---|
| [conversation-history-capture](hooks/conversation-history-capture.py) | `Stop` | Archives the local session transcript for searchable continuation |
| [directory-creation-guard](hooks/directory-creation-guard.py) | `PreToolUse` | Applies lifecycle labels and placement checks to new directories |
| [docs-staleness-guard](hooks/docs-staleness-guard.py) | `SessionStart` | Surfaces stale project guidance before work begins |
| [feedback-pending-show](hooks/feedback-pending-show.py) | `SessionStart` | Shows queued corrections waiting for review |
| [git-source-gate](hooks/git-source-gate.py) | `Stop` | Checks that durable work is represented in Git before closure |
| [github-workflow-security](hooks/github-workflow-security.py) | `PreToolUse` | Adds a security checklist before editing GitHub Actions workflows |
| [kb-validate-gate](hooks/kb-validate-gate.py) | `Stop` | Runs the project knowledge-base validator when opted in |
| [session-feedback-capture](hooks/session-feedback-capture.py) | `Stop` | Queues durable correction notes without blocking session closure |
| [safety_common.py](hooks/safety_common.py) | shared | Shared event parsing and decision helpers for opt-in hooks |
**Starter templates** for common project types: [web-app](templates/CLAUDE-web-app.md), [ML project](templates/CLAUDE-ml-project.md), [library](templates/CLAUDE-library.md), [code review](templates/REVIEW.md), [project chronicle](templates/chronicle.md), [memory files](templates/memory-project.md), [memory reference](templates/memory-reference.md), [proof plan](templates/proof-plan.md), [bug-fix prompt](templates/bug-fix-prompt.md) (anti-"pre-existing" constraints baked in), [long-run project harness pack](templates/long-run-project/) (drop-in `feature_list.schema.json` + `feature_list.template.json` + `init.sh.template` for any project crossing 5+ features and 5+ sessions).

**Dynamic workflow commands** ([workflows/](workflows/)) - ready-to-drop `.js` orchestration scripts for Claude Code dynamic workflows (`/deep-review-flow`, `/research-cn-ru`) plus [EFFECTIVE-AGENTS.md](workflows/EFFECTIVE-AGENTS.md) - measured cost lessons (one `agent()` ≈ 95-150k tokens; resume as the main economy lever).

**Cross-harness setup** ([rules/cross-harness-agents-md.md](rules/cross-harness-agents-md.md)) - share one `AGENTS.md` per project between Claude Code, Gemini CLI, and Codex without symlinks: Claude imports it via `@AGENTS.md`, Gemini reads it via `context.fileName`, Codex natively. Companion skill [gemini-delegate](skills/operational/gemini-delegate/SKILL.md) covers multi-account Gemini CLI delegation (quota ladders, account switcher [scripts/gemini-switch.sh](scripts/gemini-switch.sh), trust boundaries).

For serial Claude/Codex handoff, use the [cross-harness-continuation](skills/operational/cross-harness-continuation/) contract. It records the Git baseline, claimed files, accepted decisions, rejected approaches, and verification. The guard blocks silent rewrites and scope drift; an intentional redesign must use an explicit, reasoned `replan` mode.

**Your agent picks the approach that fits.** The [alternatives/](alternatives/) directory compares 2-5 approaches for each problem, with pros, cons, and "when to choose" guidance:

| Problem | Approaches Compared |
|---|---|
| [Multi-step orchestration](alternatives/orchestration.md) | Harness Design, Proof Loop, Deterministic Orchestration, Prompt-only |
| [Code review](alternatives/code-review.md) | Sequential checklist, Parallel competency, Cross-model, LLM + static |
| [Iterative optimization](alternatives/optimization.md) | Autoresearch, HyperAgent, Manual, Eval-driven |
| [Codebase scoping before changes](alternatives/codebase-map-scoping.md) | Belief Map / Code Graph, Symbol Index / LSP, Targeted `rg`, Full Context Upfront |
| [Context in long sessions](alternatives/context-management.md) | JIT Loading, Full Context Upfront, Compaction, Fresh Sessions |
| [Session transitions](alternatives/session-handoff.md) | Manual HANDOFF.md, Auto hooks, Session Journal, ContextHarness, Memory |
| [Reasoning-quality regression](alternatives/reasoning-regression-debugging.md) | Config reset, Stop-phrase guard, Metric monitoring, Fresh-session A/B, Proof Loop |

---

## Long-Run Project Harness (new in v3.17/v3.18)

If you have a project that crosses 5+ features and 5+ sessions of work, three drop-in artifacts close the gap that PROBLEMS.md + handoffs + chronicles alone leave open:

| Artifact | Question it answers | Where |
|---|---|---|
| `init.sh` | Is the project healthy right now? (binary check, <3 min target) | [templates/long-run-project/init.sh.template](templates/long-run-project/init.sh.template) |
| `feature_list.json` | What features exist and what state are they in? (machine-readable) | [templates/long-run-project/feature_list.schema.json](templates/long-run-project/feature_list.schema.json) + [.template.json](templates/long-run-project/feature_list.template.json) |
| `PROBLEMS.md` | What is broken right now? Recovery procedures? | Already covered in [rules](rules/) — pairs with the two above |

Hard rules attached to this pack:

- **WIP=1**: at most one feature in `status: "in-progress"` at any time
- **L1+L2+L3 evidence**: `status: "done"` requires `evidence` field referencing Syntax/Static + Runtime + System artifacts (durable files, not "tests pass" claims)
- **`done` is one-way**: regression becomes a new feature, never roll back
- **Durable source and docs**: creating `feature_list.json` opts the project into the Stop gates for a Git worktree with `origin` plus an agent-facing KB that stays current. Scratch folders remain outside this boundary.

**To audit whether your project needs this pack — and which subsystem to fix first — invoke the new [`harness-audit`](skills/operational/harness-audit/) skill:**

```
/harness-audit
```

or trigger phrases like *"audit my harness"*, *"score my CLAUDE.md"*, *"is my project ready for long-run"*. The skill produces a 5-subsystem scorecard (1-5 per dimension), identifies the bottleneck, and outputs a prioritized 3-step improvement plan with effort estimates and pointers to the templates above. Read-only — no changes applied unless you approve.

See [principle 27 - Feature Tracking](principles/27-feature-tracking.md) for the full framework. Templates and concepts adapted from [walkinglabs/learn-harness-engineering](https://github.com/walkinglabs/learn-harness-engineering) (MIT license), integrated with our existing Proof Loop, Multi-Agent Decomposition, and No-Pre-Existing Evasion principles.

---

## How This Works

**For the agent (you):** When this repo is connected to your project, you get access to all principles and skills automatically. Use them as decision frameworks - when facing a choice (one agent vs many? how to verify? how to manage context?), check the relevant principle or alternative comparison.

**New:** [HOW-IT-WORKS.md](HOW-IT-WORKS.md) - technical deep dive into how each technology actually works, with real measurements.

**Structure:**
- `principles/` - standalone architectural principles. Read the one that matches your current problem.
- `rules/` - drop-in `.claude/rules/` files: always-on working discipline (no-guessing, finish-the-task, deletion-confirm, autonomy-risk-tiers, quality-code) plus a consolidated safety-hooks reference. Agent-harness design rules (tool risk taxonomy, budgets, evals, observability, trust labels) now live on-demand in the `agent-harness-design` skill.
- `alternatives/` - side-by-side comparisons of 2-5 approaches per problem. Pick the approach that fits.
- `hooks/` - ready-to-use Python hook scripts for safety guards, session management, and discipline enforcement. Wire them with `scripts/install_hooks.py`.
- `workflows/` - drop-in dynamic-workflow commands (`/deep-review-flow`, `/research-cn-ru`) + measured cost lessons.
- `templates/` - starter CLAUDE.md and REVIEW.md files for different project types, plus the kb-skeleton and long-run-project scaffolding packs.
- `skills/` - domain skills (AI/ML, frontend, iOS, code review, video, writing, operational tooling). Loaded on demand; the generated list is in [skills/README.md](skills/README.md).
- `scripts/` - utilities: hook installer, config validator, cross-reference checker, KV-cache stats, skills-lock generator, public-repo sync with privacy scanner, Gemini account switcher.
- `skills-lock.json` - reproducible lockfile with content hashes of every skill (regenerate via `scripts/generate_skills_lock.py`).
- `CLAUDE.md` - compact summary of all principles for global config.

---

## Principles by Maturity Level

Start with L1 for any project. Add L2 when tasks repeat and optimization matters. L3 only when solo agent is not enough.

| Level | Focus | Principles |
|---|---|---|
| **L1: Foundational** | Single agent, planning, tool use | Deterministic Orchestration, Structured Reasoning, Skills Best Practices, DBS Skill Creation |
| **L2: Self-Evolving** | Feedback loops, memory, optimization | Autoresearch, Codified Context, Proof Loop |
| **L3: Collective** | Multi-agent coordination | Harness Design, Multi-Agent Decomposition, Managed Agents, MVP Agent Blueprint |
| **Cross-cutting** | Security + Integrity | Supply Chain Defense, Agent Security, Documentation Integrity, Red Lines |
| **Cross-cutting** | Session + Project Continuity | Codified Context, Project Chronicles, Research Pipeline |

Based on three-level agentic reasoning taxonomy (arxiv 2601.12538, 2504.19678).

---

## Security Hardening

Two principles specifically address agent security:

**Supply Chain Defense** - most poisoned npm/PyPI packages are caught within 1-3 days. Two config lines create a 7-day buffer:
```ini
# ~/.npmrc
min-release-age=7
```
```toml
# ~/.config/uv/uv.toml
exclude-newer = "7 days"
```

**Agent Security** - covers 7 real attack categories with documented CVEs: in-code prompt injection, repo metadata poisoning, package metadata, MCP tool poisoning, web content injection, memory poisoning, sandbox escape. Includes a six-layer defense architecture.

---

## Session Handoff - Moving Between Chats

When a Claude Code session gets long, or you want to continue tomorrow on a different machine, or your current chat predates any automation you've set up - just tell the agent to prepare a handoff.

**Type one of these phrases and hit Enter:**

- `prepare handoff`
- `save context for new chat`
- `write handoff`
- `handoff this session`

The agent writes a handoff file with:
- What was the goal
- What got done
- **What did NOT work** (the most valuable part - prevents repeating dead ends)
- Current state (working / broken / blocked)
- Key decisions and why
- The single next step

Then it stops. Close the chat. Open a new one in the same directory. The new session reads the handoff automatically (if you set up the `SessionStart` hook) or you can paste the file as your first message.

**Two storage modes - pick one:**

| Mode | When to use | Storage |
|---|---|---|
| **Single-file** (default, simpler) | One chat at a time | `.claude/HANDOFF.md` |
| **Multi-session** (opt-in) | You run multiple Claude Code chats simultaneously on the same project | `.claude/handoffs/<unique>.md` + append-only `INDEX.md` |

Single-file works for ~80% of users. Switch to multi-session only if you've actually hit last-writer-wins data loss from parallel chats. See [rule file](rules/session-handoff.md) for both protocols and [principle 18](principles/18-multi-session-coordination.md) for the theory behind the multi-session append-only invariant.

**Why a phrase and not a button:** the trigger lives in `.claude/rules/session-handoff.md` as plain markdown. No plugin install, no settings file, no hook. Works in any Claude Code session immediately. This is essential for migrating *existing* sessions that were started before you configured anything.

Copy the ready-made rule file from [rules/session-handoff.md](rules/session-handoff.md) into your project's `.claude/rules/` (or `~/.claude/rules/` for global) and you're done.

**For automation nerds:** pair this with a `Stop` hook that blocks long-session closure until a handoff is written. See [alternatives/session-handoff.md](alternatives/session-handoff.md) for all 5 approaches compared.

**If you run parallel chats and they need to talk to each other** (not just leave state), see [principle 19 - Inter-Agent Communication](principles/19-inter-agent-communication.md). Mini decision tree:

```
Broadcast "I'm done, anyone continue"       → handoff (principle 18)
Claim exclusive resource                    → lock file (principle 18)
Ask a specific other session to do X        → mailbox/<name>/ (principle 19)
Announce a decision for all running chats   → mailbox/all/ (principle 19)
Multi-turn reply chain                      → mailbox with in_reply_to threading
```

---

## Skills Catalog

Skills are practical tools for specific domains. The complete list is generated
from live `SKILL.md` frontmatter, so it cannot silently fall behind the source:
[skills/README.md](skills/README.md). Verify it with:

```bash
python scripts/generate_skills_catalog.py --check
python scripts/generate_skills_lock.py --check
```

---

## Complementary Tools

These work well alongside the principles:

- **[gstack](https://github.com/nichochar/gstack)** - dev workflow skills: /review, /qa, /ship, /investigate, /design-review
- **[hookify](https://github.com/AstroMined/hookify)** - git hooks generator for Claude Code
- **[Semgrep](https://semgrep.dev/)** - static analysis, pairs with deep-review
- **[task-orchestrator](https://github.com/jpicklyk/task-orchestrator)** - MCP task orchestration with dependency ordering

---

## This Repo Is Updated Regularly

Principles are updated with new research findings, real-world incidents, and community patterns. Security sections track actual CVEs and attack chains. See [UPDATES.md](UPDATES.md) for the full changelog.

Freshness is mechanical, not aspirational: [scripts/sync_public_config.py](scripts/sync_public_config.py) + [sync-manifest.json](sync-manifest.json) run a manifest-driven one-way sync from the author's live `~/.claude` into this repo - EOL-normalized diffing, an explicit deny-list for machine-specific files, and a privacy-marker scanner that blocks anything private from reaching the public tree (`--scan-repo --strict` runs before every push). If you maintain your own private-config/public-fork split, the same script works for you - edit the manifest.

---

## Contributing

1. Fork the repo
2. Add/improve a skill (`skills/<category>/<name>/SKILL.md`) or principle (`principles/`)
3. Skill descriptions = triggers for the model, not human summaries. Include `## Gotchas` from real failures
4. For principles or alternatives: open an issue first

---

---

## 中文简介

面向 Claude Code 智能体的实战配置系统，包含架构原则、方案对比、技能、Hook 脚本、drop-in 规则和项目模板。

**核心功能:**
- `principles/` - 独立架构原则，每个解决一个具体失败模式
- `rules/` - drop-in 规则（工作纪律、安全 Hook 配套文档；Agent 设计规则已移至 `agent-harness-design` 技能）
- `alternatives/` - 每个问题 2-5 种方案对比，附决策表
- `hooks/` - 即用型 Hook 脚本（安全防护、会话管理、技能路由），用 `scripts/install_hooks.py` 一键注册
- `workflows/` - 动态工作流命令（`/deep-review-flow`、`/research-cn-ru`）+ 实测成本经验
- `templates/` - 适用于不同项目类型的 CLAUDE.md 起始模板 + 验证计划、记忆、项目编年史和长期项目脚手架（feature_list.json + init.sh）
- `skills/` - 领域技能（AI/ML、视频制作、前端、iOS、写作、代码审查、验证、运维工具，包括 `harness-audit` 五子系统评估、`workflow-orchestration` 和 `gemini-delegate` 跨 CLI 委派）
- 跨 harness 支持：每个项目一个 `AGENTS.md`，同时供 Claude Code、Gemini CLI、Codex 读取（无需符号链接），见 `rules/cross-harness-agents-md.md`

**安装:** `claude plugin install https://github.com/AnastasiyaW/claude-code-config` 或直接复制所需文件。

**灵感来源:** 部分设计理念受到中国工程社区的启发，包括红线(红线)模式、规范驱动开发(OpenSpec)、经验库模式。

---

## Описание на русском

Система конфигурации для Claude Code агентов: архитектурные принципы, сравнения подходов, навыки, hook-скрипты, drop-in правила и шаблоны проектов.

**Что внутри:**
- `principles/` - принципы, каждый предотвращает конкретный тип отказа
- `rules/` - drop-in правила: рабочая дисциплина (no-guessing, finish-the-task, deletion-confirm, autonomy-risk-tiers, quality-code), консолидированный safety-hooks reference; правила проектирования агентов (risk taxonomy, budgets, evals, observability) теперь в скилле `agent-harness-design`
- `alternatives/` - сравнение 2-5 подходов для каждой проблемы с таблицей решений
- `hooks/` - готовые скрипты (safety guards, handoff, drift validator, keyword router, secret leak detection, backup retention, test/problems gates и др.), регистрация одной командой `scripts/install_hooks.py`
- `workflows/` - готовые dynamic-workflow команды (`/deep-review-flow`, `/research-cn-ru`) + замеры стоимости агентов
- `templates/` - стартовые CLAUDE.md + план верификации + шаблоны memory и хроник + **long-run harness pack** (drop-in `feature_list.json` + `init.sh` для проектов с 5+ фичами)
- `skills/` - доменные навыки (AI/ML, видео, фронтенд, iOS, письмо, код-ревью, верификация, операционные инструменты, включая `harness-audit`, `workflow-orchestration` и `gemini-delegate` — делегирование в Gemini CLI с мульти-аккаунтом)
- Кросс-harness: один `AGENTS.md` на проект читают Claude Code, Gemini CLI и Codex (без симлинков) — `rules/cross-harness-agents-md.md`

**Установка:** `claude plugin install https://github.com/AnastasiyaW/claude-code-config` или копирование нужных файлов.

---

## License

MIT
