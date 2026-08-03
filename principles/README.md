# Architectural Principles for AI Agent Systems

A collection of 30 battle-tested principles for building reliable, high-quality AI agent workflows. Each principle is self-contained and can be adopted independently, but they compose well together.

---

## Pick by project type

Start here if you are installing claude-code-config into a specific project. Each row is a sensible baseline; add more principles as you hit the problem they solve.

| Project type | Minimum | Recommended additions |
|---|---|---|
| **Solo developer, single project** | 04 Deterministic Orchestration, 07 Codified Context, 09 Supply Chain Defense | 11 Documentation Integrity, 13 Research Pipeline |
| **Web app (React, Vue, Next.js)** | 04, 05 Structured Reasoning, 09, 10 Agent Security | 08 Skills Best Practices, 11 Documentation Integrity |
| **ML / training / inference pipeline** | 03 Autoresearch, 04, 09, 12 Low-Signal Residual Training | 05, 13 Research Pipeline, 16 Project Chronicles |
| **Library / published package** | 04, 08 Skills Best Practices, 09, 10 | 11, 17 DBS Skill Creation |
| **New custom AI agent (any domain)** | 29 MVP Agent Blueprint, skills/agent-harness-design/references/agent-tool-design.md, skills/agent-harness-design/references/agent-budgets.md, skills/agent-harness-design/references/agent-evals.md, skills/agent-harness-design/references/agent-event-model.md | 01 Harness Design, 02 Proof Loop, 10 Agent Security, skills/agent-harness-design/references/agent-observability.md, skills/agent-harness-design/references/agent-plan-artifact.md, skills/agent-harness-design/references/agent-approval-records.md, skills/agent-harness-design/references/agent-streaming.md, skills/agent-harness-design/references/agent-skill-install-checklist.md |
| **Agent that ingests external content** | 10 Agent Security, rules/context-trust-labels.md | 29 MVP Agent Blueprint, 02 Proof Loop, skills/agent-harness-design/references/agent-evals.md |
| **Multi-agent / parallel sessions** | 01 Harness Design, 06 Multi-Agent Decomposition, 09, 18 Multi-Session Coordination, 19 Inter-Agent Communication | 02 Proof Loop, 14 Managed Agents, 22 Visual Context Pattern |
| **Long-running project (weeks+)** | 02 Proof Loop, 07 Codified Context, 16 Project Chronicles | 11 Documentation Integrity, 21 Knowledge Base Enforcement |
| **Security-sensitive codebase** | 09 Supply Chain Defense, 10 Agent Security, 15 Red Lines, 20 Vulnerability Detection Pipeline | 02 Proof Loop, 21 Knowledge Base Enforcement |

**Principles 09 (Supply Chain Defense) and 10 (Agent Security) apply universally** - install them even if your project type is not listed.

---

## Principles Overview

### [01 - Harness Design](01-harness-design.md)

Multi-agent architecture patterns for long-running AI applications. Separates generation from evaluation to overcome self-evaluation bias. Defines when a solo agent suffices and when the 20x cost of a full harness is justified.

**When to use:** Building any multi-step AI workflow where quality matters more than speed. Designing evaluation systems. Planning agent architectures.

**Source:** Anthropic Engineering -- "Harness design for long-running apps"

---

### [02 - Proof Loop](02-proof-loop.md)

A rigorous verification protocol where agents cannot self-certify completion. Requires durable artifacts (test outputs, logs, verdict files) as proof, verified by a fresh session that never saw the build process.

**When to use:** Any task where "it works on my machine" is not acceptable. Critical deployments. Tasks requiring audit trails. Multi-agent handoffs where trust boundaries matter.

**Source:** OpenClaw-RL paper (arxiv 2603.10165) + DenisSergeevitch/repo-task-proof-loop

---

### [03 - Autoresearch](03-autoresearch.md)

Iterative self-optimization through automated experimentation. Read one thing, change one thing, test mechanically, keep or discard, repeat. Scales from linear hill-climbing to branching version graphs with meta-optimization.

**When to use:** Improving any artifact with a measurable score -- prompts, skills, code coverage, latency, bundle size. NOT for subjective tasks without scriptable evaluation.

**Source:** Andrej Karpathy (github.com/karpathy/autoresearch) + HyperAgents paper [2603.19461]

---

### [04 - Deterministic Orchestration](04-deterministic-orchestration.md)

The principle that LLMs should never execute deterministic processes. Mechanical tasks (test, lint, format, detect) run as shell scripts; the LLM only handles creative/reasoning work. State lives in files, not in the agent's memory.

**When to use:** Any workflow with mechanical steps mixed with reasoning steps. Building skills with multi-step processes. Designing CI/CD-like agent pipelines.

**Source:** Deterministic orchestration patterns for AI coding agents

---

### [05 - Structured Reasoning](05-structured-reasoning.md)

Replaces free-form chain-of-thought with semi-formal reasoning: Premises, Execution Trace, Conclusions, Rejected Paths. Eliminates "planning hallucinations" where the model builds plausible but incorrect reasoning chains.

**When to use:** Debugging with non-obvious root causes. Architecture decisions with more than 2 options. Performance optimization. Security review. NOT needed for simple CRUD tasks.

**Source:** [2603.01896] Agentic Code Reasoning (Mar 2026)

---

### [06 - Multi-Agent Task Decomposition](06-multi-agent-decomposition.md)

Strategies for breaking complex tasks across multiple specialized agents. Defines when single-agent is sufficient (function-level) versus when multi-agent coordination is needed (system-level), and how to structure the coordinator.

**When to use:** Tasks touching more than 3 files. Cross-cutting concerns (security, performance, accessibility). System-level refactoring. Large feature implementations.

**Source:** [2603.14703] Multi-Agent System Optimization + [2603.13256] Training-Free Multi-Agent Coordination

---

### [07 - Codified Context](07-codified-context.md)

Treats project context as runtime infrastructure rather than documentation. CLAUDE.md is a runtime config, rules are conditional context injection, memory files are persistent state. Introduces JIT context loading to manage the context window efficiently.

**When to use:** Any project with AI agents. Setting up CLAUDE.md and memory systems. Managing context across long sessions. Designing handoff artifacts between agent sessions.

**Source:** [2602.20478] Codified Context: Infrastructure for AI Agents in a Complex Codebase

---

### [08 - Skills Best Practices](08-skills-best-practices.md)

Practical guide for creating reliable, discoverable Claude Code skills. Covers description-as-trigger design, mandatory sections (Gotchas, Troubleshooting), file structure conventions, and the principle that critical validations must be scripts, not prose.

**When to use:** Creating or updating any skill in `.claude/skills/`. Reviewing existing skills for quality. Designing skill libraries.

**Source:** Production experience across multiple Claude Code deployments

---

### [09 - Supply Chain Defense](09-supply-chain-defense.md)

Protect against malicious package updates by gating fresh packages. Set `min-release-age=7` (npm) and `exclude-newer = "7 days"` (uv) globally. Most poisoned packages are detected within 1-3 days; 7-day delay eliminates the attack window with near-zero friction.

**When to use:** Always. Every development machine, every CI runner. Override only for critical security patches that need immediate deployment.

**Source:** Industry practice in response to escalating open-source supply chain attacks (2024-2026)

---

### [10 - Agent Security](10-agent-security.md)

Comprehensive defense against prompt injection, tool poisoning, memory poisoning, sandbox escape, and data exfiltration targeting AI coding agents. Covers the full attack taxonomy with real CVEs, a six-layer defense architecture (content isolation, sandboxing, permissions, output filtering, MCP defenses, monitoring), and references to 16+ academic papers.

**When to use:** Always. Every AI agent deployment, every MCP server integration, every project that opens untrusted repositories. Designing agent permission models. Incident response for suspected agent compromise.

**Source:** OWASP Top 10 for LLM/Agentic Applications 2025-2026, CVE database, 16+ arxiv papers (2025-2026), industry research (HiddenLayer, Invariant Labs, Ona Security, Check Point, Trail of Bits)

---

### [11 - Documentation Integrity](11-documentation-integrity.md)

Validates documentation references at session start, not after failure. File paths, function names, and config values in CLAUDE.md and rules/ decay as the codebase evolves. A SessionStart hook runs a validator that catches drift before the agent acts on stale pointers.

**When to use:** Any project with CLAUDE.md or rules/ files that reference specific paths. Teams with multiple contributors. Projects where stale docs caused agent errors.

**Source:** Fiberplane drift-linter, Redis context rot patterns, Qt architecture-as-code

---

### [12 - Low-Signal Residual Training](12-low-signal-residual-training.md)

Patterns and traps for training ML models on subtle residual data (dodge & burn, frequency separation, retouching overlays). Documents 7 specific failure modes and solutions for training on low-signal targets where most pixels are near-zero.

**When to use:** Training LoRAs or models on edit residuals, overlay maps, or any target where signal is sparse and subtle. Image editing ML pipelines.

**Source:** Production LoRA training experiments on FLUX.2 Klein 9B

---

### [13 - Research Pipeline](13-research-pipeline.md)

After any research task, structured results go to a dedicated incoming folder - not just conversation history. Creates a persistent knowledge pipeline that feeds into the knowledge base, preventing repeat research.

**When to use:** After deep research sessions, security analyses, technology comparisons. Any structured analysis that produces reusable knowledge.

**Source:** Production workflow for a public knowledge base

---

### [14 - Managed Agents](14-managed-agents.md)

Infrastructure pattern for multi-agent systems: separate the brain (planning) from the hands (execution). Managed sub-agents get sandboxed environments with lazy provisioning. Covers Anthropic's Managed Agents API, Claude Code Agent Teams, and self-hosted alternatives.

**When to use:** Building multi-agent workflows. Deciding between managed vs self-hosted agent infrastructure. Designing brain/hands separation for complex tasks.

**Source:** Anthropic Engineering - "Managed Agents" (April 8, 2026), HiClaw/AgentScope (Alibaba)

---

### [15 - Red Lines (红线)](15-red-lines.md)

Absolute prohibitions that cannot be violated regardless of context. Separate from regular rules, higher priority, each anchored to a real incident. Enforcement hierarchy: hooks (mechanical) > rules (probabilistic) > nothing.

**When to use:** After any incident where an agent did something harmful with good intentions. Defining non-negotiable boundaries for your project. Choosing between rule-based and hook-based enforcement.

**Source:** Chinese engineering community (红线 pattern), OWASP ASI09

---

### [16 - Project Chronicles](16-project-chronicles.md)

A condensed timeline per long-running project that captures decisions, pivots, results, and dead ends. Sits between handoffs (tactical, session-scoped) and documentation (static). Each entry is 3-7 lines of strategic digest, not a handoff copy.

**When to use:** Any project spanning weeks/months with 3+ handoffs. Projects where multiple sessions contribute without a clear end date. When new sessions need to understand project history, not just "what's next."

**Source:** Production experience managing 10+ concurrent long-running projects with Claude Code

---

### [17 - DBS Skill Creation Framework](17-dbs-skill-creation.md)

Split skill content into Direction (logic, decision trees -> SKILL.md), Blueprints (templates, taxonomies -> references/), and Solutions (deterministic code -> scripts/). Prevents monolithic SKILL.md files where logic, data, and code are mixed.

**When to use:** Creating skills from research material. Structuring any complex skill with both reasoning and mechanical components.

**Source:** @hooeem's NotebookLM integration guide (April 2026)

---

### [18 - Multi-Session Coordination](18-multi-session-coordination.md)

Pattern for coordinating shared state between parallel Claude Code sessions in the same workspace. Distinguishes append-only shared state (handoffs - per-session files, conflict-free) from mutable shared state (GPU/port/container locks - require heartbeats and stale-reclaim with external verification). Fills an ecosystem gap: isolation solutions are well-covered, live resource coordination is not.

**When to use:** When multiple Claude Code chats run simultaneously on the same project and contend for the same resources (GPUs, ports, containers, exclusive write access). Not needed if you work one chat at a time.

**Source:** Distributed systems coordination primitives (Chubby, ZooKeeper) + Anthropic Agent Teams + claude_code_agent_farm + Issues anthropics/claude-code#19364 and #29217 as cautionary data

---

### [19 - Inter-Agent Communication](19-inter-agent-communication.md)

Directed asynchronous messaging between parallel Claude sessions using classical email semantics (inbox-per-recipient, threading via in-reply-to, sent folder as audit trail, delivery receipts, filter rules). Complements principle 18: where 18 covers shared-state ownership (nouns - who holds what), 19 covers directed messaging (verbs - who tells whom). Two coordination axes × two primitives: shared state can be broadcast (handoffs) or exclusive (locks); messages can be broadcast (`mailbox/all/`) or directed (`mailbox/<name>/`).

**When to use:** When one session needs to address a specific other session with a question, task, or architecture decision. Not needed for simple broadcast announcements (use handoffs) or for resource claims (use locks).

**Source:** 40+ years of SMTP/IMAP semantics, aydensmith/mclaude, a multi-agent production deployment with 3 named agent roles

---

### [20 - Vulnerability Detection Pipeline](20-vulnerability-detection-pipeline.md)

LLM-driven pipeline for discovering security vulnerabilities in source code. Combines the model's pattern-matching with deterministic SAST rules and triage gates so findings come with evidence, not just suspicion. Pattern: scan → score → cross-reference against known CVE taxonomies → file regression test.

**When to use:** Auditing an unfamiliar codebase. Pre-release security review. Investigating a reported CVE in a dependency. Routine "find what is there" scans on sensitive code.

**Source:** Claude-led vulnerability research experiments (Feb 2026), OWASP ASVS, internal security review practice

---

### [21 - Knowledge Base Enforcement](21-knowledge-base-enforcement.md)

Every accepted code-review finding gains three forms: a regression test (guards against recurrence), an invariant written to the knowledge base (teaches future sessions), and a cross-reference in the file(s) it constrains (discoverable at edit time). Missing any form loses a guarantee.

**When to use:** After any non-trivial code-review finding. When "we fixed this before" keeps happening. Building a KB that agents read before editing code in a specific area.

**Source:** Production workflow distilled from repeat-incident patterns

---

### [22 - Visual Context Pattern](22-visual-context-pattern.md)

Local HTTP server + HTML fragments + file-based event queue lets an agent present UI / design / diagram options to a human and read clicks back. Works across every agent runtime (Claude Code, Codex, Cursor, Gemini CLI) because it uses files, not MCP. Minimum viable implementation is ~100 lines.

**When to use:** Any decision where "would the user understand this better by seeing it than reading it?" is yes. UI mockup selection, spatial / architectural diagrams, visual comparisons. NOT for simple yes/no text decisions.

**Source:** Distilled from obra/superpowers visual-companion skill (2026-04)

---

### [28 - Feature-Layer Architecture](28-feature-layer-architecture.md)

Three-tier project knowledge model: Global KB (cross-project principles) -> Layer KB (per-project bounded concerns like security, data, ui) -> Feature narrative (ULTRAPACK-style task.md per feature). Adds the missing narrative artifact above kb-skeleton: where one feature's design rationale, plan, verification, and retrospective live together with hyperlinked cross-references to invariants and global principles.

**When to use:** Multi-month projects with 5+ active concerns. Codebases approaching 50K+ lines. Teams across timezones or sessions. Complements (not replaces) `feature_list.json` (machine state), `PROBLEMS.md` (incidents), and chronicles (strategy).

**Source:** ULTRAPACK (github.com/btseytlin/ultrapack) task.md pattern + this repo's kb-skeleton extension

---

### [23 - Anti-pattern as Config](23-anti-pattern-as-config.md)

Three-layer enforcement stack for preventing LLM regression to generic defaults: skill + reference file with explicit anti-patterns (layer 1), slash-commands wrapping common checks like `/audit` and `/polish` (layer 2), deterministic detector that runs without LLM and fails build on match (layer 3). Plus the anti-attractor procedure: name reflex → reject if listed → enumerate alternatives → justify pick.

**When to use:** Whenever outputs revert to a single known-bad default (Inter font, purple gradients, `SELECT *`, bare `except`, microservices for small apps, etc.). Frontend design, security review, SQL code, Dockerfiles, Python idioms, test quality.

**Source:** Distilled from pbakaus/impeccable (2026-04) + OWASP agent security research + internal harness-design practice

---

### [29 - MVP Agent Blueprint](29-mvp-agent-blueprint.md)

Structured 15-section flow for designing a brand-new agent from scratch in any domain. Covers domain intake, autonomy level selection (5 levels), core loop, tool registry with risk classes, permission matrix, planning mode, goal-like loop, context/memory/compaction, skills/connectors, prompt caching, observability, build order, and first release checklist. Complements principle 01 (Harness Design) which assumes an agent already exists.

**When to use:** When building a NEW agent for a specific domain (support, finance, ops, sales, research, any workflow automation) — not when improving an existing one. Use for new Agent SDK apps, custom Python orchestrators, new MCP servers, new Cloudflare Workers with tool calls. Pairs with the `skills/agent-harness-design/references/agent-tool-design.md`, `rules/context-trust-labels.md`, and `skills/agent-harness-design/references/agent-budgets.md` operational rules.

**Source:** Denis Sergeevitch -- "agents-best-practices" skill (MIT, https://github.com/DenisSergeevitch/agents-best-practices), `references/mvp-agent-blueprint.md`. Adapted to our stack with cross-references to principles 01, 07, 10, 21 and the three new operational rules.

---

### [30 - Gates That Cannot Bootstrap Themselves](30-gates-that-cannot-bootstrap.md)

A harness check that switches on only when its own artifact is already present protects every
project except the ones that never set it up — and because the check is *designed* to be silent
there, nothing ever reports the hole. Covers the three observed variants (an exemption for
"aggregation" directories, an `allow()` for repositories that have not adopted the tool, and a
freshness signal any merge can forge), the inverse failure of a trigger so broad it gets trained
away, and five rules for writing gates that speak when adoption is missing.

**When to use:** When adding any opt-in hook or validator; when auditing why a harness that
"is installed" never said anything; when a shared directory used by many sessions behaves as if
it had no supervision.

---

## Decision Matrix

Use this table to pick the right principle for your situation:

| Situation | Primary Principle | Supporting Principles |
|---|---|---|
| "Agent output quality is inconsistent" | 01 Harness Design | 02 Proof Loop |
| "How do I verify the agent actually did it?" | 02 Proof Loop | 04 Deterministic Orchestration |
| "I want to improve my prompt/skill automatically" | 03 Autoresearch | 02 Proof Loop (final verification) |
| "Agent keeps forgetting steps in a process" | 04 Deterministic Orchestration | 07 Codified Context |
| "Debugging is going in circles" | 05 Structured Reasoning | 04 Deterministic Orchestration |
| "Task is too big for one agent" | 06 Multi-Agent Decomposition | 01 Harness Design |
| "Agent loses context between sessions" | 07 Codified Context | 04 Deterministic Orchestration |
| "My skills are hard to discover/maintain" | 08 Skills Best Practices | 07 Codified Context |
| "Solo agent works but quality plateaus" | 01 Harness Design | 03 Autoresearch |
| "Need audit trail for compliance" | 02 Proof Loop | 05 Structured Reasoning |
| "Multi-file refactoring keeps breaking things" | 06 Multi-Agent Decomposition | 02 Proof Loop |
| "Agent invents false claims about completion" | 02 Proof Loop | 04 Deterministic Orchestration |
| "Worried about malicious dependency updates" | 09 Supply Chain Defense | 04 Deterministic Orchestration |
| "Agent might be reading poisoned content" | 10 Agent Security | 02 Proof Loop |
| "Opening untrusted repos with AI agent" | 10 Agent Security | 09 Supply Chain Defense |
| "MCP server might be malicious" | 10 Agent Security | 04 Deterministic Orchestration |
| "Agent disabled its own security controls" | 10 Agent Security | 04 Deterministic Orchestration |
| "Multi-agent system needs trust boundaries" | 10 Agent Security | 06 Multi-Agent Decomposition |
| "Agent followed stale docs and broke things" | 11 Documentation Integrity | 07 Codified Context |
| "Training on subtle edit residuals fails" | 12 Low-Signal Residual Training | 03 Autoresearch |
| "Keep re-researching the same topics" | 13 Research Pipeline | 07 Codified Context |
| "Multi-agent infra is too complex" | 14 Managed Agents | 06 Multi-Agent Decomposition |
| "Agent cut corners on a critical rule" | 15 Red Lines | 04 Deterministic Orchestration |
| "Long-running project lost its history" | 16 Project Chronicles | 07 Codified Context |
| "Can't understand why past decisions were made" | 16 Project Chronicles | 05 Structured Reasoning |
| "Need absolute prohibitions, not guidelines" | 15 Red Lines | 10 Agent Security |
| "Skill is a monolithic wall of text" | 17 DBS Skill Creation | 08 Skills Best Practices |
| "Parallel chats overwrite each other's handoffs" | 18 Multi-Session Coordination | 07 Codified Context |
| "Multiple sessions fight over the same GPU/port" | 18 Multi-Session Coordination | 04 Deterministic Orchestration |
| "One chat needs to ask another a specific question" | 19 Inter-Agent Communication | 18 Multi-Session Coordination |
| "Need to broadcast an architectural decision to all running sessions" | 19 Inter-Agent Communication | 07 Codified Context |
| "Sender wants to know if recipient actually processed the message" | 19 Inter-Agent Communication | 02 Proof Loop |
| "Looking for zero-day vulnerabilities in an unfamiliar codebase" | 20 Vulnerability Detection Pipeline | 10 Agent Security |
| "Same code-review findings keep getting rediscovered" | 21 Knowledge Base Enforcement | 07 Codified Context |
| "Need the user to choose between UI or design options" | 22 Visual Context Pattern | 01 Harness Design |
| "Agent output keeps defaulting to Inter / SELECT * / bare except" | 23 Anti-pattern as Config | 04 Deterministic Orchestration |
| "Cloud design tool vs terminal-first design workflow?" | 22 Visual Context Pattern | alternatives/design-md-pattern.md |
| "Need to design a brand-new agent from scratch" | 29 MVP Agent Blueprint | 01 Harness Design, 10 Agent Security |
| "What tool risk classes / permission decisions should I model?" | 29 MVP Agent Blueprint | skills/agent-harness-design/references/agent-tool-design.md |
| "External webhook content might inject instructions" | rules/context-trust-labels.md | 10 Agent Security |
| "Agent loop has no budget and runs away" | skills/agent-harness-design/references/agent-budgets.md | 29 MVP Agent Blueprint |
| "What test cases must my agent pass before launch?" | skills/agent-harness-design/references/agent-evals.md | 02 Proof Loop, 21 KB Enforcement |
| "How do I trace and debug agent behavior in production?" | skills/agent-harness-design/references/agent-observability.md | skills/agent-harness-design/references/agent-evals.md |
| "How should plans for risky actions be structured?" | skills/agent-harness-design/references/agent-plan-artifact.md | skills/agent-harness-design/references/agent-approval-records.md |
| "How do I record approvals so they're audit-able and scope-bounded?" | skills/agent-harness-design/references/agent-approval-records.md | skills/agent-harness-design/references/agent-plan-artifact.md |
| "Implementing streaming tool calls without partial execution bugs" | skills/agent-harness-design/references/agent-streaming.md | skills/agent-harness-design/references/agent-tool-design.md |
| "Should I use Anthropic Managed Agents or build my own harness?" | 14 Managed Agents | 01 Harness Design, 29 MVP Agent Blueprint |
| "How to persist agent state for replay / audit / compaction?" | skills/agent-harness-design/references/agent-event-model.md | skills/agent-harness-design/references/agent-observability.md |
| "Installing a 3rd-party skill — what should I verify first?" | skills/agent-harness-design/references/agent-skill-install-checklist.md | 09 Supply Chain Defense, 10 Agent Security |
| "MCP server has 50+ tools and burns context on every call" | skills/agent-harness-design/references/agent-tool-design.md section 9 (connector code-exec) | skills/agent-harness-design/references/agent-tool-design.md section 6 (deferred loading) |

### Composition Patterns

These principles are designed to layer:

1. **Optimization + Verification:** Use Autoresearch (03) for iterative improvement, then Proof Loop (02) for final sign-off.
2. **Decomposition + Evaluation:** Use Multi-Agent Decomposition (06) to split the work, Harness Design (01) to evaluate each piece.
3. **Context + Orchestration:** Use Codified Context (07) for state management, Deterministic Orchestration (04) for process control.
4. **Reasoning + Verification:** Use Structured Reasoning (05) to analyze, Proof Loop (02) to prove the analysis is correct.
5. **Security + Supply Chain:** Use Agent Security (10) for runtime defense against injection, Supply Chain Defense (09) for dependency-level protection. Together they cover both code-level and package-level attack vectors.
6. **Security + Proof Loop:** Use Agent Security (10) to prevent injection during build, Proof Loop (02) with fresh-session verification to catch any injection that persisted.
7. **Visual + Anti-pattern:** Use Visual Context Pattern (22) to show design options in a browser, Anti-pattern as Config (23) to keep those options from sliding back to generic defaults (Inter, purple gradients, etc.).
8. **KB Enforcement + Proof Loop:** Use Knowledge Base Enforcement (21) to capture review findings as tests + invariants + cross-refs, Proof Loop (02) to verify the regression test actually protects against recurrence.
9. **Vulnerability Pipeline + Red Lines:** Use Vulnerability Detection Pipeline (20) to find issues, Red Lines (15) to codify the non-negotiable ones that must never regress.
