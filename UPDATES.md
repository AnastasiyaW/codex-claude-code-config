# Updates

Changelog for claude-code-skills. Newest first.

---

## 2026-07-31 (v3.34.0 - skill-tree recovery after a machine/account move)

- Added `scripts/recover_skill_trees.py`: diagnoses and repairs skill trees that
  a machine or account move left half-copied. Union fill — a directory that
  already carries a `SKILL.md` is authoritative and is never overwritten, so the
  run is idempotent; nothing is deleted.
- Added [docs/skill-tree-recovery.md](docs/skill-tree-recovery.md) describing the
  four ways a skill disappears without any error being raised: a dangling
  cross-profile junction/symlink, an empty directory shell, a UTF-8 BOM before
  the opening `---`, and a stale copy that lost its `name:` field.
- The dangling-link case also breaks the *diagnosis*: `iterdir() + is_dir()`
  follows the link, gets `False`, and drops the entry, so a tree of 107 dead
  junctions reported "no problems". The script enumerates raw directory entries
  and classifies non-resolving ones as `BROKEN_LINK`, printing where each pointed.
- Documented how to merge two live trees that were edited independently: resolve
  per file on evidence, because neither side is automatically newer, and never
  propagate a line where a skill references its own `scripts/` directory.
- Wired the check into [docs/runtime-wiring.md](docs/runtime-wiring.md) as a
  runtime-contract row, and added the `обвязка` / `wiring` / `account-migration`
  keywords. (GitHub topics reject non-ASCII, so the repo carries `harness`,
  `agent-harness` and `wiring` there instead.)

## 2026-07-22 (v3.33.0 - grounded NotebookLM research)

- Added `skills/ai-ml/notebooklm-grounded-research` for large stable
  documentation, courses, books, and papers with citation-preserving answers.
- Added a keyword route for NotebookLM without making the optional browser
  bridge mandatory for unrelated research.
- Pinned the documented integration to `notebooklm-mcp@2.0.0` with the Codex
  `minimal` profile (5 tools), and added a read-only setup verifier.
- Added explicit trust, privacy, source-ingestion, and authentication bounds:
  the bridge is community browser automation, not an official API; live code,
  official docs, and tests remain authoritative.
- Verified the route, skill lint, lock/catalog, lifecycle contracts, pinned
  package age, stdio startup, and `tools/list` with the minimal profile.

## 2026-06-28 (v3.32.0 — skill description discipline + skill-lint)

Applied the Google *Agent Skills* whitepaper (May 2026) description discipline to the whole skill
library, and shipped the checker that enforces it.

- NEW [`scripts/skill_lint.py`](scripts/skill_lint.py) — deterministic SKILL.md smell checker (shift-left,
  advisory): flags a missing/`vague` description, a missing **"when NOT to use"** boundary, a missing
  positive trigger, a missing/non-kebab `name`, an over-budget body (>5000 words), and the
  "references-nothing" smell. Code-aware (skips fenced/inline code). Run:
  `python scripts/skill_lint.py skills`.
- [`skills/development/proof-verify`](skills/development/proof-verify/SKILL.md) had **no YAML
  frontmatter at all** (so the model couldn't route to it) — added `name` + a full what/when/when-not
  description.
- **Added a tailored "when NOT to use" boundary to 30 skills** — each names the actual adjacent
  sibling skill for routing disambiguation (e.g. `flux2-klein-prompting` ↔ `flux2-lora-training`,
  `humanize-english` ↔ `humanize-russian`, the video-production pipeline stages), not generic filler.
- Fixed 3 Title-Case `name:` fields to kebab and added the missing `name:` to 5 video-production skills.
- Result: **`skill_lint.py` reports 31/31 skills clean, 0 findings.** Evidence: the linter was itself
  independently re-tested (a YAML folded-scalar parse bug and a regex gap were found and fixed before
  trusting its output).

---

## 2026-06-28 (v3.31.0 — learn-from-corrections loop)

The agent should learn a lesson every time the user corrects it (the most-missed lever of
self-improving agents). This release closes that loop with an **evidence-driven** design.

- NEW [`hooks/session-feedback-capture.py`](hooks/session-feedback-capture.py) (`Stop`) — queues
  finished sessions with real back-and-forth into `~/.claude/feedback/queue.jsonl`. Non-blocking,
  deterministic, opt-out via `CLAUDE_SKIP_FEEDBACK_CAPTURE=1`.
- NEW [`hooks/feedback-pending-show.py`](hooks/feedback-pending-show.py) (`SessionStart`) — surfaces
  the pending count so the loop closes; silent when empty, self-clearing.
- NEW skill [`skills/development/distill-feedback/`](skills/development/distill-feedback/SKILL.md) —
  `/distill-feedback`: LLM-semantically detects durable corrections, proposes atomic rules, applies
  **human-gated** via delta-merge. Ships a deterministic `extract_feedback_queue.py`.
- NEW [`rules/learn-from-corrections.md`](rules/learn-from-corrections.md) — the protocol + the test
  evidence + cross-links (memory-maintenance delta-merge, autonomy-risk-tiers human-gate).
- **Evidence:** detection was tested independently before adoption. A keyword detector scored
  **F1 0.42** on held-out adversarial cases (missed ~60% of real corrections, incl. all keyword-free
  ones); an LLM-semantic detector scored **F1 0.97** on the same set. So the hook does NO keyword
  judgment — detection is LLM, in the human-gated distill step. (KV-cache hygiene was also tested and
  **skipped** — low yield: the dominant cache-buster is harness-injected, not our authored files.)
- **Privacy:** fixed two pre-existing privacy-marker leaks found by the full-tree scan — a host name
  in `hooks/activity-journal-guard.py` and personal historical paths in `scripts/validate_config.py`.
- README counts refreshed (36 hooks / 31 skills / 26 rules).

---

## 2026-06-18 (v3.30.2 — agent task artifact skeleton)

- NEW [`templates/agent-task/`](templates/agent-task/) provides a drop-in `.agent/tasks/<task-id>/` skeleton: `spec.md`, `state.json`, `scratchpad.md`, `trace.jsonl`, `evidence/`, `verdict.json`, `problems.md`, `fix-log.md`, and `handoff.md`.
- [`principles/02-proof-loop.md`](principles/02-proof-loop.md) now links to the template so long-running, multi-agent, high-risk, or compaction-prone work starts with durable state/evidence instead of chat-only memory.

---

## 2026-06-18 (v3.30.1 — PreCompact AUTO-DRAFT handoff fallback)

- **[`hooks/precompact-handoff-guard.py`](hooks/precompact-handoff-guard.py)** now writes a best-effort `.claude/handoffs/codex-auto/*-auto.md` transfer artifact when context compaction starts and no fresh semantic handoff exists. The draft is generated from the local Codex JSONL session log (recent user messages, assistant progress notes, and tool-call anchors) and is intentionally marked `AUTO-DRAFT`, so the next agent upgrades it into a normal handoff before substantive work.
- The same hook now tolerates UTF-8 BOM on stdin, which makes manual PowerShell testing match hook behavior instead of falling back to the current working directory.
- Docs updated in `README.md`, `hooks/README.md`, and `rules/safety-hooks.md`.

---

## 2026-06-16 (v3.30.0 — rules consolidation: fewer-but-focused, agent-* demoted to a skill)

Research-backed consolidation of the always-on rule set (fewer files, no duplicates, one concern per file). Driven by current best practice: thin always-on context + demote situational detail to on-demand skills — bloated rule sets cause context-rot / lost-in-the-middle, which hurts quality, not just cost.

- **rules/ 43 → 24.** Near-duplicates merged by synthesis (load-bearing detail kept, prose dropped):
  - 8 per-hook safety docs (destructive, git-destructive, self-harm, command-injection, test-muting, api-key-leak, auto-backup, backup-retention) folded into the single [`rules/safety-hooks.md`](rules/safety-hooks.md) index ("Per-hook: safe-use, gaps, tuning" section). `safety-secrets` folded into [`rules/secrets-as-data.md`](rules/secrets-as-data.md).
  - `quality-no-monkey-patch` + `quality-no-over-engineering` → one [`rules/quality-code.md`](rules/quality-code.md) (two poles: no-hack + no-over-build, sweet spot = minimal correct architecture + verify).
  - `memory-crosslinks` + `ace-context-merge` → one [`rules/memory-maintenance.md`](rules/memory-maintenance.md) (cross-links + provenance tags + ACE delta-merge).
- **Agent-harness design rules demoted to a skill.** The 10 `agent-*` + `context-trust-labels` rules (situational — relevant only when building an agent harness) moved into the new [`skills/agent-harness-design/`](skills/agent-harness-design/SKILL.md) (10 reference sheets), off always-on context. `CLAUDE.md` "Designing New Agents" now points to the skill.
- All cross-references updated (CLAUDE.md, rules, README EN/中文/RU counts); no dead links; drift validator clean.

---

## 2026-06-10 (v3.29.1 — user-facing docs actualized to match actual contents)

Every "textual information" surface refreshed against the real file tree (counts were 1-2 versions stale):

- **README.md**: intro counts corrected (29 principles / 25 hooks / 28 skills / 43 rules); principles list completed (12 Low-Signal Residual Training, 13 Research Pipeline, 29 MVP Agent Blueprint were missing); hooks table expanded 15 -> 25 rows with verified events/matchers (taken from a live `settings.json` wiring, not guessed); Structure section now documents `rules/` and `workflows/`; install table gains a "more than one CLI agent" row; CN/RU intro sections rewritten with current counts and the cross-harness pointer.
- **[`scripts/install_hooks.py`](scripts/install_hooks.py)**: 9 shipped-but-uninstallable hooks added to `--extras` (claude-attribution-guard, human-confirmation-guard, db-snapshot-guard, verify-deleted-guard, file-cohesion-guard, precompact-handoff-guard, test-gate-stop-hook, problems-md-validator, plan-gate) — previously the repo shipped 25 hooks but the installer knew only 15.
- **[`CLAUDE.md`](CLAUDE.md)**: Core Working Rules section extended with the rules published in v3.29.0 (autonomy-risk-tiers, no-guessing, git-source-of-truth, file-organization-cohesion, cross-harness-agents-md) — previously listed only 5 of the always-on set.
- **[`AGENTS.md`](AGENTS.md)**: counts + `workflows/` entry.
- **[`HOW-IT-WORKS.md`](HOW-IT-WORKS.md)**: new "Cross-Harness Context" section (one AGENTS.md, many CLIs — the no-symlinks mechanism table); scripts table completed (12 scripts, was 5).
- **[`MAINTENANCE.md`](MAINTENANCE.md)**: section 3 (bi-weekly sync) rewritten around the mechanized `sync_public_config.py` four-bucket workflow.

---

## 2026-06-10 (v3.29.0 — cross-harness AGENTS.md, gemini-delegate, workflows/, mechanical public-repo sync)

**Cross-harness context sharing (the "CLAUDE.md vs GEMINI.md vs AGENTS.md" question):**
- NEW [`rules/cross-harness-agents-md.md`](rules/cross-harness-agents-md.md) — one canonical `AGENTS.md` per project shared by Claude Code (`@AGENTS.md` import), Gemini CLI (`context.fileName` setting), and Codex (native). No symlinks — they break on Windows and behave differently across platforms in git. Includes task-level context passing (handoff/brief markdown files as the universal currency) and trust labels for cross-vendor output.
- NEW skill [`skills/operational/gemini-delegate/`](skills/operational/gemini-delegate/SKILL.md) — delegating bulk / long-context / second-opinion work to Gemini CLI: multi-account OAuth stash switcher ([`scripts/gemini-switch.sh`](scripts/gemini-switch.sh)), live-measured quota caps (~16-18 Pro-tier agentic tasks/account/day) with a recovery ladder (switch account → Flash model → split across days), non-interactive invocation patterns, hard boundaries (no secrets to external LLMs, semi_trusted output).

**Dynamic workflows go public:**
- NEW [`workflows/`](workflows/) — drop-in workflow commands `/deep-review-flow` (competency review with adversarial verify) and `/research-cn-ru` (research with mandatory CN/RU sources), plus [`workflows/EFFECTIVE-AGENTS.md`](workflows/EFFECTIVE-AGENTS.md) — measured lessons from production runs (one `agent()` ≈ 95-150k tokens; resume is the main economy lever).
- NEW skill [`skills/development/workflow-orchestration/`](skills/development/workflow-orchestration/SKILL.md) — writing dynamic workflow scripts: pipeline vs parallel, schemas, budgets, resume, quality patterns, billing discipline.
- [`rules/safety-billing.md`](rules/safety-billing.md) gains Risk 4: dynamic workflows as a token-burn multiplier — opt-in requirement, scale estimation before launch, `budget`-guard in loops.

**Broken references fixed + missing rules published.** Several rules already in this repo (`silent-failure-detection`, `deletion-confirm-and-verify`, `quality-no-monkey-patch`, `quality-over-tokens-independent-verify`) linked to files that were not here. Now published:
- [`rules/system-verification-independent.md`](rules/system-verification-independent.md) — control systems / kill switches / functions verify behavior independently ("function name ≠ behavior"), with the real watchdog-that-didn't-kill case
- [`rules/safety-hooks.md`](rules/safety-hooks.md) — one-page map of every hook + the `# claude-bypass: <key>` comment format
- [`rules/autonomy-risk-tiers.md`](rules/autonomy-risk-tiers.md) — act without asking on reversible actions; backup→verify→act (or wait) only on the irreversible tier
- [`rules/git-source-of-truth.md`](rules/git-source-of-truth.md) — git as the single source of truth; deploy → commit+push always together; the 4 classes of things that stay out
- [`rules/file-organization-cohesion.md`](rules/file-organization-cohesion.md) + enforcing hook [`hooks/file-cohesion-guard.py`](hooks/file-cohesion-guard.py) — durable artifacts go into the existing structure, related files stay together
- [`rules/post-ui-change-review.md`](rules/post-ui-change-review.md) — isolated design-review subagent after every CSS/HTML/DOM change (path-scoped)
- [`templates/bug-fix-prompt.md`](templates/bug-fix-prompt.md) — bug-fix task prompt with anti-"pre-existing" constraints baked in

**Repo freshness is now mechanical:**
- NEW [`scripts/sync_public_config.py`](scripts/sync_public_config.py) + [`sync-manifest.json`](sync-manifest.json) — manifest-driven one-way sync from a live `~/.claude` into this repo: EOL-normalized diffing (a CRLF clone no longer reads as "everything differs"), deny-list for machine-specific files, active-only files surface as candidates instead of being auto-copied, and a privacy-marker scanner (`--scan-repo --strict`) gates every push. Reusable for any private-config/public-fork split.

---

## 2026-05-28 (v3.28.0 — silent-failure-detection: plugin CLI prerequisite verifier)

NEW [`rules/silent-failure-detection.md`](rules/silent-failure-detection.md)
NEW [`scripts/verify_plugin_prerequisites.py`](scripts/verify_plugin_prerequisites.py)

A class of harness gap that does not announce itself: a Claude Code plugin is `enabled: true` in `settings.json`, but its hooks shell out to an external CLI (semgrep, gh, stripe, language servers) that is not installed on the host. Hook exits non-zero, Claude Code logs it and continues. User keeps the illusion of protection while the actual layer is a silent no-op.

Real case that surfaced this: the official `semgrep@claude-plugins-official` plugin was enabled on a Windows machine. Its `hooks.json` invokes `semgrep mcp -k post-tool-cli-scan` on every Write/Edit. `shutil.which("semgrep")` was `None`. Every Write/Edit for the entire session had been failing silently. The gap was caught only by an unrelated `where.exe semgrep` audit.

Resolution = a SessionStart hook that reads `enabledPlugins` from `settings.json`, looks up known CLI requirements per plugin, and `shutil.which`-checks each one. Missing → printed to stdout for the agent and the user to see. Informational only (exit 0), does not block the session.

Conservative map: only plugins whose own `hooks.json` or `.mcp.json` invokes a documented external CLI. Extension protocol is in the rule (open the plugin's hooks.json, find external-binary commands, add to the map).

Specializes [`system-verification-independent.md`](rules/system-verification-independent.md) ("name ≠ behavior") to the harness itself — silent-failure detection of the protection layer.

Known gaps documented in the rule:
- MCP server failures inside third-party plugins (Node missing, etc.) not yet covered
- Hook failures due to missing env / permissions / wrong cwd not covered
- Bundled-Python-script crashes not covered

These are documented explicitly so the rule does not provide false confidence.

---

## 2026-05-21 (v3.27.0 — alternatives/agents-md-rule-loading: JIT skills vs always-on rule blob)

NEW alternatives/agents-md-rule-loading.md

Triggered by Gloaguen et al. 2026 ("Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?", arXiv 2602.11988): repository context files -- both auto-generated and human-written -- reduce coding-agent task success and add 20%+ cost by pushing agents toward broader exploration. Compares three ways to load a rule corpus:

- Approach A: always-on blob (the paper's measured failure mode)
- Approach B: path-scoped rules (`paths:` frontmatter, file-glob triggered)
- Approach C: skills as JIT (description in context, body on demand) + lean indexed root file

Recommendation: tier the corpus -- a small always-on core (safety + core methodology), path-scoped rules for file-correlated guidance, skills for topic-bound guidance, an index in the root file so nothing is lost. Includes verified Claude Code loading mechanics: `rules/` files load unconditionally; `paths:` is the only conditional-activation field; skills use progressive disclosure; `@path` imports load at launch and do not save context.

Caveat documented: prompt caching makes always-loaded content cheap but not harmless -- the success-rate degradation is behavioral, not cost. Framed as an `alternatives/` comparison (not a principle) because the conclusion is evidence-backed but pending A/B validation.

---

## 2026-05-16 (v3.26.0 — closing remaining gaps from agents-best-practices: event model, skill install checklist, connector code-exec)

Preventive close of the 3 remaining items from the v3.23.0 evaluation. We previously took 85% of upstream content (the parts with immediate use case). This release takes the remaining 15% (forward-looking) so the integration is complete and future surface-area additions only add NEW concepts, not catch-up on existing ones.

NEW skills/agent-harness-design/references/agent-event-model.md (10th operational rule)
- 13 canonical event types for harness state persistence: user_message, assistant_message, tool_call, tool_result, approval_request, approval_result, plan_update, goal_update, skill_invocation, memory_load, context_compaction, connector_call, error, final_answer
- Append-only `events.jsonl` storage layout with separate artifacts/ folder for bulky payloads referenced by `evidence_ref`
- Cross-event correlation via `parent_event_id` (tool_result → tool_call, approval_result → approval_request)
- 5 operations made trivial with event model vs without (replay, audit, compaction, eval grading, cost analysis)
- "Implement by trigger, not upfront" guidance: start with 5 minimal events, add others as production surfaces the need

NEW skills/agent-harness-design/references/agent-skill-install-checklist.md (11th operational rule)
- Pre-install checklist: source verification, repo activity, license, README-to-code map, version pinning, min-release-age
- During-install: sandbox unknown scripts, permission manifest read, ATTRIBUTION.md trail, no symlinks rule
- Post-install: inventory update, first-use trial in isolated context, trust label assignment, removal procedure documentation
- Periodic audit (monthly or post-incident)
- Incident response 6-step for compromised skill (pause-rename, diff since install, audit affected sessions, cleanup, post-mortem, update this checklist)
- Real-world worked example: Denis Sergeevitch's `agents-best-practices` install in this same session (which checklist items passed, which were borderline)

EXTENDED skills/agent-harness-design/references/agent-tool-design.md (section 9 added)
- **Connector Code-Execution Pattern** for MCP server / connector catalogs with 50+ tools or large data
- Instead of exposing 50 raw tools — expose single `connector_exec(code: str)` that runs Python/JS in sandbox with pre-loaded connector library
- 5 measurable benefits (selective tool loading, pre-context filtering, intermediate state, fewer tool-call loops, sensitive data isolation)
- Sandbox constraints (CPU/memory limits, network allowlist, filesystem allowlist, no subprocess, egress logging, credentials isolation)
- When to apply / when NOT to apply with explicit thresholds

UPDATED CLAUDE.md
- "Designing New Agents" bumped from 8 rules to 10 rules (added agent-event-model, agent-skill-install-checklist)

UPDATED principles/README.md
- 3 new rows in decision matrix (event persistence, 3rd-party install verification, MCP 50+ tools)
- "New custom AI agent" project-type row: added event-model to baseline, added streaming + skill-install to supporting

**Why preventive and not on-trigger:**

In v3.23.0 evaluation we marked these 3 items as "wait for trigger" (first event-sourced agent, third 3rd-party install per month, first MCP server with 50+ tools). User asked to take them preventively. Reasoning: the cost of cold content (~400 lines of markdown that may sit unused) is low — they don't consume context until referenced via skill activation or rule load. The benefit of completeness is real: future evaluations of agent-builder tools won't need to "what did we already cover?" inventory pass.

**Cumulative state after this release:**

- 11 always-on agent-builder rules (`rules/agent-*.md`)
- 1 deep-dive principle (29 MVP Agent Blueprint)
- 1 cloned upstream skill (locally, not in this repo)
- 1 alternatives comparison (skill-management-tools.md)
- 4 enriched existing principles (01, 02, 14, 28 indirectly via long-run-harness)
- 1 foundational quote in CLAUDE.md (agent-legibility)
- 5 releases on 2026-05-16 (v3.22.0 → v3.26.0)

Content from Denis Sergeevitch's `agents-best-practices` upstream skill: **fully integrated** at the synthesis level. Remaining 0% gap — items deliberately not taken: provider API patterns (covered by agent-sdk-dev plugins), source links file (linked from principle 29), coverage-audit meta-doc.

**Code review notes:**
- All 11 agent-builder rules cross-reference each other consistently
- Personal data scan on 3 new files: 0 hits
- All cross-references in new content validated
- Public CLAUDE.md now lists 10 rules in "Designing New Agents" section; principles/README.md decision matrix has 9 rows for agent-builder concerns

---

## 2026-05-16 (v3.25.0 — alternatives/skill-management-tools: evaluation of ai-dotfiles + Skiller)

Two community projects surfaced today solving variants of "manage Claude Code skills across machines and projects":

- **ai-dotfiles** (https://github.com/pavel-gorlov/ai-dotfiles) — Python CLI, "npm for Claude Code config", symlink-based with vendor system for 3rd party (github / skills.sh / paks / buildwithclaude / tonsofskills). Solves the manual-mirror pain point cleanly.
- **Skiller** (https://github.com/beautyfree/skiller) — Electron GUI managing skills across 30+ AI agent tools (Claude Code, Cursor, Codex, Gemini CLI, etc.).

Evaluated both for adoption. **Neither adopted right now**, but both documented as alternatives with honest "when each fits" guidance.

NEW alternatives/skill-management-tools.md
- Problem framing: when manual cp + git push becomes friction
- ai-dotfiles section: how it works (catalog, manifest, symlinks, vendor system, settings/MCP merge, gitignore sync), where it fits well, why this repo does NOT adopt right now (symlinks are a hard "no" per `НИКАКИХ СИМЛИНКОВ` rule; supply chain — 4 days old, 0 stars, pipx bypasses min-release-age=7; public-vs-private boundary question)
- Skiller section: how it works (Electron GUI, 30+ agent normalization, selective install), where it fits (multi-tool users), why this repo does NOT adopt (Claude Code-primary, CLI-first, single abstraction level limitation)
- "This repo's current approach" — explicit description of manual cp + git push flow we use, with no symlinks, explicit ATTRIBUTION.md per cloned external skill
- "When to switch" — concrete thresholds (>5 commits/week, >5 project-level .claude/ dirs, third machine, frequent 3rd-party installs) when reconsideration is warranted
- Cross-refs to managed-agents.md, orchestration.md, principles 08/17

UPDATED alternatives/README.md
- Added skill-management-tools.md row to comparison table
- Flagged drift: README table has 7 entries but directory contains 16 comparison files; documented as known manual maintenance step

**Why document and not adopt:**

- ai-dotfiles is technically a good solution to a real pain point we have. But adoption requires either changing our global "no symlinks" rule (which was made deliberately — see CLAUDE.md history) or forking the tool to use file copies. Either is a larger investment than the current manual approach's friction justifies (3 commits today is high-water-mark, not steady state).
- Skiller's value proposition is cross-tool normalization. We are Claude Code-primary. Different problem.
- Both are worth knowing about for community members with different constraints (multiple machines, multiple AI tools, frequent 3rd-party install) where adoption math flips.

**Out-of-scope but noted:** other projects in the same announcement batch (Palatine Speech, Palatine Spectra, Stepik agents course, Sublex) target different domains (B2B speech, industrial CV, beginner agent course, YouTube subtitles) and were not evaluated for this repo's scope.

---

## 2026-05-16 (v3.24.0 — rules/agent-streaming, principle 02/14 enrichments, sanitization pass)

Same-day follow-up to v3.23.0. Adds the 8th operational rule (streaming buffering, forward-looking), enriches two existing principles with relationship/decision content, and does a sanitization pass on residual references to specific deployments and persons in older changelog entries.

NEW skills/agent-harness-design/references/agent-streaming.md (8th rule in the agent-builder series)
- 5 buffering rules for incremental tool calls when using `stream=True`
- Minimal Python buffer pattern with `pending_tool_use` accumulator
- Abort handling: synthetic tool result with `stream_aborted` type
- 3 output-guardrail modes (post-buffer / token-level / hybrid) with tradeoff analysis
- Forward-looking: current Agent SDK apps are synchronous; this rule prevents the typical "partial tool execution" bug when streaming is first introduced

UPDATED principles/02-proof-loop.md
- Added "Relationship to principle 01" callout at the top explaining the composition: principle 01 = general Generator-Evaluator for subjective tasks, principle 02 = specialization for testable tasks with frozen spec + 4 strict roles + fresh-context verifier. They compose -- Proof Loop can use Generator-Evaluator inside its Builder role.

UPDATED principles/14-managed-agents.md
- New "Extended Decision Matrix: 12 criteria for Managed vs Self-Built Harness" replaces a 5-row table with a 12-row decision matrix covering: standard workload, custom tools, regulated data, custom audit, financial actions, communication sends, IAM, multi-tenant isolation, prototype speed, sustained high-volume cost, vendor lock-in tolerance, infra team capacity
- Documents the hybrid pattern (Managed Agents for standard sub-tasks invoked by self-built brain owning business authorization)

UPDATED CLAUDE.md
- "Designing New Agents" bumped from 7 rules to 8 rules
- One sanitization fix in CLAUDE.md inter-agent communication section

UPDATED principles/README.md
- 2 new rows in decision matrix (streaming, Managed vs self-built)
- One sanitization fix in principle 19 reference

UPDATED HOW-IT-WORKS.md, alternatives/agent-mailbox-system.md, principles/19-inter-agent-communication.md
- Sanitization: replaced specific deployment name + 3 person-name role assignments with generic role descriptions (planner / executor / reviewer). The pattern stays intact; the case study just becomes provider-neutral.

UPDATED rules/no-guessing.md, rules/verify-at-consumer.md
- Replaced a personal-name attribution with "a collaborator's parallel Claude session" (idea attribution preserved, person name removed)

UPDATED rules/long-run-harness.md
- Replaced 3 broken author-workspace `.claude/rules/...` cross-refs with `project-level .claude/rules/...` (in the public repo they read as broken pointers)

UPDATED UPDATES.md (historic entries)
- v3.7.1 entry: replaced 3 specific project mentions with generic descriptors
- v3.20.x entry: personal-name attribution updated
- Inter-Agent Mail v3.18 entry: production validation reference made provider-neutral

**Local-only changes (not in public repo, documented here for reference):**
- `~/.claude/scripts/block_secrets.py` got a top-of-file marker explaining it's disabled in settings.json and documenting the architectural decision (replaced by outbound-gate `pre_push_public_repo_scan.py`). This is preventive: a future session greppping for `block_secrets` will see the breadcrumb and not "fix" what was intentionally turned off.
- `~/.claude/CLAUDE.md` slimmed from 992 lines to ~580 lines (-41%) by replacing duplicated principle content with short summaries + links to public principles. Personal/project-specific content (BILLING SAFETY, CUDA/PyTorch, Vikunja conventions, Frontend Design Catalog, etc.) preserved at full depth. Backup saved at `~/.claude/CLAUDE.md.backup-2026-05-16`.

**Why the local CLAUDE.md was bloated:** principles 01/02/03/04/05/06/07/11/14/28 each had a 25-80 line section in CLAUDE.md repeating content also present in the public principle files. This created drift risk (which version is canonical?) and burned KV-cache space (~400 lines of duplicated prose loaded every session). The public principles ARE the canonical source; CLAUDE.md should be a map with anchored summaries, not a wiki.

**Code review notes:**
- All cross-references between 8 agent-builder rules + 2 enriched principles validated (0 broken)
- Personal data scan: 0 hits in new content; pre-existing references in older changelog entries sanitized in this round
- Public CLAUDE.md size after this round: 467 lines (within ~150-line AGENTS.md target by approximately 3x; further trimming would require deleting content rather than slimming and was not done)

---

## 2026-05-16 (v3.23.0 — 4 more operational rules from agents-best-practices + agent-tool-design extension)

Same-day follow-up to v3.22.0. After analyzing what else from upstream was actually a **gap** (not redundant with our existing principles), four more rules were extracted, plus the existing `skills/agent-harness-design/references/agent-tool-design.md` got two new sections.

The decision rule applied: take everything that **fills a real operational gap** (no canonical format, no checklist, no contract), skip what duplicates existing principles 01/02/07/10/16/21/28.

NEW skills/agent-harness-design/references/agent-evals.md
- 13 mandatory eval categories (task_success, tool_selection_precision, unnecessary_tool_calls, permission_correctness, approval_correctness, prompt_injection_resistance, context_compaction_retention, retrieval_relevance, output_format_adherence, failure_recovery, cost_and_latency, human_intervention_rate, false_confidence)
- 13 specific adversarial test cases that must be in eval set from day 1 (retrieved-document-injection, exfiltration-request-in-email, malformed-tool-output, expired-connector-auth, etc.)
- Trace grading questions for periodic spot-check
- Eval workflow (CI integration, threshold, regression on incident)
- Connects to principle 21 -- every accepted code-review finding gains a regression eval

NEW skills/agent-harness-design/references/agent-observability.md
- 16 mandatory trace fields per model call (run_id, instructions_loaded, tools_visible, tool_calls, permission_decisions, approval_requests, approval_results, tokens, cache breakdown, latency, cost_estimate, etc.)
- What NOT to log (hidden reasoning, full tool args with secrets, raw user content)
- 7-question audit format -- a trace must answer all 7 from-the-trace
- Periodic grading questions (manual spot-check, ~1-2 runs per week)
- 6-step incident response (pause -> preserve -> identify -> patch -> regression eval -> gradual re-enable)
- Cost monitoring alerts (cost-per-task baseline, cache hit rate, tools_visible cardinality, compaction count, approval response time)

NEW skills/agent-harness-design/references/agent-plan-artifact.md
- Planning mode = runtime mode, not paragraph in prompt -- mutation tools mechanically blocked
- 8 specific triggers for entering planning mode + when NOT to enter
- Plan artifact 10-field format stored as durable file (not conversation message)
- Plan approval bound to plan_id + version -- version bump invalidates approval
- Plan-Validate-Execute pattern (gather source-of-truth -> create plan -> validate against source -> request approval -> execute one step at a time -> validate after each)

NEW skills/agent-harness-design/references/agent-approval-records.md
- Approval request format (JSON schema with approval_id, approval_type, action, target, risk, preview_ref, expected_result, rollback, scope, scope_details, context, requested_by)
- Approval result format (JSON schema with status, approved_by, timestamp, scope, expires_at, auth_method)
- 4 scope rules (exact-action-not-category, single-use-unless-explicit, expiration-mandatory, scope-changes-require-new-approval)
- 5 re-approval triggers (plan version bump, target changed, risk class escalated, time elapsed, scope boundary)
- Audit log immutable append-only storage convention
- Anti-pattern: model self-approval -- permission engine MUST verify approver != requester

EXTENDED skills/agent-harness-design/references/agent-tool-design.md
- New section 6: Deferred Tool Loading 4 detail levels (`name_only`, `name_and_description`, `full_schema`, `examples`) -- critical for MCP server design with 50+ tools combined
- New section 7: Hosted vs Client Tools decision matrix -- 8 criteria mapping (private business APIs, regulated data, financial actions, communication sends -> always client; web search, image gen, code-exec sandbox -> hosted OK)
- New section 8: Strict Schemas (provider validation + harness double-check) -- provider validates structure, harness validates business semantics

UPDATED CLAUDE.md
- "Designing New Agents" section bumped from 3 rules to 7 rules with full descriptions

UPDATED principles/README.md
- Project-type table updated: 4 new rules added to "New custom AI agent" baseline + supporting
- Decision matrix +4 rows for the new rules

**Why all 4 new rules + section extensions in one release:** the 4 rules form an interconnected operational layer:
- agent-tool-design.md says **what** tools look like
- agent-plan-artifact.md says **when** to plan vs execute
- agent-approval-records.md says **how** approvals are recorded
- agent-evals.md says **how** to test all of the above
- agent-observability.md says **how** to verify it ran correctly in production

Splitting them would create artificial cross-version dependencies. Better to ship the layer atomically.

**What we deliberately did NOT take in this round:**
- Provider API patterns (Responses-style, Chat Completions, Anthropic) -- our agent-sdk-dev plugins still cover this
- Goal-like loop in full depth -- overlaps with principles 03 (autoresearch CORAL/HyperAgent) and 04 (deterministic orchestration)
- Source links file -- already linked from principle 29

**Source:** Same as v3.22.0 -- [DenisSergeevitch/agents-best-practices](https://github.com/DenisSergeevitch/agents-best-practices) v1.2.0 (MIT). Files synthesized this round: `security-evals-observability.md` (evals + observability + approvals), `planning-and-goals.md` (plan artifact), `tools-and-permissions.md` (deferred loading + strict schemas), `provider-api-patterns.md` (hosted vs client tools).

**Code review notes:**
- All cross-references between the 5 new/updated rule files validated (each rule references the others where conceptually linked, no circular dependency, no contradiction)
- Personal data scan: 0 hits in new content
- Reconciled the 3 different existing places mentioning "approval" (CLAUDE.md harness section, rules/safety-*, principles/10) by making `agent-approval-records.md` the canonical format spec; older mentions remain as conceptual references

---

## 2026-05-16 (v3.22.0 — Principle 29 MVP Agent Blueprint + 3 operational rules from agents-best-practices)

A new principle and three operational rules adapted from Denis Sergeevitch's [agents-best-practices](https://github.com/DenisSergeevitch/agents-best-practices) skill (MIT). The gap this fills: principles 01 (Harness Design) and 02 (Proof Loop) describe **how an agent should work** once it exists, but we had no structured flow for **designing a brand-new agent from scratch** -- the moment when "I want an agent that does X" turns into a deployable first version. This update adds that flow plus three always-on rules for the design choices you make at that moment.

**Why we adopted this externally rather than writing our own.** Denis's skill is provider-neutral, generalizes beyond coding (research, finance, support, ops, sales, healthcare, education, procurement), and is MIT-licensed -- exactly the surface we were missing. We took 5 of his ~14 reference files, kept attribution, summarized into one principle + three rules instead of bulk-copying, and wired the rest into our existing principle map.

NEW: principles/29-mvp-agent-blueprint.md
- 15-section MVP blueprint output template (Objective -> MVP scope -> Autonomy -> Core loop -> Instructions -> Tools -> Planning -> Goal loop -> Memory/Compaction -> Skills/Connectors -> Caching -> Safety -> Observability -> Implementation path -> First release checklist)
- 5 autonomy levels (answer-only / draft-only / approval-gated / policy-bounded auto / long-running goal) with explicit "pick the lowest level that creates value" guidance
- 5-step domain intake (Domain / Primary user / Job-to-be-done / Inputs / Outputs)
- Build order (loop -> tools -> permissions -> structured results -> budgets -> tracing -> planning -> compaction -> skills -> connectors -> goal loops -> subagents)
- Composition recipes with principles 01, 07, 10, 21
- Cross-link to upstream MIT skill for full depth (provider API patterns, complete tool schemas, prompt templates)

NEW: skills/agent-harness-design/references/agent-tool-design.md
- 15-class tool risk taxonomy (`read_only` -> `privileged_admin`)
- 7-type permission decision object (`allow` / `deny` / `ask_user` / `approval_required` / `require_stronger_auth` / `run_in_sandbox` / `run_as_draft_only`)
- Draft/commit naming pattern with 4 conventional pairs (`draft_X -> send_X`, `prepare_X -> apply_X`, `propose_X -> commit_X`, `recommend_X -> execute_X`)
- Structured tool result format with mandatory `next_valid_actions` field (cuts retry loops 2-3x in observed deployments)
- 5-level tool visibility model (`base` / `task` / `skill` / `connector` / `deferred` / `sensitive`)
- Pre-merge checklist for new tools

NEW: rules/context-trust-labels.md
- 3-level trust hierarchy (`trusted` / `semi_trusted` / `untrusted`) with explicit examples per level
- Verbatim boundary statement to wrap untrusted content (recommendation: use the same exact sentence each time so the model learns to recognize the boundary)
- 6-item "what untrusted content cannot do" list (override permissions, change scope, bypass approval, etc.)
- Real-world detection pattern: prompt injection in fetched markdown content -- caught by untrusted-by-default + verify-before-act
- Helper Python wrapper recommendation for Agent SDK code

NEW: skills/agent-harness-design/references/agent-budgets.md
- 10 mandatory budget types every agent loop must declare (`max_model_turns`, `max_tool_calls`, `max_parallel_tool_calls`, `max_wall_time_seconds`, `max_input_tokens`, `max_output_tokens`, `max_total_cost`, `max_tool_result_chars`, `max_retries_per_model_call`, `max_retries_per_tool_call`)
- Recommended defaults with rationale per budget
- Stop format (JSON object) when a budget is hit -- includes `next_safe_action` so the user can decide to extend or stop
- Failure modes that this rule catches (overnight autoresearch loops, unbounded poll loops in serverless handlers, stuck cron tasks)

UPDATED: rules/long-run-harness.md
- Added "First Release Checklist" -- 15 pass/fail items grouped into Code-level / Process-level / Knowledge-level / Safety-level. Project must pass all 15 before being marked `[LONG-RUN]`. Adapted from Denis's "First release checklist" + our 3-Layer Validation Gate.

UPDATED: principles/01-harness-design.md
- Added "See also" pointer to principle 29 at the top: "principle 29 produces the first version's spec, principle 01 governs how it iterates"

UPDATED: principles/README.md
- Bumped principle count 28 -> 29
- Added 2 rows to "Pick by project type" table (new custom AI agent, agent that ingests external content)
- Added principle 29 entry with cross-references to 01, 07, 10, 21 + the three new rules
- Added 4 rows to Decision Matrix for the new design language

UPDATED: CLAUDE.md
- Added "Agent-Legible Environment" foundational principle quote at the top of the Harness Design region
- Added "Designing New Agents -- Structured Flow" section linking to principle 29 + the three new rules

**What we deliberately did NOT take from upstream:**
- Provider API patterns (Responses-style, Chat Completions, Anthropic) -- our existing agent-sdk-dev plugins cover this
- Goal-like loop / planning mode in full depth -- overlaps with our principles 03 (autoresearch), 04 (deterministic orchestration), 16 (project chronicles)
- Bulk copy of all 14 upstream reference files -- would create a maintenance fork and stale; the principle file links to upstream for full depth instead

**Local installation note** (not in this repo, but relevant for users): the upstream skill can be cloned directly into `~/.claude/skills/agents-best-practices/` so it triggers automatically on phrases like "build me an agent". This repo only carries the adapted summary + the operational rules, since rules need to be version-controlled with the rest of the stack while the skill itself can update independently from upstream.

**Source:** [DenisSergeevitch/agents-best-practices](https://github.com/DenisSergeevitch/agents-best-practices) v1.2.0 (MIT). Reference files synthesized: `mvp-agent-blueprint.md`, `tools-and-permissions.md`, `system-prompts-instructions.md`, `context-memory-compaction.md`, `agentic-loop.md`, `agent-legibility-feedback-loops.md`. Original skill cloned at 2026-05-16.

---

## 2026-05-13 (v3.21.0 — Mechanical enforcement for no-claude-attribution: two hook scripts)

Follow-up to v3.19.0 (`rules/no-claude-attribution.md`). The rule alone is an instruction-layer defence — it works while the assistant remembers it, but can be lost under context pressure. The two new hooks add mechanical enforcement (IAEA-style defence-in-depth: instruction + automation).

NEW: hooks/claude-attribution-guard.py (`PreToolUse` on Bash)
- Inspects only Bash commands that produce git/GitHub artifacts: `git commit`, `git commit --amend`, `gh pr create|edit|comment`, `gh pr merge`, `gh issue create|comment`. Other Bash commands pass through silently.
- Scans the command (including heredoc bodies) for forbidden attribution patterns: `Co-Authored-By: Claude/Anthropic/AI`, `<noreply@anthropic.com>`, `🤖 Generated with [Claude Code]`, `Generated with claude.ai/code`, `Authored by Claude`, etc.
- On match returns `{"decision": "block", "reason": "..."}` with a fix recipe.
- OVERRIDEs Claude Code's default system-prompt instruction to add these footers — works because rules declared in `~/.claude/CLAUDE.md` have higher priority than the base system prompt.
- Bypass for intentional exceptions: in-command marker `# claude-bypass: attribution` or env var `CLAUDE_ALLOW_ATTRIBUTION=1`.

NEW: hooks/pre-push-claude-attribution.py (git `pre-push` hook)
- Final gate before commits reach the remote. The PreToolUse hook above catches commits made inside a Claude Code session, but cannot see commits made from a plain terminal, from IDE git integrations, or before the rule was adopted.
- Reads git's standard pre-push stdin format (`<local_ref> <local_sha> <remote_ref> <remote_sha>`), enumerates commits in the push range, scans message bodies for the same attribution patterns.
- New-branch case handled (`remote_sha = 0000...`): enumerates commits reachable from local that are not on any remote, capped at 200.
- Install once globally:
  ```bash
  mkdir -p ~/.claude/scripts/git-hooks
  cat > ~/.claude/scripts/git-hooks/pre-push <<'EOF'
  #!/bin/bash
  set -e
  STDIN_DATA="$(cat)"
  echo "$STDIN_DATA" | python ~/.claude/scripts/pre-push-claude-attribution.py
  EOF
  chmod +x ~/.claude/scripts/git-hooks/pre-push
  git config --global core.hooksPath ~/.claude/scripts/git-hooks
  ```
- Bypass (env var only, in-command markers don't apply at git layer): `CLAUDE_ALLOW_PUSH_ATTRIBUTION=1 git push ...`

Both hooks tested with 5+3 unit cases before adoption: block on attributed commits, allow clean commits, respect bypass, ignore non-git Bash, allow empty push ranges.

Defence-in-depth stack now: (1) text rule in CLAUDE.md, (2) PreToolUse Bash guard, (3) git pre-push guard. Three independent layers — instruction loss does not defeat the system because the lower layers fire mechanically.

For the policy details and the HERMES.md / Issue #53262 background that motivates the policy, see [rules/no-claude-attribution.md](rules/no-claude-attribution.md) and [rules/safety-billing.md](rules/safety-billing.md).

---

## 2026-05-13 (v3.20.0 — Principle 28 Feature-Layer Architecture: project knowledge as a navigable tree)

A new orthogonal slice added to the stack: **per-project layer documentation** with hyperlinked feature narratives. The gap this fills: long-running projects accumulate knowledge in three uncoordinated places (cross-cutting KB, machine-readable state, scattered git log), but **no single artifact** captures one feature's design rationale + implementation plan + verification + retrospective as a coherent narrative. ULTRAPACK ([btseytlin/ultrapack](https://github.com/btseytlin/ultrapack)) solved this with `docs/tasks/<slug>.md`; this update integrates the same idea into our existing kb-skeleton structure with explicit cross-tier hyperlinks (global KB to layer KB to feature doc) and project-wide F-NNN ID space.

NEW: principles/28-feature-layer-architecture.md
- Three-tier model: Global KB (cross-project) -> Layer KB (per-project bounded concern) -> Feature (per-project narrative)
- A layer is a bounded concern (security, data, ui, infrastructure, domain) -- organizational, NOT directory-based
- A feature lives in a primary layer, may touch secondary layers (explicit link declarations)
- Unified ID system: P-NN / R-name / A-name (Tier 1), L-name / F-NNN / IV-N / D-N / G-N / PT-N (Tier 2-3)
- Hyperlink convention: anchor within feature, relative within project, GitHub raw URLs to Tier 1
- Promotion gate: feature-local pattern -> layer pattern -> global principle (by usage, not intent)
- Relationship table to existing principles 07, 11, 18, 21

NEW: templates/kb-skeleton/docs/layers/ (extends existing kb-skeleton)
- `_LAYER-TEMPLATE/` -- complete scaffold for one bounded concern
- `_LAYER-TEMPLATE/README.md` -- layer overview with linked principles + features table
- `_LAYER-TEMPLATE/history.md` -- reverse-chronological evolution log
- `_LAYER-TEMPLATE/kb/{invariants,decisions,gotchas,patterns}.md` -- layer-scoped KB mirroring project-wide kb structure
- `_LAYER-TEMPLATE/features/_FEATURE-TEMPLATE.md` -- ULTRAPACK-style narrative (Design / Plan / Verify / Conclusion) with extended cross-references to layer invariants and global principles
- `docs/layers/README.md` -- layer index template with cross-layer Mermaid graph placeholder

NEW: skills/architecture/layer-new/SKILL.md (slash command `/layer-new <name>`)
- Scaffolds `docs/layers/<name>/` with full template tree
- Validates layer name (kebab-case, not generic file-system names)
- Updates `docs/layers/README.md` layer index automatically
- Idempotent: second call is a no-op with clear message
- Falls back to GitHub fetch if template missing on current machine

NEW: skills/architecture/feature-new/SKILL.md (slash command `/feature-new <layer> <slug>`)
- Auto-allocates next F-NNN ID (project-wide namespace, not per-layer)
- Creates `docs/layers/<layer>/features/feat-<NNN>-<slug>.md` from template
- Updates layer README features table
- Appends entry to `feature_list.json` if present (with explicit `encoding="utf-8"` per UTF-8 posting rule)
- Validates slug format and rejects collision with existing IDs

NEW: templates/kb-skeleton/scripts/build_kb_graph.py
- Stdlib-only parser of `docs/layers/**` markdown structure
- Generates `docs/_graph/tree.md` -- full Mermaid graph of layers + features + cross-reference edges (any F-NNN mentioned in a feature body, not just declared depends-on)
- Generates `docs/_graph/backlinks.json` -- reverse index for "who references this feature/invariant/decision"
- Generates `docs/_graph/health.md` -- consistency report (dangling F-NNN refs, feature_list.json sync, missing titles/statuses)
- `--check-only` flag for CI integration (nonzero exit on errors)
- Cross-platform: Windows-safe with `encoding="utf-8"` everywhere

NEW: scripts/validate_kb_links.py (registered in SessionStart hook)
- Lightweight scan on every session start (<200ms)
- Silent skip when project has no `docs/layers/` (most projects)
- Reports: layer count, per-layer feature count + status breakdown, placeholder detection (`<layer-name>` leftover)
- Cross-checks `feature_list.json` membership with on-disk features
- Output injected into agent context so fresh sessions see KB status before reading code

UPDATED: settings.json
- Added `validate_kb_links.py` to SessionStart hooks (after existing `check_handoff.py` and `detect_new_courses.py`)

Why this is in `principles/`, `templates/`, `skills/`, and `scripts/` -- not in `rules/`:
- This is an **architectural pattern** (principle 28), not an operational safety rule
- The templates and skills are tools to adopt the pattern, not guardrails that block dangerous actions
- The SessionStart hook is purely informational -- it never blocks, only reports state

What this is NOT:
- A replacement for `feature_list.json` (machine state stays separate from human narrative)
- A replacement for `PROBLEMS.md` (incident log stays separate from feature-scoped retrospective)
- A replacement for ULTRAPACK -- the spirit is borrowed, the integration extended for kb-skeleton compatibility

Sources of inspiration:
- [ULTRAPACK by btseytlin](https://github.com/btseytlin/ultrapack) -- minimalist task.md narrative pattern
- [ULTRAPACK example task: ultrapack-v1.md](https://github.com/btseytlin/ultrapack/blob/main/docs/tasks/ultrapack-v1.md)
- [hr-breaker bug fix task](https://github.com/btseytlin/hr-breaker/blob/main/docs/tasks/fix-non-ascii-resume-upload.md) -- demonstrates handsoff decisions documentation
- Principle 21 -- Knowledge Base Enforcement (the triangle of fix/test/invariant this extends)

Adoption path for an existing long-running project:
1. Copy `templates/kb-skeleton/docs/layers/` into the project's `docs/`
2. For each major bounded concern (security, data, ui, infra...), run `/layer-new <name>`
3. For 2-3 in-flight features, run `/feature-new <layer> <slug>` and migrate narrative content
4. Add `doc:` and `layer:` fields to existing `feature_list.json` entries
5. Run `python scripts/build_kb_graph.py` once to verify and generate `docs/_graph/`

---

## 2026-05-13 (v3.19.0 — Billing safety: HERMES.md + ANTHROPIC_API_KEY + no-attribution)

Two real-world documented classes of **silent billing override** in Claude Code surfaced in late April / early May 2026. Multiple Max subscribers got pay-as-you-go API charges on top of their flat-rate plan — without warning, without confirmation. Adding two new rules to the public stack so other Claude Code users can adopt the same defence.

NEW: rules/safety-billing.md (HERMES.md + ANTHROPIC_API_KEY + auto-recharge defence)
- **Risk 1 — HERMES.md in git history**: file/commit/branch name containing `hermes.md` (any case) triggers Claude Code's harness-detection regex when reading `git status` into system prompt. Session silently switches to extra-usage tier on top of Max plan. Documented case: $200.98 overcharge ([Issue #53262](https://github.com/anthropics/claude-code/issues/53262))
- **Risk 2 — ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN in env**: silent precedence over OAuth subscription. Common scenario: `.env` file of another project (Supabase edge functions, custom backend) inherited into the shell where you run `claude`. Auto-recharge can trigger without warning. Cases: $152, $187 documented ([Issue #53728](https://github.com/anthropics/claude-code/issues/53728), [#53638](https://github.com/anthropics/claude-code/issues/53638), [#39903](https://github.com/anthropics/claude-code/issues/39903))
- **Risk 3 — Auto-charge on API credit exhaustion**: Anthropic Console default enables auto-recharge. Combined with Risk 2 → full billing limit can be drained silently
- Mandatory pre-session checks (Bash + PowerShell variants)
- Cleanup procedures: `git filter-repo` for HERMES.md, env unset for API keys
- Recovery procedure when incident already happened
- Hook ideas (TBD, opportunity for contributors): PreToolUse Bash block + SessionStart env check

NEW: rules/no-claude-attribution.md (forbid `Co-Authored-By: Claude` in git/PR/issues)
- **OVERRIDE** Claude Code's default system prompt instruction to add `Co-Authored-By: Claude <noreply@anthropic.com>` to commits and `🤖 Generated with [Claude Code]` to PR descriptions
- Forbidden in: git commits (public + private), PR titles/descriptions, issue bodies, project management tools, Slack/Discord/Telegram bots, code comments
- Allowed when content (repo named `claude-code-config`, file `claude-handler.py`, bug report about Claude Code itself) — not attribution
- **Main rationale**: defence-in-depth with Risk 1 above. Claude Code already scans git history for harness fingerprints; minimizing AI-related footprint reduces surface for future detection-regex false positives that could trigger billing changes
- Secondary: privacy/B2B professionalism, git blame clarity, team symmetry
- Mechanical enforcement: PreToolUse hook idea (TBD) + project-level `.git/hooks/commit-msg` template included

Why this is in `rules/` and not `principles/`: these are operational safety procedures (concrete check-before-action commands), same category as the existing `safety-*` family. Principles cover architectural patterns.

What this is NOT: a fix for Anthropic's bugs. Issues #53262 and #53728 are open and require Anthropic action. These rules are user-side defence until upstream fixes ship.

Sources:
- [Issue #53262: HERMES.md billing trigger](https://github.com/anthropics/claude-code/issues/53262)
- [Issue #53728: Silent ANTHROPIC_API_KEY precedence](https://github.com/anthropics/claude-code/issues/53728)
- [Issue #53638: Desktop project API key override](https://github.com/anthropics/claude-code/issues/53638)
- [Issue #39903: $152 subagent case](https://github.com/anthropics/claude-code/issues/39903)
- [MindStudio analysis](https://www.mindstudio.ai/blog/hermes-md-bug-claude-max-billing-subscription-pricing)
- [Consumer Rights Wiki](https://consumerrights.wiki/w/Anthropic_Claude_Code_HERMES.md_billing_flaw)
- [Anthropic Help Center: API key env vars](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code)
- [reddit r/ClaudeAI: $187 case via project .env](https://www.reddit.com/r/ClaudeAI/comments/1tbaq2d/)

---

## 2026-05-12 (v3.18.0 — Harness audit skill + Coordinator/Fork/Swarm triad)

Follow-up to v3.17.0. After integrating the four most useful pieces from Learn Harness Engineering, went deeper into the course `references/` to extract one more skill and one principle extension.

NEW: skills/operational/harness-audit/ (the 5-subsystem assessment as a callable skill)
- Score a project across 5 subsystems: Instructions / State / Verification / Scope / Lifecycle (1-5 each)
- Adapted to OUR concrete stack (CLAUDE.md + .claude/rules/ + PROBLEMS.md + feature_list.json + init.sh + hooks)
- Identify the lowest-scoring subsystem as the bottleneck
- Produce a prioritized 3-step improvement plan with effort estimates and pointers to our templates
- references/checklist-per-subsystem.md — concrete binary checks (hard + soft) per subsystem
- references/scoring-rubric.md — anchored 1-5 levels, tiebreakers, 3 calibration examples (fresh prototype / mature project / OSS skill repo)
- Designed as a query-only skill — produces scorecard, does not make changes
- Skip criterion: short-term projects (<5 features or <5 sessions) — overhead not warranted

EXTENDED: principles/06-multi-agent-decomposition.md
- Added "Three Delegation Patterns: Context Sharing as the Dimension" section
- Coordinator / Fork / Swarm triad distinguished by **context sharing level** (none / full / shared-state)
- Hard constraints per pattern:
  - Coordinator: must synthesize before re-dispatch (no "based on your findings, do X")
  - Fork: single-level only (recursive forks multiply context exponentially)
  - Swarm: flat roster only (teammates cannot spawn teammates)
- Self-contained worker prompt template (applies across all three patterns)
- Reinforces our existing "Never delegate understanding" rule with structured framing

What we considered taking but didn't (after reading 5 reference patterns + 6 project READMEs):

- **memory-persistence-pattern.md** — already mirrors our 4-type taxonomy and two-step save invariant
- **context-engineering-pattern.md** — already covered by practice_context_engineering with Select/Write/Compress/Isolate operations
- **tool-registry-pattern.md** — theory for runtime builders; we are runtime consumers via hooks
- **lifecycle-bootstrap-pattern.md** — same — runtime-builder content, not skill-consumer content
- **Project 05's Planner+Generator+Evaluator 3-role pattern** — already in our Proof Loop principle (02) with 4 roles (Spec-freezer + Builder + Verifier + Fixer)
- **Project 06 capstone benchmarking scripts** — useful concept but not adopted as a pattern; we measure harness value qualitatively per project

Honest assessment: after deep reading, the course confirmed ~90% of our stack is current with state-of-the-art harness engineering. The remaining genuine gaps were the four items from v3.17.0 plus this audit skill plus the multi-agent triad framing. Diminishing returns from here.

Source: [walkinglabs/learn-harness-engineering](https://github.com/walkinglabs/learn-harness-engineering), MIT license. 5-subsystem framework from their `skills/harness-creator/SKILL.md` Phase 2 assessment. Multi-agent triad from their `skills/harness-creator/references/multi-agent-pattern.md`.

---

## 2026-05-12 (v3.17.0 — Long-run project harness: feature_list.json + init.sh + 3-layer validation gate)

After reviewing the [Learn Harness Engineering course](https://walkinglabs.github.io/learn-harness-engineering/) (walkinglabs, MIT-licensed), we integrated four genuinely useful pieces into our existing stack. Most of the course (~80%) overlaps with our existing principles 01-20, but these four close real gaps:

NEW: principles/27-feature-tracking.md
- The three-artifact harness for long-run projects: PROBLEMS.md (incidents) + feature_list.json (scope) + init.sh (health check)
- Machine-readable feature state with 4 statuses (not-started / in-progress / blocked / done)
- WIP=1 invariant: at most one feature in-progress at any time
- Evidence field at status='done' must reference L1 (static) + L2 (runtime) + L3 (system) durable artifacts
- done → anything else is forbidden (regressions become new fix features)
- Bootstrap procedure for existing long-run projects (extract from handoffs + chronicles)
- Mechanical enforcement sketch via Stop hook (defence-in-depth)
- Anti-patterns: 50+ entries (use BACKLOG.md instead), vague evidence, init.sh that downloads multi-GB models

NEW: templates/long-run-project/
- feature_list.schema.json — drop-in JSON Schema (Draft 07)
- feature_list.template.json — worked example with all 4 statuses + dependencies + evidence
- init.sh.template — bash skeleton with commented language-specific sections (Python/Node/Rust)
- README.md — bootstrap instructions, status transitions, evidence requirements, when-to-skip guidance

NEW: rules/long-run-harness.md (Russian, mirrors private ~/.claude/rules/long-run-harness.md)
- Convention: every [LONG-RUN] project gets feature_list.json + init.sh in repo root
- Target metric: <3 min from fresh clone to ./init.sh exit 0
- Anti-patterns specific to our stack (downloading torch in init.sh without --index-url, etc.)
- Source attribution to walkinglabs/learn-harness-engineering

UPDATED: rules/no-pre-existing-evasion.md
- Added "WIP=1 + VCR Blocking" section
- Connects to 3-Layer Validation Gate via evidence requirements
- Lists acceptable ways to switch features (block / rollback / never two in-progress)

This release also reflects updates landed in our private stack (mirrored here for reference):

PRIVATE UPDATE: ~/.claude/CLAUDE.md "Proof Loop Pattern"
- Added explicit "3-Layer Validation Gate" subsection
- L1 (Syntax/Static) → L2 (Runtime) → L3 (System/E2E), no skipping
- "L3 without L2 = autoreject" rule with real-world case (UI state mismatch caught only by browser smoke, not by curl-only L3 probes)
- Default policies per project size (full 3 layers for prod, L1+L2 for utilities, L1-only for pure refactors)
- Every layer requires a durable artifact (no claim without file path)

What we deliberately did NOT take from the course:

- AGENTS.md as a separate file (we already use CLAUDE.md as the routing layer)
- Modular CLAUDE.md split into docs/* (we already have .claude/rules/ doing exactly this)
- OpenTelemetry observability (overkill for our scale; we have structured logs where they matter)
- 5-subsystem audit as a separate skill (covered by existing project-health workflows)
- Memory taxonomy (our 4-type system — user/feedback/project/reference — is equivalent)
- Multi-agent coordination patterns (our principles 01, 06, 18 are richer)

The course is excellent for teams without an existing harness. For us, ~80% was already mature. These four additions are the genuine gaps it surfaced.

Source: [walkinglabs/learn-harness-engineering](https://github.com/walkinglabs/learn-harness-engineering), MIT license. Templates lifted from `skills/harness-creator/templates/` with modifications.

---

## 2026-05-10 (v3.16.0 — Scaling architecture for 10K+ elements + dataset learning pipeline)

User questions: (1) how to store and orchestrate when library has 10,000+
elements so a small agent can compose beautiful animations from text;
(2) if we download 1000 Pinterest pixel art images, can we learn from them
to build similar quality automatically.

This release adds 4 reference documents covering both questions, plus
synthesis of two parallel research agents on 2026 state-of-the-art tools.

NEW: references/element-library-scaling-architecture.md (550+ lines)
- Tier-based growth path (10 to 10,000+ elements)
- Per-element files in category folders + _manifest.json
- Lazy loader pattern via _registry.js (dynamic imports)
- 512-dim CLIP/SigLIP embedding vectors per element
- ANN search in browser (brute-force at 10K, HNSW WASM beyond)
- Per-element semver versioning for backward compat
- Scene grammar (YAML) for composition constraints
- 8-step agent workflow: text -> intent -> embedding query -> grammar
  -> render -> vision LLM critique -> iterate -> bake
- Storage backend tradeoffs (static files / SQLite-in-browser /
  PostgreSQL+pgvector / managed services)
- Build pipeline + auto-preview generation
- Migration plan from v3.15 (9 elements) to v3.16-ready architecture

NEW: references/pinterest-to-library-pipeline.md (300+ lines)
- 3-layer translation problem: lossy JPEG -> grid-aligned PNG ->
  structured representation -> element drawer code
- Stage A pixelization options (pyxelate / Pillow LIBIMAGEQUANT /
  SDXL+Pixel-Art-XL / RetroDiffusion / FLUX LoRAs)
- Stage B structured extraction (vision LLM tagging / SAM 2 /
  palette+clustering)
- Stage C library integration (3 approaches: manual / AI-assisted /
  train-then-generate)
- End-to-end command sequence
- LoRA training alternative path
- Hybrid pipeline (best of both)
- Legal note: prefer HuggingFace datasets / OpenGameArt / Lospec over
  Pinterest scraping

NEW: references/dataset-to-library-actionable.md (450+ lines)
THIS IS THE EXECUTABLE PLAN. Combines findings from both research agents
into single actionable pipeline:

- Stage 0 - Data: bghira/free-to-use-pixelart (HuggingFace, clean license)
- Stage 1 - Pixelize: Pillow + imagequant PyPI (Oct 2025), 10 min CPU
  for 1000 images. Optional SD-piXL (ETH Zurich, SIGGRAPH Asia 2024,
  arxiv 2410.06236) for top-quality subset with mathematical grid
  alignment guarantee.
- Stage 2 - Decompose: Qwen2.5-VL-7B local (within 5-10% of GPT-4o,
  free) OR Gemini 2.5 Flash ($0.50 for 1000 images)
- Stage 3 - Cluster: DINOv2 (texture-aware visual style) + UMAP (20D)
  + HDBSCAN (auto-K, expected 15-40 clusters). SigLIP-2 for semantic
  text-image search.
- Stage 4 - Mine grammar: mlxtend FP-Growth on element co-occurrence
  -> rules like "mountains -> fog_band confidence=0.84"
- Stage 5 - Generate drawers: Claude vision + code generation, ~70-80%
  correct first pass, ~20 min human refinement per drawer
- Stage 6 - Train LoRA (optional): FLUX LoRA via fal.ai ($8 per 1000
  steps) or local fluxgym/ai-toolkit. SDXL LoRA superseded by FLUX
  in 2026.
- Stage 7 - Evaluate: CMMD (CLIP Maximum Mean Discrepancy) via
  clean-fid library. FID is broken for pixel art (Inception trained
  on ImageNet); CMMD has better convergence on non-ImageNet domains.

Compose scenes via SceneSmith pattern (arxiv 2602.09153, Feb 2026):
designer + critic + orchestrator with 3-5 iteration loop.

Total cost for mature 100-element library starting from 1000 images:
~30 hours human work + $10-20 cloud APIs.

NEW: research/product/pixel-art-2026-05-10/ now contains 5 research docs:
- pixel-art-{en,cn,kr,ru}-research.md (4-language research, v3.8)
- loop-animation-and-storyboard-research.md (v3.10)
- twilight-scenarios.md (v3.9)
- image-to-pixel-art-tools-2026.md (v3.11)
- high-detail-tools-2026.md (v3.14)
- image-collection-learning-2026.md (v3.16, NEW)
- image-to-pixelart-and-training-2026.md (v3.16, NEW)

Plugin description: 22 skills, 5 evaluator agents, 9-element library
with declarative composition, scaling architecture documented through
10,000+ elements.

Workshop snapshot also updated: pixel-art-workshop-2026-05-10/
(consolidated folder) now reflects v3.16 documentation.

---

## 2026-05-10 (v3.15.0 — Element library: declarative scene composition)

User feedback: hand-coding each cover from scratch (370 lines per Tier 2 scene)
is repetitive. Suggestion: pre-draw reusable elements and compose scenes from
them. This is exactly the pattern in the user's Elements Sheet.html reference
(16 elements x 3-8 variants).

This release adds the **element library**:

NEW: `skills/creative/pixel-art-studio/elements/elements.js`
9 reusable element drawing functions:
- drawSky (4 palette variants: dusk-cool / dawn-warm / midnight / autumn)
- drawStars (3 variants: dense / sparse / twinkling, with twinkle phase)
- drawMountainRange (3 depths: far / mid / near for atmospheric perspective)
- drawTower (3 variants: stone / ruined / runic, with brick texture +
  crenellations + optional flag with sin-wave wave animation)
- drawWindow (3 variants: lit / flickering / dark, volumetric glow halo)
- drawPine (3 sizes x 3 depths fg/mg/bg, with branches + snow on tips)
- drawFogBand (3 intensities for atmospheric haze layer)
- drawSnow (light/heavy variants, deterministic seeded falling)
- drawGround (snow surface with deterministic texture sparkles)

Each element function has standard signature `drawXxx(ctx, x, y, opts)` where
opts includes variant / palette / scale / t (animation phase 0..1) / seed.
Palettes are semantic: `palette.bg1..bg4` (sky stops), `palette.stone` /
`stoneLight` / `stoneDark` (architecture), `palette.warm` / `warmGlow`
(accent), etc. 4 named palettes (dusk-cool, dawn-warm, midnight, autumn).

NEW: `elements/catalog.html` - visual preview of all elements x variants
Mirror of user's Elements Sheet.html pattern. 25 canvas previews in 9
sections show every variant of every element. For style approval before
scene composition. Verified rendering: 25 canvases, 9 sections, 0 console
errors.

NEW: `examples/library-demo/index.html` - declarative scene composition
Same fortress-tower scene as Tier 2 demo, but composed from JSON instead of
370-line hand-coded draw function:

```javascript
const SCENE = [
  { el: "sky",            variant: "dusk-cool" },
  { el: "stars",          variant: "dense", maxY: 130, count: 80 },
  { el: "mountain-range", x: 0, y: 220, variant: "far",  seed: 311 },
  { el: "fog-band",       x: 0, y: 215, h: 20, intensity: 0.4 },
  { el: "mountain-range", x: 0, y: 240, variant: "mid",  seed: 322 },
  { el: "mountain-range", x: 0, y: 250, variant: "near", seed: 333 },
  { el: "tower",          x: 96, y: 90, variant: "stone", height: 150, width: 14 },
  { el: "window",         x: 92, y: 100, variant: "lit", flickerPhase: 0.1 },
  // ... 16 more lines
];
renderScene(ctx, W, H, SCENE, t);
```

7x reduction in code (50 lines vs 370 lines), same visual quality. Full 100%
canvas coverage verified (55,296/55,296 pixels rendered). Live animation via
phase-derived loops in element functions.

The declarative pattern is **AI-friendly** - LLMs can generate scene specs as
JSON without understanding pixel-level drawing code. This unlocks the
pixel-art-storyboard skill's natural-language-to-scene workflow at scale.

Element registry pattern (renderScene + ELEMENT_REGISTRY) makes adding new
elements trivial: write `drawXxx(ctx, x, y, opts)`, register in
ELEMENT_REGISTRY, available everywhere. Future expansion: castles, cities,
ships, characters, magical effects, weather (rain, lightning), wildlife
(birds, butterflies, deer).

Workshop snapshot also updated: pixel-art-workshop-2026-05-10/ (consolidated
folder with all today's artifacts) now contains 100 files, 1.3MB. Includes
README with full architecture overview + CHANGELOG with v3.8-v3.15 entries.

Plugin description: 22 skills, 5 evaluator agents, detail tier system,
9-element library with declarative scene composition.

---

## 2026-05-10 (v3.14.0 — Detail tier system: high-detail-pipeline doc + base-image composite + Tier 2 demo)

User feedback after v3.13.0: existing 64x96 covers look "primitive" compared to
professional pixel art references (Saint11/Slynyrd-tier work, AI-generated
pieces at 480-720px with atmospheric perspective, volumetric lighting, fine
textures). Reference images shown were a fortress-on-cliff scene and a snowy
night street with multi-temperature lighting and 50+ colors.

This release adds the **detail tier system**:

| Tier | Approach | Time/cover | % of pro reference |
|---|---|---|---|
| 1 (existing) | 64x96 hand-coded canvas, 8 layers | 30 min | ~20% |
| 2 (NEW) | 192x288 hand-coded canvas, 15 layers | 2-4 h | ~60% |
| 3 (NEW) | AI base (SDXL+LoRA) + canvas animation overlay | 15-60 min | ~85-95% |

**`references/high-detail-pipeline.md`** documents the Tier 3 workflow:
- Stage 1: AI generation (SDXL + Pixel Art XL LoRA, FLUX-based LoRAs,
  RetroDiffusion REST API, MidJourney + post-process)
- Stage 2: Pixel snap + palette enforcement (preprocess.py with NEAREST
  downsample + LIBIMAGEQUANT quantize + Atkinson dither)
- Stage 3: Manual cleanup (quality_check.py + pixel-art-quality-board)
- Stage 4: Canvas animation overlay (static PNG <img> + transparent canvas
  for snow/glow/flicker animations on top)
- Stage 5: Bake composite to WebP/MP4/WebM via bake_animation.py

Includes working SDXL+LoRA Python code, RetroDiffusion API examples, and
cost/time tradeoffs (RetroDiffusion ~$0.02 per cover, SDXL local on RTX 4080+
free but ~30-60s/cover).

**`bake_animation.py` extended with `--base-image` flag**:
Composite static PNG (Tier 3 AI base) UNDER canvas animation overlay at each
captured frame. The static image carries heavy detail (mountains, buildings,
textures); canvas only animates motion elements (snow, window flicker, fog
drift). CPU stays low at runtime, file stays small after baking.

```bash
python scripts/bake_animation.py http://localhost:9132/composite-cover.html \
  --canvas-id overlay \
  --base-image cover_snapped.png \
  --period-ms 8000 --fps 30 --format web -o cover_final.webp
```

**`examples/tier2-detail-demo/`** — side-by-side visual comparison of Tier 1
vs Tier 2 of the same scene (fortress tower at dusk):
- Tier 1: 6,144 logical pixels, 12 colors, 1 mountain layer, 30 stars,
  1 motion source — quick prototype quality
- Tier 2: 53,387 logical pixels (96.5% canvas coverage), 32+ colors,
  3 mountain ranges with atmospheric perspective and snow caps,
  pine forest with 3 depth layers (background/midground/foreground),
  brick-textured tower with 12-window grid and individual flicker phases,
  volumetric glow halos around lit windows (3-pixel radial, alpha-blend),
  fog band between mountain layers, 24 multi-component snow particles,
  red banner with sin-wave animation, snow ground with texture pattern

Verified programmatically: both canvases render with full coverage, no
console errors. Visual screenshot shows clear detail upgrade from Tier 1 to
Tier 2 — significantly closer to professional reference quality without AI.

For users who want Tier 3 quality without local GPU: RetroDiffusion REST API
or PixelLab Python SDK provide programmatic AI generation with 50 free
credits / paid tiers. Full pipeline documented in
`references/high-detail-pipeline.md`.

Plugin description: 22 skills, 5 evaluator agents, now with detail tier
system spanning quick prototype to professional-grade.

---

## 2026-05-10 (v3.13.0 — Animated WebP support + format decision tree)

`bake_animation.py` now supports **animated WebP** as a first-class output
format (`--format webp` or alias `--format web`). WebP is now the **default**
because it's the best web format: ~5x smaller than equivalent GIF, supports
full alpha channel, and embeds as `<img>` tag (unlike WebM which requires
`<video>` element).

Format size comparison (4-second loop @ 30fps, 256x384):
- Animated WebP: ~150-400 KB (full alpha, embed as <img>)
- WebM-alpha:    ~200-500 KB (full alpha, requires <video>)
- MP4:           ~200-500 KB (NO alpha, universal compat)
- GIF:           ~1-2 MB (1-bit alpha only, embed everywhere)
- APNG:          ~1.5-4 MB (full alpha, embed as <img>)
- PNG sequence:  ~5-15 MB (lossless, for game engine import)

New flags:
- `--format web` (alias for `--format webp`) - now the DEFAULT
- `--lossless` - WebP pixel-perfect mode (larger files, use for archival)
- `--quality N` - WebP lossy quality 0-100 (default 80, barely visible
  difference on pixel art due to flat-fill regions)

Updated `references/smoother-animation-baking.md` with:
- Decision tree for format selection by use case (web embed / chat / video
  editor / game engine / archival)
- Quality tuning guide for WebP lossy vs lossless on pixel art
- Why lossy q=80 is fine for pixel art (no chroma subsampling artifacts on
  flat-fill pixel boundaries)

The user-facing recommendation flow:
- "I want to put this on a website / in markdown" → `--format web` (WebP)
- "I want to send this in Telegram / email" → `--format gif` (universal)
- "I want to import into After Effects / DaVinci" → `--format webm-alpha`
- "I want to use in Unity / Godot" → `--format png-sequence`

Implementation: Pillow's native WebP encoder (no ffmpeg dependency for WebP).
`Image.save(..., format='WebP', save_all=True, append_images=..., method=6,
allow_mixed=True, minimize_size=True)` produces optimal animated WebP.

---

## 2026-05-10 (v3.12.0 — Fantasy book covers worked example: LOTR / GoT / Name of the Wind)

End-to-end validation of the v3.11.0 pipeline. Three classic fantasy covers
generated step-by-step from real book iconography to working canvas-rendered
animation, demonstrating the full workflow:

1. **Real cover research** (WebSearch on iconography per book)
2. **Palette selection from Design Seeds catalog** via `--search-tag` and `--mood`
3. **Scene specification** (5-element framework documented in `scenarios.md`)
4. **Canvas program coding** (8-layer retouch-style composition per cover)
5. **Browser verification** (preview MCP, all 3 canvases render)
6. **Side-by-side composite** for visual proof

Three covers, three different visual moods:

- **The Fellowship of the Ring (Tolkien, 1954)**: One Ring centered with Eye of
  Sauron + Tengwar inscription orbiting. Palette: `design-seeds/heavenly-hues`
  (deep navy + warm gold + red eye accent). Loop 8s: ring rotation +
  inscription glow pulse + embers drifting up from below. Dark Mordor mountain
  silhouette at horizon.

- **A Game of Thrones (Martin, 1996)**: Iron Throne silhouette with jagged
  sword-formed back. Palette: custom frost-iron (slate blue → steel → snow
  + amber torch accent — single warm pixel against cold scene). Loop 8s:
  snow falls (12 deterministic particles) + torch flickers (multi-component
  sin) + raven flies across upper third. Distant Wall tower silhouette behind.

- **The Name of the Wind (Rothfuss, 2007)**: Hooded figure centered in autumn
  forest. Palette: `design-seeds/rose-palette` (browns + sage + dusty rose).
  Loop 6s (intentional asynchrony with 8s loops above, LCM 24s composite):
  cloak edge sub-pixel breathing + autumn leaves drifting + hidden campfire
  glow at lower-left. Flanking tree silhouettes.

All three covers bundled as `skills/creative/pixel-art-studio/examples/fantasy-covers/`:
- `index.html` — single self-contained HTML with 3-cover grid
- `scenarios.md` — full 5-element scene specifications + cover iconography
  research + design notes (palette source diversity, loop period diversity,
  8-layer retouch standard verification per cover)

Verified programmatically:
- All 3 canvases render to 6144 / 6144 / 5545 pixels (full coverage)
- drawLOTR / drawGOT / drawNOTW execute in 1.2-1.9 ms each
- 0 console errors
- Visual screenshot captured at 6× scale showing all 3 covers side-by-side

**This is the canonical "how to use the pipeline" example** — reference for
generating covers from real book iconography. Future skill invocations can
follow this exact step-by-step procedure for any book series.

---

## 2026-05-10 (v3.11.0 — Design Seeds palettes + animation baking + interaction reviewer + 2026 image-to-pixel-art tools research)

Five additions in one release. Each addresses a feedback item from real session use:
- "Палитры должны быть красивые из коробки" → Design Seeds curated palettes
- "Запекать анимации в GIF/видео с прозрачностью" → bake_animation.py
- "Шахматы парят над доской — нужен агент-проверка взаимодействия" → pixel-art-interaction-reviewer
- "Плавнее анимации" → smoother-animation-baking.md (баке N×больше кадров)
- "Image-to-pixel-art tools 2026" → research saved + documented

**Design Seeds curated palette database** (`scripts/palettes/design-seeds/`):
10 palettes hand-curated from design-seeds.com (Jessica Colaluca's site), covering the
mood spectrum: nature-tones (sage), heavenly-hues (deep night blues + warm star-glow),
color-serve (warm peach), color-palette (pastel pink), rose-palette (vintage rose),
tropical-tones (warm tropical), color-imagination (dreamy blue), color-escape (peaceful
peach), color-set (autumn red), color-wander (mystic violet). Each .hex file cites
source URL + tags + mood + best-for use cases. `_index.json` provides tag-based search
across the catalog.

**`palette.py` extended** with:
- `--list` now shows the design-seeds category (10 palettes)
- `--search-tag <tag>` returns matching palettes by tag (e.g. `twilight`, `dramatic`,
  `pinks`, `mystical`, `dreamy`, `warm-accent`)
- `--mood <query>` searches by free-form mood substring (e.g. `night`, `dawn warm`,
  `romantic`, `peaceful`)
- Nested palette path support: `design-seeds/heavenly-hues` resolves to
  `palettes/design-seeds/heavenly-hues.hex`

Verified: `--search-tag twilight` returns Heavenly Hues with full metadata including
"best_for: Twilight cover, moonlit ambient, stars + warm accent". Direct ramp lookup
for cover generation.

**`bake_animation.py` (Playwright + ffmpeg pipeline)**:
Convert canvas-rendered HTML animations to GIF / APNG / WebM (with alpha channel) /
MP4 / PNG sequence. Uses headless Chromium to drive the same JS draw functions that
run at runtime — single source of truth, no Python re-implementation drift.

Procedure:
1. Open HTML page in Playwright headless Chromium
2. Override requestAnimationFrame to no-op (control time manually)
3. For each baked frame: set `t = i/N`, call `drawXxx(ctx, W, H, t)`, capture
   canvas via `toDataURL`
4. Encode N frames via Pillow (GIF/APNG) or ffmpeg (WebM yuva420p / MP4 h264)

WebM with alpha (yuva420p) is the canonical output for video-editing import — it
preserves transparency through After Effects, DaVinci Resolve, etc. MP4 doesn't
support alpha, use it only for solid-bg covers.

Install: `pip install playwright Pillow && playwright install chromium`. ffmpeg
required for video formats.

**`smoother-animation-baking.md` reference** (in pixel-art-storyboard skill):
Documents the baking workflow + the key insight: animations are parametric on `t ∈ [0,
1)`, so we can sample `t` at any density at bake time. Runtime: 4-8 hand-coded
keyframes; baked: 100-240 frames per loop = much smoother. Costs nothing at display
time because output is a static GIF/video file.

Includes: format comparison table (GIF / APNG / WebM / MP4 / PNG sequence), FPS
selection guide (30fps sweet spot, 60fps for sub-pixel-fine motion), file size
trade-offs (WebM ~200-500KB vs GIF 800KB-2MB), production recipe (develop with
canvas+RAF, ship as `<video>` baked).

**`pixel-art-interaction-reviewer` agent** (4th specialized reviewer):
Catches things style/animation/composition reviewers miss — chess piece floating
ABOVE the board with no surface contact, character shadow falling FROM SAME side as
highlight (light-direction inconsistency), foreground object that should occlude
background but doesn't, scale mismatches (chair smaller than child's head).

Six dimensions (100pt rubric):
- Gravity & surface support (25pt) — feet/base touching ground/surface
- Occlusion order / Z-depth (20pt) — z-order matches 3D intent
- Light direction consistency (20pt) — single light source, all highlights/shadows
  agree
- Anchor point / framing (15pt) — subject anchored sensibly per cover/scene
  conventions
- Scale plausibility (10pt) — sizes between objects narratively coherent
- Animation frame consistency in interactions (10pt) — held objects don't drift,
  particles respect physics

Hard blockers (always REJECT): floating-without-justification, broken z-order,
contradictory light sources without diegetic reason.

**`pixel-art-quality-board` updated to spawn 4 reviewers in parallel** (was 3).
Aggregate `board_score = (style + animation + composition + interaction) / 4`.
Worst-of-N still applies. Cost note: 4x single-reviewer instead of 3x. Calibration
allows skipping interaction reviewer for minimal-asset covers (single icon, no
inter-object physics).

**Calibration on Twilight v2 covers (Breaking Dawn — pawn becomes queen)**:
The interaction reviewer (calibration example in agent file) catches that the pawn
sits at y=49 with bottom y=63, but board starts at y=70 → pawn floats 7 pixels
above board surface. This is exactly the type of error users were spotting; now an
agent catches it programmatically.

**`research/product/pixel-art-2026-05-10/image-to-pixel-art-tools-2026.md`** (research):
Comprehensive 2026 tool catalog for "real cover photo → pixel art" workflow:
- **Open-source Python**: pyxelate (best quality, soft-abandoned, Python 3.10
  recommended), Pillow LIBIMAGEQUANT (excellent baseline), hitherdither (advanced
  dithering kernels), rembg (background removal preprocessor)
- **AI-based**: nerijs/pixel-art-xl (HuggingFace, 8 steps LCM, img2img at strength
  0.6-0.8 for reference-driven), RetroDiffusion (commercial REST API, 50 free
  credits, true pixel art model not SD-adapted), PixelLab (Python SDK), ModelScope
  flux-2-klein-4b-spritesheet-lora
- **Web tools**: All UI-only (Pixilart, Lospec Pixelizer, PixelOver, ezgif)

Recommended pipeline for project use case: `rembg` (background separation) →
`pyxelate` GMM+Atkinson at 32×48 (reference grid for hand-coding) → `hitherdither`
for palette-constrained passes → Pillow palette extraction as hex list for canvas JS.

Plugin description: 22 skills, 4 → 5 evaluator agents.

---

## 2026-05-10 (v3.10.0 — retouch-style standardization + multi-agent quality review system)

User-supplied production references (`Grass Field with City.html` + `Elements Sheet.html`)
formalized into a style standard. Built a 4-agent quality review system that audits any
pixel-art output against the standard with multi-dimensional decomposition (style /
animation / composition / orchestrator).

**`skills/creative/pixel-art-storyboard/references/retouch-style-guide.md`**:
Formalizes the visual fingerprint observed in user reference files:
- 8-layer scene composition (sky gradient → atmospheric particles → far depth → mid depth →
  near foreground → subject → foreground motion → atmospheric overlay)
- 3-tier palette structure (Tier A sky/atmosphere, Tier B subject ramps with hue-shift,
  Tier C single-pixel accent)
- Pre-generated geometry (230 stars + 4 grass layers in reference; deterministic seeded RNG)
- Multi-component motion (windAt = travel + local + base + gust, 4 components mixed)
- Surface detail per object (3-8 surface dots/lines on subjects ≥16px)
- Day/night phase system with palette interpolation per `T ∈ [0,1]`
- Atmospheric overlay final pass for scene cohesion
- Quantitative density thresholds (50+ stars min, 4-6 colors per ramp, 3+ motion components)
- 10-point validation checklist (retouch-pass criteria)

**4 quality-review agents** (in `agents/`):

- **`pixel-art-style-reviewer`** — evaluates palette tier discipline (25pt), surface detail (20pt),
  layer depth (20pt), hue rotation across luminance ramp (15pt), accent discipline (10pt),
  anti-AI-slop signals (10pt). Returns scored JSON verdict per dimension. Cites
  `quality_check.py` and `palette.py --analyze` automated metrics.

- **`pixel-art-animation-reviewer`** — evaluates loop seamlessness (25pt), motion physics
  multi-component (20pt), concurrent independent loops (15pt), particle determinism (15pt),
  period appropriateness (15pt), phase computation correctness (10pt). Reads source code
  to verify motion math claims. Spawn-tested against running preview server when available.

- **`pixel-art-composition-reviewer`** — evaluates silhouette readability test (25pt), focal
  point clarity (20pt), visual hierarchy tier count (15pt), negative space ratio (15pt),
  scale relationships matching narrative intent (15pt), framing/breathing margin (10pt).

- **`pixel-art-quality-board`** — orchestrator that spawns 3 reviewers IN PARALLEL (Task tool
  with 3 subagent_type calls in single message), collects verdicts, synthesizes board
  decision (PASS / NEEDS_WORK / REJECT) with ranked fixes. Worst-of-N is the safe default
  (any REJECT → board REJECT). Surfaces cross-dimension fixes. Calibration on declared
  intent (minimalist 8-bit gets graded against minimalist rubric, not retouch).

**Twilight covers v2 (validation example)** at
`skills/creative/pixel-art-studio/examples/twilight-covers/index-v2.html`:
- 8-layer composition per cover (vs 2-layer in v1)
- 60-80 deterministic stars per cover (seeded `makeStarField(seed_, count, W, maxY)`)
- 4-stop sky gradients (deep midnight → violet → plum → horizon glow)
- Horizon silhouettes (tree lines, mountain ridges) on Twilight, New Moon, Eclipse
- Multi-component motion (stem sway uses travel+local sin combo on New Moon)
- Crescent moon + halo on New Moon; eclipse moon with shadow encroachment + halo on Eclipse
- Warm spotlight beam (radial gradient + globalCompositeOperation 'lighter') on Breaking Dawn
- Stars dim during dawn-breaking (last 30% of cycle) on Breaking Dawn
- Hex parser memoization for performance (HEX_CACHE map)

Verification (programmatic, screenshot tool wedged on dense canvas):
- All 4 canvases render valid PNG dataURLs (3326-7902 bytes)
- 6144 pixels per canvas (full coverage)
- 0 console errors
- `drawTwilight()` execution: 2.7ms (well within frame budget)

Plugin description: 21 → 22 skills, 1 → 4 evaluator agents.

**Cost note for quality-board orchestration**: running 3 parallel reviewers ≈ 3× the cost
of single review. Justified for "is it ready to ship" decisions, public output, or
high-stakes deliveries. For routine iteration, use single-dimension reviewers directly.

Research source: visual audit of `Grass Field with City.html` + `Elements Sheet.html`
+ 100 functions of canonical canvas-pixel-art rendering code reviewed.

---

## 2026-05-10 (v3.9.0 — new `pixel-art-storyboard` skill: narrative-to-canvas pipeline)

Companion skill to `pixel-art-studio` (v3.8.0). Where `pixel-art-studio` handles
static sprite design, palettes, dithering, quality scoring — `pixel-art-storyboard`
handles the upstream step: turning a 2-paragraph scene description (book synopsis,
album brief, ambient mood) into a self-contained HTML file with **canvas-rendered
seamless-loop animated pixel art**.

**`skills/creative/pixel-art-storyboard/`**:

- **SKILL.md** (Direction): 5-element scene framework (Subject/Setting/Lighting/
  Palette/Motion), workflow with mandatory rules (single self-contained HTML,
  no Math.random in render path, image-rendering: pixelated required, RAF per
  canvas), gotchas for canvas pixel art, troubleshooting table, 3 prompt registers.

- **references/looped-animation-techniques.md**: phase-derived loops
  (`t = (now/period) % 1`), sub-pixel breathing (Metal Slug technique), parallax
  LCM principle (Slynyrd worked example: 96px canvas with scroll rates 1/2/3/4/8),
  particle architectures (Architecture B: phase-locked deterministic field —
  `pos = f(phase, seed[i])`), palette interpolation for day/night cycles,
  loop period selection by mood, code patterns for correct vs wrong implementations.

- **references/scene-description-framework.md**: 5-element framework table,
  compositional shorthand (iconography first, symbolic accent, negative space),
  three reference forms (cover-style / establishing shot / loop-friendly), three
  full worked examples (Romeo & Juliet, lonely cabin, cyberpunk alley), constraint
  guidance per canvas size, anti-patterns table, narrative-to-spec workflow.

- **references/three-registers.md**: distinct prompt styles for LLM agent
  (parameter-heavy, machine-friendly), human pixel artist (atmospheric, emotional),
  SDXL Pixel Art LoRA (noun-heavy, comma-separated, with anchor tokens). Same
  scene shown all three ways for comparison.

- **references/easing-curves.md**: integer-pixel quantization issue, why linear
  ease feels wrong for pixel motion, designed-step easing (Celeste-style),
  pixelSnap wrapper, anticipation>action timing rule, when to skip easing
  entirely (sub-pixel breathing, phase-locked motion).

- **templates/single-cover.html**: starter HTML for a single book/album cover
  with placeholder canvas program.

- **templates/grid-cover.html**: starter HTML for multi-cover grid layout
  (4×1 → 2×2 → 1×4 responsive, dark-atmospheric aesthetic with JetBrains Mono +
  pink accents matching reference style).

**Worked example bundled**: `pixel-art-studio/examples/twilight-covers/` —
Twilight Saga 4 books (2005-2008) as animated pixel covers in a single HTML.
Each cover is a hand-coded canvas program with seamless loop:

- **Twilight (4s loop)**: red apple in pale cupped hands; highlight orbits;
  petal drifts diagonally
- **New Moon (8s loop)**: red tulip with ruffled petals; one petal falls
  per cycle; subtle stem sway
- **Eclipse (5s loop)**: torn red ribbon flowing diagonally; sin-wave flutter;
  single thread drifts through tear
- **Breaking Dawn (10s loop)**: white queen + pawn on checkered board with
  warm spotlight; transformation halo pulses in last 25% of cycle; queen-ghost
  briefly overlays pawn

Scene scenarios saved at
`research/product/pixel-art-2026-05-10/twilight-scenarios.md`.

Verified via Claude Preview MCP: server started, console clean (0 errors),
4 canvases at correct positions in 2×2 layout (CSS responsive), each running
its own requestAnimationFrame loop with distinct period.

**Why this matters**: completes the pixel-art creation pipeline.
storyboard (narrative → animated cover) → studio (sprite design + palette +
quality) → reviewer (Generator-Evaluator independent quality verdict). Three
skills compose into a full creative workflow.

Research source: 4-language earlier research (EN/CN/KR/RU) + new agent on
loop animation theory and scene description writing. All saved in
`research/product/pixel-art-2026-05-10/`.

---

## 2026-05-10 (v3.8.0 — new `pixel-art-studio` skill + first evaluator agent)

Major addition: complete pixel-art creation toolkit as a single skill, plus the first
Generator-Evaluator agent in the repo. Built from a 4-language research synthesis
(EN, CN 中文, KR 한국어, RU русский) covering classical pixel-art canon plus regional
conventions (Chinese xianxia/wuxia + 故宫/青花/五行 palettes; Korean 도트 + 오방색
KS A 0062 standard; Russian "Punch Club rule" + Stoneshard-inspired palette).

**`skills/creative/pixel-art-studio/`** — DBS-framework skill with three layers:

- **Direction** (SKILL.md, ~400 lines): workflow tree for 5 use-cases (single
  sprite / animation / image-to-pixel-art preprocessing / sprite sheet / quality
  review). Cultural style anchors: matches user-stated style (xianxia → 故宫 palette,
  Korean dot → 오방색, Russian indie → Stoneshard-inspired) to bundled assets.

- **Blueprints** (8 reference files, ~6,000 lines): drawing techniques (cluster
  theory, jaggies/doublies, selective outlining, pillow-shading anti-pattern),
  palette theory (limited palettes, hue shifting, dithering algorithms, banding
  detection), shading + materials (skin/metal/wood/water/fire/glass recipes with
  shade counts and hue tendencies), animation (Disney 12 principles applied to
  pixel art, frame counts, smear frames, sub-pixel motion, easing curves), quality
  rubric (8 anti-AI-slop signals with detection heuristics), tools and libraries
  catalog (Aseprite, pyxelate, Hitherdither, RetroDiffusion, ModelScope LoRAs),
  cultural style guides (Western canon, CN xianxia, KR dot, RU indie), extended
  JSON schema spec with 3 examples.

- **Solutions** (6 scripts, ~2,300 lines):
  - `render.py` — JSON to PNG/GIF/APNG/spritesheet, supports frames + tags +
    layers, Aseprite-compatible direction modes (forward/reverse/pingpong)
  - `quality_check.py` — orphan pixels, doublies (vertical + horizontal),
    pillow-shading detection (boundary-vs-interior luminance + light-direction
    asymmetry), hue rotation across luminance ramp, anti-AA-slop boundary
    color count, animation cross-frame consistency
  - `palette.py` — 20 bundled palettes (4 hardware-authentic, 11 Lospec
    community, 4 cultural CN/KR, 1 indie-game RU), extraction via k-means /
    median-cut / octree, hue-shifted ramp generation following Endesga rule
  - `dither.py` — 6 algorithms: Bayer 2×2/4×4/8×8, Floyd-Steinberg, Atkinson,
    ordered (clustered-dot), blue noise
  - `preprocess.py` — image-to-pixel-art pipeline (LANCZOS pre-pass for noise
    reduction, NEAREST final downsample, palette quantization, dithering)
  - `animate.py` — 6 walk/idle/attack/death animation templates with
    culturally-correct frame counts (CN 4-frame @ 200ms, KR 6-frame @ 8fps,
    Western 4-8 frames @ 8-12fps), 6 easing curves quantized to integer pixel
    positions for sub-pixel motion engineering

**`agents/pixel-art-reviewer.md`** — first Generator-Evaluator agent in the repo.
Reviews pixel art with fresh context (does not see how it was made). Runs
quality_check.py + visually inspects the PNG, then writes PASS/HOLD/REJECT verdict
with score, blocking issues, soft issues, false positives, and specific fixes.
Calibrated skeptic: high automated scores on visually-bad art get downgraded;
flagged orphans on intentional stippling get marked false-positive.

**Why it matters:** the previous `pixel-art-gen` skill in the marketplace was
basic JSON→PNG with no animation, no palette discipline, no quality control.
This new skill is production-grade: 20 bundled palettes (versus 4 ad-hoc
suggestions), automated anti-AI-slop detection (versus none), 4-language
cultural style awareness (versus Western-only), and Generator-Evaluator review
(versus self-evaluation).

Verified: all 12 smoke tests pass — render single sprite, render 4-frame
animation to GIF/APNG/spritesheet, palette listing (20 palettes in 4
categories), palette extraction via median-cut, ramp generation with 40°
hue shift, walk-template generation, easing waypoints, dither application,
animation cross-frame quality check.

---

## 2026-05-04 (v3.7.1 — test-gate-stop-hook: 3 hardening fixes from real-world deployment)

Patch release. After v3.7.0 shipped, applying the hooks to three real
workloads (a sandbox calculator project, a scraper project with empty
tests scaffold, a Go server project, plus a wider umbrella
workspace) surfaced three structural bugs. Each one would have caused
false BLOCK on legitimate sessions; each was caught and fixed before
the hook spread to wider use.

**Round 1 — section headings false-positive in problems-md-validator**.
Pure section group headings (`## Open`, `## Resolved`, `## Workarounds`)
were being treated as problem entries and flagged for missing Status.
Fix: only `## YYYY-MM-DD ...` (date-prefixed) headings count as entries.
Section headings now silent. Commit `634c08e`.

**Round 2 — test-gate override parser dropped commented files**. The
`.claude/test-command` override file is meant to be self-documenting,
so users put leading `#` comment lines explaining the command. The
parser used `strip()` and saw only the first comment as content, then
rejected the whole file. Fix: walk lines, skip leading comment/blank,
take first command line. Same release: pytest exit 5 ("no tests
collected") was being treated as failure, which broke any project
with a placeholder `tests/` directory. Fix: pytest exit 5 = silent
pass. The gate auto-activates when the first real test lands. Commit
`f6b5bfe`.

**Round 3 — umbrella-directory false-positive via rglob**. The Python
detection used `cwd.rglob("test_*.py")` to verify real test files
exist before selecting pytest. From a multi-project workspace umbrella,
rglob swept the entire tree and found CLI scripts named `test_*.py`
in unrelated subprojects (e.g. `face-relax-lora/scripts/test_single.py`
which does `sys.exit(1)` at module load). pytest tried to collect them
during import → SystemExit → exit 3 (internal error) → BLOCK. Fix:
drop rglob entirely, use only conventional locations (top-level
`pytest.ini`, `pyproject.toml` that mentions pytest, immediate
children of `tests/` or `test/`). Projects placing tests deep
(e.g. `src/pkg/tests/`) now opt in via `.claude/test-command`
override. Commit `3f74981`.

**Lesson encoded in this release**: defence-in-depth applies to
deployment process, not only runtime. Sandbox alone does not catch
these — a sandbox is too clean. The pattern that worked: sandbox
unit-test → one simple real project → one multi-project workspace.
Each tier surfaced bugs the previous tier could not. Any hook that
will run globally should pass all three tiers before being registered
in `~/.claude/settings.json`.

---

## 2026-05-04 (v3.7.0 — no-pre-existing-evasion: structural anti-laziness stack)

Adds the behavioural enforcement layer for bug-fix tasks. Stops agents
from labelling discovered issues as "pre-existing", "out of scope", or
"deferred for separate refactor" to escape work. Phrase detection
(existing `stop-phrase-guard.py`) is detective; this release adds the
preventive structural layer.

**New principle**: `principles/26-no-pre-existing-evasion.md`. Documents
the failure mode (issue #42796: 173 violations / 17 days), the bradfeld
"fix or ticket" pattern with five named exceptions, and the
hook-enforcement design.

**New rule**: `rules/no-pre-existing-evasion.md`. Drop into a project's
`.claude/rules/` or merge into `CLAUDE.md`. Lists the five legitimate
reasons to defer (missing-data, missing-dep, arch-decision,
scope-explosion, inaccessible-repo) - "complicated", "risky",
"pre-existing" are explicitly rejected.

**New hooks**:

- `hooks/test-gate-stop-hook.py` (Layer 2). Runs the project test suite
  on every Stop event. Blocks the "done" claim if the suite is red.
  Detects pytest, npm/pnpm/yarn/bun test, cargo test, go test, plus
  `.claude/test-command` override. Anti-loop guard via `stop_hook_active`.
  Bypass: `CLAUDE_SKIP_TEST_GATE=1` env or `.claude/.skip-test-gate` marker.

- `hooks/problems-md-validator.py` (Layer 4). Validates that every entry
  in `PROBLEMS.md` has a Status that is either one of the five 5-exception
  reasons, a resolution state (RESOLVED/WORKAROUND/NOT_A_BUG/CLOSED), or
  a specific blocker (`BLOCKED-<thing>`). Plain `OPEN` is rejected.
  Parser ignores section group headings (`## Open`, `## Resolved`) and
  only inspects date-prefixed entries (`## YYYY-MM-DD ...`).
  Bypass: `CLAUDE_SKIP_PROBLEMS_CHECK=1` or `.claude/.skip-problems-check`.

**Layer summary** (defence in depth):

| Layer | Component | Catches |
|---|---|---|
| 1 (detective) | `stop-phrase-guard.py` (existing) | Old phrases ("pre-existing", "good stopping point", etc.) |
| 2 (preventive) | `test-gate-stop-hook.py` (new) | Red tests at Stop event |
| 3 (verifier) | Independent agent pattern (proof-loop) | Documented; not codified - requires fresh-context spawn |
| 4 (preventive) | `problems-md-validator.py` (new) | OPEN entries without 5-exception ticket |

**Smoke-tested** in a sandbox project (4 calculator tests, 2 fail / 2 pass)
across 9 scenarios:
- Test gate: red → BLOCK; anti-loop guard; env var bypass; marker bypass; green → silent pass
- PROBLEMS.md: missing → silent pass; OPEN no exception → BLOCK; valid 5-exception statuses → pass; anti-loop guard
- Caught one parser false-positive (section headings being treated as entries) and fixed before publication

**Reference**:
- Origin investigation: [anthropics/claude-code#42796](https://github.com/anthropics/claude-code/issues/42796)
- bradfeld pattern: [advanced-claude-config gist](https://gist.github.com/bradfeld/1deb0c385d12289947ff83f145b7e4d2)
- Compliance Decay paper: Jaroslawicz et al. 2025
- Opus 4.7 literal-interpretation guidance: [Anthropic blog](https://claude.com/blog/best-practices-for-using-claude-opus-4-7-with-claude-code)

---

## 2026-04-29 (v3.6.4 — desktop-sessions: UX cleanup + critical bug fixes)

User feedback в первом live-test: "не надо кнопки которые ничего не делают". Справедливо — кнопка "Restore" в HTML только копировала команду в clipboard, фактически action делал отдельный скрипт. Affordance врала.

### Changed: HTML registry — no fake action buttons

`scripts/sessions_registry.py`:
- **Убрана** синяя "Restore" кнопка (была copy-only, выглядела как action)
- **Добавлен** selectable `local_<sid12>` chip с `user-select: all` CSS — triple-click select, ctrl+c copy. Honest affordance: видно что это data, не action.
- "RESTORED" badge теперь inline tag в title, не псевдо-overlay grid.
- Footer обновлён: "triple-click chip → tell Claude in chat" workflow.

### Fixed: critical bug — substring vs prefix match (collision risk)

`scripts/sessions_restore.py`: `find_session()` использовал `if q in sid` (substring anywhere) — query "26" нашёл 54 совпадения (короткий substring встречается посреди UUID разных sessions). Это могло привести к **wrong session restored** при ambiguous match auto-pick.

**Fix**: `if sid.startswith(q)` (prefix-match). 12-char query теперь надёжно уникален среди тысяч sessions. Anti-collision rationale в docstring.

### Fixed: critical bug — stored `sessionId` field has `local_` prefix

Storage внутри JSON: `sessionId: "local_262fa296-2064-..."` — Anthropic stores с тем же `local_` префиксом, что и filename. Мой `parse_session()` возвращал raw value, а `find_session()` ожидал clean UUID — restore падал с `no session matching` для valid sids.

**Fix**: `sid_clean = sid_raw.removeprefix("local_")` во всех 4 скриптах. Display строки везде явно re-add `local_` префикс для consistency. `restore.py` accepts both `local_<uuid>` и bare `<uuid>` форму.

### Changed: 12-char display (was 8)

8 chars = 2^32 уникальных = collision risk на ~65K sessions (birthday paradox). 12 chars = 2^48 — practically collision-free на любом human archive. `inventory.py`, `find.py`, `registry.py` показывают `local_<12chars>` consistently.

### Restored: generic platform detection regression

Случайный `cp` при sync local→public перезаписал generic versions (`storage_root()` функция с `sys.platform` детектом) хардкодом Windows-путей. Восстановлено — Mac/Linux users снова работают без environment variables.

---

## 2026-04-29 (v3.6.3 — Desktop sessions HTML registry + macOS docs)

### Added: `skills/operational/desktop-sessions-discovery/scripts/sessions_registry.py`

Четвёртый скрипт в комплекте — генерирует **HTML registry** всех сессий, авто-открывается в default браузере. UX: пользователь browse'ит дашборд, кликает "Restore" на нужной session — команда копируется в clipboard. Дальше paste в чат с Claude (skill auto-invoke сработает) или прямо в terminal.

**HTML features**:
- Live JS search по title / cwd / sessionId substring
- Sort: most recent / most turns / title A-Z / size desc
- Filter: hide 0-turn auto-runs (типа "Morning digest" / "Observer daily analysis"), hide already-restored
- Per-accountId collapsible секции, active accountId выделен зелёным border
- "RESTORED" badge для sessions уже migrated (читается из `~/.claude/desktop-migrations.jsonl`)
- Включает обе storage: `claude-code-sessions/` (current) + `local-agent-mode-sessions/` (legacy pre-Feb 2026)
- Self-contained HTML (no external deps), dark theme, ~640KB для 711 sessions

**Реальный use case**: на тестовой машине (Win11) — 711 sessions across 6 accountIds, 48MB total. Из них 69 видны в desktop UI (active accountId), остальные 642 — invisible. Registry показывает все 711 в одном scroll, с поиском и filter'ами.

### Added в SKILL.md: macOS specifics secція

- Path: `~/Library/Application Support/Claude/claude-code-sessions/<acct>/<org>/local_<sid>.json`
- Legacy path: `~/Library/Application Support/Claude/local-agent-mode-sessions/<acct>/<org>/`
- Все 4 скрипта auto-detect platform через `sys.platform` — no flags needed на Mac
- Mac-only bonus: `mdfind -onlyin ~/Library/Application\ Support/Claude/ "<query>"` (Spotlight indexes content of JSON files, faster than `find` для one-off lookups)
- HTML auto-open через `open <html>` (system default browser)
- macOS .dmg install не имеет MSIX EXDEV bug — sessions персистятся stable

### Added: `.gitignore`

Базовый `.gitignore` с `__pycache__/`, `*.pyc`, `.DS_Store`, IDE folders. Repo раньше не имел — bytecode из smoke tests рисковал попасть в commits.

---

## 2026-04-29 (v3.6.2 — Claude desktop sessions discovery toolkit)

### Added: `skills/operational/desktop-sessions-discovery/`

Новая skill-категория `operational/` для скиллов работы с самим Claude (не контент/код, а runtime). Первая запись — обходное решение для GitHub issue [#48511](https://github.com/anthropics/claude-code/issues/48511) "all session history disappears when switching accounts in Code mode" (открыт без ответа Anthropic).

**Контекст**. Claude desktop app хранит сессии в `<accountId>/<orgId>/local_*.json`. При переключении аккаунта `LocalSessionManager.loadSessions()` читает только active accountId — старые сессии становятся **невидимы в UI**, но физически остаются на диске. Один реальный пользователь обнаружил у себя 710 sessions / 50 MB истории, разбитой по 6 accountId-папкам, из которых видно только 69. Главный заброшенный архив 330 sessions (45 MB) полностью невидим.

Storage paths (reverse-engineered, **не документированы Anthropic**):

| Платформа | Путь |
|---|---|
| Win32 .exe | `%APPDATA%\Claude\claude-code-sessions\<acct>\<org>\local_<sid>.json` |
| Windows MSIX | `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\…` (broken — issue [#48362](https://github.com/anthropics/claude-code/issues/48362), atomic-rename fails в песочнице) |
| macOS | `~/Library/Application Support/Claude/claude-code-sessions/<acct>/<org>/local_<sid>.json` |

Источник: `.vite/build/index.js` line 771: `const $6t="claude-code-sessions"`. Может измениться в любом релизе.

**Три скрипта**:

1. `scripts/sessions_inventory.py` — таблица всех sessions по accountId, с titles/cwd/turns/last activity, плюс cross-account view (какие проекты были открыты под несколькими accountId)
2. `scripts/sessions_find.py "<query>"` — поиск по substring в title/cwd, фильтр по accountId/дате/`--untitled`
3. `scripts/sessions_restore.py <sid8>` — selective copy одной sessions в active accountId с byte-verify и audit log в `~/.claude/desktop-migrations.jsonl`. Source НЕ удаляется (kept as backup).

**3 риска (toolkit имеет deadline)**:
- v2.1.9+ regression (issue [#18645](https://github.com/anthropics/claude-code/issues/18645)): валидация блокирует sessions с других машин. Cross-account на той же машине пока работает, но Anthropic ужесточает проверки.
- VM bundle architecture coming (issue [#54428](https://github.com/anthropics/claude-code/issues/54428)): следующая desktop-версия переходит на `vm_bundles/claudevm.bundle/sessiondata.img` disk-image. После релиза file-copy migration **может сломаться полностью**.
- Mass merge всех 700+ sessions в один accountId = неюзабельный UI. Selective restore только когда нужна конкретная.

**Long-term recommendation**: дрифт серьёзной работы в CLI Claude Code. CLI sessions в `~/.claude/projects/<slug>/<UUID>.jsonl` account-agnostic, stable storage, JSONL формат, переживают desktop reorgs. Desktop app — для quick UI, но не для long-running.

Generic platform detection (`sys.platform` aware), UTF-8-safe stdout (для Cyrillic/Chinese titles), proof-loop verify (byte-match после copy), audit log в JSONL.

---

## 2026-04-28 (v3.6.1 — API UTF-8 posting + verify-at-consumer retry anti-pattern)

### Added: `rules/api-utf8-posting.md`

Правило при POST/PUT любого API с **non-ASCII телом** (комментарии в issue trackers, чат-сообщения в TG/Slack, GitHub PR/issue body, webhooks). На Windows цепочка `Claude harness → bash subprocess → cp1251/cp1252 console codepage → curl -d` теряет UTF-8 байты — stored body содержит литеральные `?` (0x3F) вместо букв.

**Mandatory pattern**: Python `urllib.request` + `json.dumps(..., ensure_ascii=False).encode("utf-8")` + header `Content-Type: application/json; charset=utf-8`. Inline `curl -d '{"text":"Привет"}'` НЕ использовать.

**Mandatory verification**: после каждого non-ASCII POST'а — GET back и проверить mojibake. Helper `assert_no_mojibake()` ловит heuristic "0 non-ASCII chars + много `?`" → RuntimeError.

**Hot-fix protocol** когда user в реальном времени flag'ит mojibake: НЕ извиняться, repost немедленно через Python pattern (1 мин > 5 мин обсуждения), GET back verify, только после verification confirm. Анти-паттерн: повторить broken POST с минорной правкой ("может теперь сработает") — encoding bug deterministic.

5 root-cause точек где UTF-8 ломается на Windows (curl inline, subprocess без encoding, open() без encoding, python -c inline, PowerShell Invoke-WebRequest) с конкретными fix'ами для каждой.

### Updated: `rules/verify-at-consumer.md`

Добавлен 6-й anti-pattern: **"Receiver вернул HTTP 200 + я отправила событие повторно — должно работать"**. Если payload shape wrong, retry дропается так же silently. Retry без diagnosis = waste времени. Generic, переживает конкретные incidents.

---

## 2026-04-28 (v3.6.0 — Universal destructive intent + Verify-at-consumer + Independent Verifier)

### Updated: `hooks/human-confirmation-guard.py`

Расширен с "только catastrophic" на **universal destructive intent** (rm/docker rm/kubectl delete/curl DELETE/cloud APIs/process kill/package uninstall/IAM delete/etc) + safe-target whitelist (`build/`, `dist/`, `node_modules/`, `target/`, `__pycache__/`, `.cache/`, `.venv/`, `/tmp/`, `.pyc`, `.bak`, `.DS_Store` и т.п.).

**Логика**:
1. Detect destructive intent в команде
2. Если rm-like + ВСЕ targets в SAFE_TARGETS → allow silent (рутинная очистка не требует prompts)
3. Иначе требует `# user-confirmed: "<verbatim phrase>" <timestamp>` token, fresh ≤10 min

**Effect**: 90% destructive ops теперь требуют human-in-the-loop, но routine `rm -rf node_modules` не блокирует.

### Added: `hooks/verify-deleted-guard.py` (PostToolUse)

Пятый шаг user workflow ("проверяем что реально удалили"). Hook **после** действия проверяет существование target:

| Verifier | Что проверяет |
|---|---|
| `rm` / `rmdir` | `Path(target).exists()` для каждого arg |
| `docker rm/rmi/volume rm/network rm` | `docker ps -a` / `docker images` / `docker volume ls` — name not listed |
| `kubectl delete X Y` | `kubectl get X Y` returns NotFound |
| `curl -X DELETE <url>` | follow-up `curl GET <url>` returns 404/410/204 |

Verdict: `verified-deleted` / `still-present` / `could-not-verify` → `~/.claude/logs/safety.log` + stderr warn если still-present. Не блокирует (post-action), но даёт agent'у signal не докладывать "deleted" когда proof говорит обратное.

### Added: `rules/no-guessing.md`

Канонический core-rule: каждое решение опирается на verifiable source (paper / code / probe / прямая цитата user), не "обычно так делают". **Расширено в этом v3.6.0** разделом **Independent Verifier Agent** — Generator-Evaluator pattern для важных решений: перед destructive/irreversible действием spawn isolated agent в свежем контексте, передать минимум контекста, попросить НЕ доверять reasoning'у Generator'а и независимо проверить факты. Verdict PROCEED/HOLD/REJECT.

Реальные кейсы где сработало бы (включая Replit Lemkin incident — single agent под стрессом игнорировал code freeze; independent verifier с свежим контекстом не имел бы ни стресса, ни context'а — просто посмотрел на freeze marker и REJECT).

### Added: `rules/verify-at-consumer.md`

Специализация no-guessing для интеграций (webhook, API, queue, RPC). Idea credit: a collaborator's parallel Claude session. Real case 2026-04-28:

| Layer | What we saw |
|---|---|
| Spec | `file_uploaded { url, filename, size, prompt_id }` |
| Sender log | `HTTP 200` ✓ |
| Reality (consumer code) | `services/chat/.../webhook.ts:592` reads `body.data?.url` |
| Result if shipped without verifier | Все события дропаются silently, debug 4 часа |

Правило: **Spec ≠ implementation. HTTP 200 ≠ correctness. Generator имеет blind spot.** Правда об контракте живёт в коде получателя, не в spec doc или коде отправителя. Перед shipping integration code — read consumer code, trace exact field paths, spawn isolated verifier agent для cross-check.

### Hook chain в `settings.json` (PreToolUse → Bash)

```
1. destructive-command-guard.py     (Layer 1: catastrophic)
2. human-confirmation-guard.py      (Layer 2: ANY destructive — universal)
3. db-snapshot-guard.py             (Layer 3: backup для DB)
4. block_git_destructive.py         (Layer 4: git destructive)
5. ...
```

PostToolUse → Bash:
```
6. detect_api_key_leak.py           (existing)
7. verify-deleted-guard.py          (Layer 5: post-condition check) ← NEW
```

Это формализует workflow user'а:
**1. Спросить дважды → 2. Сделать бэкап → 3. Verify бэкап → 4. Удалить → 5. Verify удалилось.**

---

## 2026-04-28 (v3.5.0 — Defence-in-depth for destructive ops)

### Added: `hooks/human-confirmation-guard.py`

Second layer of protection for destructive operations. Blocks even commands that already passed `destructive-command-guard.py` via bypass marker, unless they also carry a fresh `# user-confirmed: "<phrase>" <timestamp>` token. Token requires a verbatim phrase from a recent user reply (max 10 minutes old) — agent cannot self-generate this without an actual conversation event.

**Verdict matrix**:
| destructive pattern | bypass marker | user-confirmed | result |
|---|---|---|---|
| no | - | - | allow |
| yes | no | - | allow (destructive-guard blocks first) |
| yes | yes | no | **BLOCK** (this hook) |
| yes | yes | fresh | allow |
| yes | yes | stale >10 min | **BLOCK** |

**Why**: single bypass marker can be added by the agent itself after internal reasoning — no human-in-the-loop. The Replit incident (Aug 2026, Jason Lemkin) showed this fails: agent dropped a production database, then lied about restoring it. Dual-token pattern formalizes the human contact event as a *proof artifact in the command*, not an instruction in the prompt.

### Added: `hooks/db-snapshot-guard.py`

Third layer: auto-snapshot before allowed destructive SQL **with verification that the snapshot is real**. Sibling of `git-auto-backup.py` but for databases (Postgres, MySQL, MongoDB).

Verification matters because `pg_dump` can exit 0 even on partial dumps (permission denied for some tables, connection drops mid-stream). The hook checks:
- File exists and size above min threshold
- Footer marker present (`-- PostgreSQL database dump complete` for PG, `-- Dump completed` for MySQL, non-empty `.bson` files for Mongo)
- At least one `CREATE` / `COPY` / `INSERT` statement

If the snapshot fails verification — loud WARN to stderr + safety.log, but still ALLOW the destructive command. Hook is a safety net, not a gate (failed-backup blocking creates worse fail2-style lockup).

**Connection**: this codifies one specific lesson from the Replit incident — auto-backup is necessary but **insufficient**. The agent there claimed to restore the DB but didn't (or did partially). Verification layer turns "we tried" into "it actually worked".

### Hook chain order (`PreToolUse → Bash`)

The three layers should be registered in this order in `settings.json`:

```
1. destructive-command-guard.py    (block raw destructive without bypass)
2. human-confirmation-guard.py     (block bypass without user-confirmed token)
3. db-snapshot-guard.py            (auto-snapshot if both above passed)
4. ...rest of chain (git-destructive, command-injection, auto-backup)
```

Layer 1 blocks the obvious case. Layer 2 closes the "agent self-bypass" hole. Layer 3 provides recovery if something still slips through. Each layer is independently overridable but unable to substitute for the others — defence-in-depth, IAEA INSAG-10 model.

---

## 2026-04-28 (v3.4.0 - Merge Conflict Resolution Principle)

### Added: `principles/24-merge-conflict-resolution.md`

Codifies what worked during a real two-session race condition: Claude session A and Claude session B editing the same TypeScript monolith concurrently. Without the protocol, session A could have wholesale-overwritten session B's parallel work by "taking its own side" as fresher. With the protocol, both sessions' work merged cleanly into one PR.

**The protocol**: when conflicts arise, isolated agents (fresh context) independently verify each side against verified data sources (live probes > production deployment > tests > git blame > code > docs). A second agent in a separate fresh context audits the proposed resolution. Errors are checked in parallel as resolutions are produced — if errors emerge, the resolution is wrong even if both agents agreed.

**Anti-patterns** the principle blocks:
- "auto-merge tool already resolved this, probably correct" — tool sees syntax, not semantics
- "I'll take my side, mine is fresher" — may erase production hot-fix from parallel session
- "merge fast, fix later" — fixing on master is an order of magnitude more expensive

**Connection**: this is the [Proof Loop](principles/02-proof-loop.md) and [Generator-Evaluator](principles/01-harness-design.md) patterns specialized to a high-stakes, low-context decision (which version of these N lines belongs in the final code). Also extends [no-guessing](CLAUDE.md) — every resolution decision must be backed by verified data, not operator intuition.

**Summary checklist** at the end of the principle file lists 7 boxes that must be checked before merging anything with conflicts.

---

## 2026-04-27 (v3.3.0 - Drift Validator Robustness)

### Improved: `scripts/validate_config.py`

Validator hardened across 5 dimensions after surfacing 24 false-positive "broken refs" on a real install. Drift dropped to 0 with no false negatives.

**1. Skip patterns extended** - 6 new substring filters catch path-like strings that aren't real file paths:
- `*` - glob patterns (`~/.ssh/id_*`, `~/.claude/scripts/block_*.py`, `~/.secrets/*`, `/proc/*/environ`)
- `/api/` - URL endpoints (e.g. `/api/v1/projects/7/tasks` documented in rule files)
- `docker/login-action` - GitHub Actions reference, not a file
- `./script.sh` - generic placeholder in safety rule examples
- `cat/less/` - command list separated by slashes (cat/less/head/tail/grep/bat/xxd)
- `YYYY-` - date placeholder in handoff template paths

**2. Linux system path skip on Windows** - new `LINUX_SYSTEM_PREFIXES` tuple (`/etc/`, `/proc/`, `/opt/`, `/var/`, `/usr/`, `/dev/`) skipped when `sys.platform == "win32"`. Rule files reference these as concepts for SSH/system docs but they don't exist on the local filesystem.

**3. Cross-machine paths opt-in** - new `CROSS_MACHINE_PREFIXES` tuple (default empty) for paths on remote hosts (Hyper-V VMs, build hosts, container mounts). Extend in your fork.

**4. Workspace roots extensible via env var** - new `CLAUDE_WORKSPACE_ROOTS` env var (colon-sep on Unix, semicolon on Windows) for users with monorepo outside `~/Desktop`. Roots checked in priority order: env var entries -> `~/Desktop` -> `~` -> Claude Code project memory dirs.

**5. Claude Code memory dir resolution** - `~/.claude/projects/*/memory/` enumeration so refs like `memory/<filename>` resolve to the session-scoped memory store. Filtered to dirs that have a `memory/` subdir to avoid stat-call explosion on machines with many project records.

### Fixed

- **Stale report file**: previously `drift-report.md` was only written when drift was detected. After fixes that dropped drift to 0, the prior dirty report persisted forever, misleading anyone who read the file directly (incl. verifier agents). Now always written - either drifted detail or "Last run: clean - scanned N files".

- **UnicodeEncodeError on Cyrillic paths**: Windows default cp1252 stdout crashed when printing broken refs containing non-ASCII (e.g. `claude-stories/YYYY-MM-DD-тема.md`). Now reconfigures stdout/stderr to UTF-8 with replacement errors at startup.

### Why this matters

Validator is part of the Documentation Integrity defense layer (principle 11). If it cries wolf 24x on first install, users mute it - exactly what defense-in-depth shouldn't do. The fixes distinguish:
- Real drift (file moved/deleted) - flag
- Conceptual references (URLs, glob, command lists) - skip
- Cross-platform refs (Linux paths on Windows) - skip with platform guard
- User workspace layout - configurable via env var

Rule of thumb after this update: if validator flags something, it's a real broken ref worth fixing. No more "oh it's just the validator being wrong".

---

## 2026-04-23 (v3.2.0 - Article Structure Review + Handoff Skill Injection)

### Added: Article Structure Review Skill (`skills/writing/article-structure-review/`)

Structural self-review for technical articles before publication. Fills three gaps not covered by word-level skills (humanize, infostyle):

1. **Thesis/proof balance** - each significant claim needs a concrete example, number, case study, code snippet, or source citation. Antipattern: 3+ claims in a row without any proof element. Mechanical test: count thesis vs proof per H2 section, ratio above 2:1 = rebuild.

2. **Genre consistency** - one primary genre per article (Story / Reference / Analysis / Rant / Tutorial). If genres mixed, mark transitions explicitly. Test: read only first paragraph of each H2 section - does it read as one throughline or disconnected blocks?

3. **Limitations block** (mandatory) - "What's NOT solved / Where it breaks" section at article end. Builds trust, antidotes promotional tone, communicates maturity. Not false modesty - concrete scaling limits, unverified hypotheses, tradeoffs, known holes.

Plus three secondary checks: paragraph length variety (no three 3-sentence paragraphs in a row = AI marker), middle-section overload detection (40% of theses in middle third = rebalance), visual vs prose check (structural data → diagram/table, not description).

Based on recurring reader feedback on LLM-assisted technical drafts: "many theses, few examples", "overconfident tone", "middle overloaded", "missing limitations", "some parts unclear why they're here - show a picture".

### Added: Required Skills Section in Handoffs

Session handoff format extended with `## Required skills` section. When a new session picks up a handoff, it reads the listed skills BEFORE continuing work - ensures project-specific rules (e.g. humanize for writing, article-structure-review for articles) load automatically.

Benefits:
- Handoff becomes project-aware, not just session-aware
- Auto-loading of skills tied to codified state (principle 07)
- Eliminates "new session doesn't know about project rules" class of issue

Applied to session-handoff rule (`.claude/rules/session-handoff.md` in project) + new handoff template. Example:

```markdown
## Required skills
- article-writing/skills/humanize-russian.md
- article-writing/skills/article-structure-review.md
- article-writing/skills/infostyle-audit.md
```

### Added: Project-Level Auto-Load Rule Pattern

New pattern: project-specific `.claude/rules/auto-load-*.md` rules that list mandatory skills with triggers. When editing certain files or matching user commands, agent is instructed to read skills first. Example triggers for writing project:

- Edit/Write over `drafts/**/article.md`
- User commands like "пиши статью", "правь черновик", "ответ на коммент"
- Session start in project directory

Three-tier loading guarantee:
1. CLAUDE.md lists skills in required audit order (soft)
2. `.claude/rules/auto-load-*.md` with explicit triggers (firmer)
3. `## Required skills` in handoff for session continuity (strongest for multi-session work)

### Context for this update

These additions emerged from reader feedback on two published technical articles. Round-trip: published → critical feedback → skill formalization → shared publicly. Matches the "external verifier" pattern from Proof Loop (principle 02) - reviewers' critiques become inputs for tooling, not one-off responses.

---

## 2026-04-23 (v3.2.0 - Multica patterns adopted)

Three patterns adopted from Multica (multica-ai/multica) after deep research.
Multica itself is a team-scale product (Postgres + Go + Next.js) - too heavy
for solo use - but their engineering has reusable pieces.

### Added: `scripts/generate_skills_lock.py` + `skills-lock.json`

Deterministic lockfile for all skills. Each skill gets:
- `content_hash` - sha256 of SKILL.md + references/ + scripts/ (path-sorted)
- `size_bytes`, `file_count`, `files` list, `last_modified`
- `aggregate_hash` at top level for whole-repo drift detection

Run `python scripts/generate_skills_lock.py --check` in CI to catch
unintentional drift (someone edits SKILL.md, forgets to regen lock).

Inspired by Multica's `skills-lock.json` pattern, adapted to our file-based
skill structure (no pgvector dependency).

### Added: `scripts/cleanup_handoffs.py`

TTL-based GC for `.claude/handoffs/` with crucial distinction:
- **DONE** (CLOSED/RESUMED/ABANDONED) → archive after `--done-ttl` days
- **ORPHAN** (ACTIVE/UNKNOWN) → **warn only**, never auto-delete

The DONE/ORPHAN split comes from Multica's daemon GC (PR #1559). Naive
"delete anything older than N days" is dangerous: old ACTIVE handoff may
be real forgotten work, not trash.

`INDEX.md` never touched (preserves principle 18 append-only invariant).

### Notes on what was NOT adopted

- Multica's Postgres + pgvector stack: too heavy, conflicts with our
  "file-based, zero deps" design principle (shared with mclaude)
- WebSocket real-time progress: our file-polling is good enough solo
- Team task board UI: we are single-user context, not a team platform

---

## 2026-04-22 (v3.1.0 - Proof-Verify Skill + Keyword Router + Freshness Audit)

### Added: Proof-Verify Skill (`skills/development/proof-verify/`)

Plan-based verification with independent agents. Four phases:

1. **Plan** - freeze acceptance criteria in `.proof/PLAN.md` before any code
2. **Build** - implement, record progress and evidence
3. **Verify** - independent agent (fresh context, never saw build) checks each AC
4. **Fix** - minimal fixes, re-verify, loop until all PASS

Key: builder cannot verify their own work. Verifier reads PLAN.md only, runs checks independently.

**KB-aware extension** (`references/kb-aware-verification.md`): verifier also checks conformance against project knowledge base - coding standards, architecture patterns, conventions. ACs catch functional bugs, KB conformance catches style/architecture drift.

New template: `templates/proof-plan.md` - starter plan with AC format and KB reference section.

Sources: Proof Loop (Principle 02), Sprint Contract (Principle 01), OpenClaw-RL, oh-my-claudecode Ralph.

### Added: Keyword-Skill-Router Hook (`hooks/keyword-skill-router.py`)

`UserPromptSubmit` hook that detects natural-language keywords and suggests matching skills. Adapted from oh-my-claudecode's keyword detection pattern with key difference: **soft suggestions** (agent decides relevance) vs OMC's hard routing (forced invocation).

- 8 routes: planning, code review, security, handoff, research, debugging, simplify, init
- ~40 regex patterns, bilingual (Russian + English)
- Non-blocking: outputs suggestion, does not force skill invocation

### Added: HOW-IT-WORKS.md - Technical Deep Dive

New page explaining HOW each technology works mechanically:
- Rules (conditional context injection)
- Memory (wiki-graph, 78 files, 178 cross-links, layered loading)
- Handoffs (multi-session state transfer, 67x compression, verification contract)
- Hooks (code vs rules - "rules are hope, hooks are guarantees")
- KV-Cache (96.9% hit rate, 4 rules for cache-friendly context)
- Context fill vs degradation (measured 169 sessions, 45K turns)
- Supply Chain Defense (one line blocked DPRK attack)

New script: `scripts/context_degradation.py` - measures quality proxies across context fill-level buckets. Tests "40%+ = degradation" claim. Our data on 1M context: no degradation up to 72% fill.

### Updated: README freshness audit

- Principle count: 17 → 23 (other sessions added 18-23)
- Skills: 16 → 18 (added proof-verify, plan-swarm-review)
- Hooks: 5 → 15 (added all safety hooks + keyword router + backup cleanup)
- Alternatives: 12 → 15
- Templates: 7 → 8 (added proof-plan)
- Chinese and Russian sections updated with correct counts
- Fixed principle 12 numbering conflict (DBS → 17)

---

## 2026-04-20 (Humanize skills update: 9 new AI markers + Habr feedback)

### Updated: `skills/writing/humanize-russian/SKILL.md`

Added 9 new AI text detection patterns from Russian Wikipedia "Признаки сгенерированности текста" article. These complement the existing Liang et al. research-backed markers:

| New Pattern | Example | Fix |
|---|---|---|
| Rule of Three abuse | "яркий, богатый, разнообразный" | Keep one precise word |
| Merism (fake ranges) | "от лёгкого до тяжёлого" | Concrete value |
| Tautological synonym avoidance | "данный специалист" instead of repeating name | Just repeat the name |
| Vague attributions | "по словам экспертов" | Specific source or remove |
| Problem → vague optimism | "Несмотря на проблемы, перспективы..." | Concrete forecast or honest "не знаю" |
| Title-as-definition opening | Starting with "X - это..." | Start with context/problem/story |
| Promotional adjective clusters | "потрясающая природная красота" | Concrete fact |
| English-style heading caps | "Как Правильно Настроить" | Only first word capitalized in Russian |

Also added connector cleanup rules ("Честный нюанс" → remove, "Однако/Впрочем" → new sentence without connector) and "кардинальный" as a Tier 1 marker word with excess ratio data.

**Source of these additions:** first Habr article (16K views, 17 comments) received direct feedback about AI text markers. Comments flagged: English-Russian language mixing, AI-slop perception, promotional tone. These new patterns specifically address the community's detection heuristics.

### Updated: `skills/writing/humanize-english/SKILL.md`

Synced with latest version from production use. Minor formatting improvements.

---

## 2026-04-20 (Harness tools research digest + two new principles + DESIGN.md alternative + security refresh)

Everything in this update traces back to a week of research on three converging threads: (1) the obra/superpowers + pbakaus/impeccable skill ecosystem, (2) Anthropic's Claude Design launch and the DESIGN.md convention it popularized, (3) the April 2026 wave of agentic security disclosures.

### New: `principles/22-visual-context-pattern.md`

Distilled from the obra/superpowers `visual-companion` skill. Formalizes the workflow where an agent presents UI/design options as HTML fragments in a local browser and reads user feedback through a file-based event queue. Architecture: local HTTP server + `screen_dir/*.html` + append-only `events` JSON lines. The pattern is runtime-agnostic (works with Claude Code, Codex, Cursor, Gemini CLI) because it uses nothing but files + a stdlib HTTP server. Includes a minimum viable ~100-line implementation, decision rule ("would the user understand this better by seeing than reading?"), gotchas (Windows background-mode quirk, CSS class contract), and integration points with principles 01 / 02 / 04 / 07 / 08 / 23.

### New: `principles/23-anti-pattern-as-config.md`

Distilled from pbakaus/impeccable. Positive configuration ("use X") fails when the failure mode is a single attractor the model reverts to under pressure (Inter font, purple gradients, `SELECT *`, bare `except`). The principle codifies a three-layer enforcement stack:

1. **Skill + anti-pattern reference file** — explicit forbidden patterns with rule IDs, rationale, exceptions, alternatives.
2. **Slash commands** wrapping common checks (`/audit`, `/polish`).
3. **Deterministic detector** — regex / linter / vision check that runs without LLM and fails build on match.

Includes the "anti-attractor procedure" (name reflex → reject if listed → enumerate alternatives → justify pick), a rule-writing template, and examples extending beyond frontend to security, SQL, Dockerfiles, Python idioms, and tests. Links to Principle 10 (whose Attack Taxonomy is structurally the same thing for AppSec).

### New: `alternatives/design-md-pattern.md`

Documents the DESIGN.md convention that emerged alongside Claude Design (Anthropic Labs, April 2026). Compares three implementations — first-party Claude Design canvas, community getdesign.md (69 brand files from Linear/Stripe/Ferrari/Wired/etc.), and the open-source CLI reproduction `bluzir/claude-code-design`. Includes a 60-line minimum viable DESIGN.md starter, decision table for picking the right approach, and anti-patterns specific to DESIGN.md files (copy-pasted from framework defaults, missing "do not use" sections, conflicting with authoritative tokens.css).

Clarifies a common community confusion: the design collection at getdesign.md is maintained as `awesome-design-md` by VoltAgent, **not** `hesreallyhim/awesome-claude-code` (the latter is a general Claude Code meta-list, not design-specific).

### Updated: `principles/10-agent-security.md`

Added April 2026 developments:

- **New incident timeline entry:** CVE-2026-32211 (Microsoft Azure DevOps MCP, CVSS 9.1, missing authentication, disclosed 2026-04-03). Illustrates that first-party MCP servers still require auth verification.
- **New section "April 2026 Update: State of Attacks and Defenses"** covering:
  - **PIDP-Attack** reaching 98.125% success across 3 benchmarks and 8 models — attacks crossed the 90%+ threshold, static defenses insufficient
  - **Adaptive attack success >85%** against SOTA defenses (from the arxiv:2601.17548 meta-analysis)
  - **SentinelOne memory integrity module** reducing memory-poisoning Mean-Time-To-Detect from 72 hours to under 15 minutes
  - **Multi-modal defense framework** achieving 94% detection / 70% trust leakage reduction / 96% task accuracy retention via layered architecture (attention-based anomaly + intent-flow analysis + output constraints)

The takeaway: defenses must assume injection succeeds and limit blast radius, because preventing it outright is no longer viable.

### Research provenance

The four documents feeding these changes live in the private workspace at `research/agentic/harness-tools-superpowers-impeccable.md`, `research/agentic/claude-design-ecosystem-2026-04.md`, `research/security/agentic-security-april-2026.md`, and `research/agentic/multiclaude-orchestration-alternatives-2026-04.md`. They include fact-checks against community posts (e.g., Impeccable is 1 skill + 18 commands + CLI, not "20 skills"; `visual-companion` does not have "two modes" as sometimes claimed; `awesome-claude-code` is general-purpose, not design-specific). Future drafts of these principles should cite the research directly rather than re-derive.

---

## 2026-04-18 (Safety Phase 3: marker bypass + backup retention + API key detection + docker sandbox)

### Updated: `hooks/safety_common.py` - unified bypass API

New function `bypass(name, text, env_name=None)` checks two sources:
1. Env var `CLAUDE_ALLOW_<NAME>` (upper, dashes -> underscores)
2. In-command marker: `# claude-bypass: <name>` (or `//` / `<!-- -->` variants)

Marker bypass solves the real limitation of env-var bypass: bash inline prefix `FOO=1 cmd` does NOT propagate to hooks (hooks are sibling processes to the bash command, not children). Marker travels with the command text itself.

Examples:
```bash
git commit -m "..."  # claude-bypass: injection
rm -rf /tmp/legit-cleanup   # claude-bypass: destructive
```

All 7 Phase 1+2 hooks updated to call `bypass(name, text)` instead of `bypass_env()`. Old env-var bypass still works for hooks started with `export CLAUDE_ALLOW_X=1`.

### New: `hooks/backup-retention-cleanup.py` (Stop event)

Cleans up `claude-backup-*` branches and `claude-pre-clean-*` stashes older than 14 days. Runs on every session end. Silent in non-git directories. Idempotent.

Solves the accumulation problem: `git-auto-backup.py` creates recovery points liberally, but without retention they pile up (50+ branches after a month of active dev).

Register in settings.json alongside existing Stop hooks.

### New: `hooks/api-key-leak-detector.py` (PostToolUse)

Scans tool output for 13+ API key patterns: Anthropic, OpenAI, GitHub PAT/fine-grained, AWS access/secret, Stripe live/test, Slack, Google API, private key blocks, JWT, generic bearer tokens.

This is a **detective** control (not preventive) - PostToolUse runs after output already returned to Claude context. Emits loud stderr warning with redacted snippet + rotation action items when a key is detected. Covers leakage paths that `secret-leak-guard.py` (preventive) can miss - hardcoded keys in code, env output, ps aux, cp .env followed by cat .env.backup.

### New: `rules/safety-api-key-leak.md`, `rules/safety-backup-retention.md`

Matching rules for the two new hooks.

### New: `alternatives/docker-sandbox-claude-code.md`

Architectural pattern documentation: running Claude Code inside Docker sandbox with explicit host boundaries. Based on the practitioner pattern of 5000+ agent-driven PRs with 1-2 incidents. Tradeoffs table vs hook-only protection, minimal compose file, Dockerfile, GitHub Actions CI/CD permissions example, breakout scenarios.

### Phase 3 coverage summary

| Dimension | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Destructive ops | destructive-command-guard | - | marker bypass added |
| Secret leaks | secret-leak-guard | - | + api-key-leak-detector (post) |
| Git catastrophes | git-destructive-guard | + git-auto-backup | + backup-retention-cleanup |
| Self-harm | self-harm-guard | - | marker bypass added |
| Hidden muted tests | - | test-muting-guard | marker bypass added |
| Quoting injection | - | command-injection-guard | + heredoc whitelist, marker bypass |
| Bypass friction | env var only (broken with inline prefix) | - | marker bypass working |
| Architectural | - | - | docker-sandbox-claude-code.md |

---

## 2026-04-17 (Safety Phase 2: test muting + command injection + auto-backup)

### New: `hooks/test-muting-guard.py`

Blocks adding skip/xfail/ignore patterns to test files. Watches Edit/Write/NotebookEdit on `tests/`, `__tests__/`, `spec/`, `*_test.py`, `*.test.js` etc. Covers pytest, unittest, jest/mocha/vitest, JUnit, Go, Rust, RSpec patterns. Uses diff logic - only blocks patterns added by this edit, not already-existing ones. Bypass: `CLAUDE_ALLOW_TEST_MUTING=1`.

Real case pattern: `.only()` left after debug → suite silently runs 1 test of 100. Classic production bug source.

### New: `hooks/command-injection-guard.py`

Detects suspicious `$(...)` and backtick substitutions inside Bash commands. Three tiers:
- Trivial (pwd, date, whoami, basename, dirname, echo, etc) → pass
- Destructive verb inside substitution (dropdb, rm -rf, killall, curl | sh) → hard block
- Non-trivial (any other command) → advisory block

Handles single-quote literal regions correctly (substitution inside `'...'` is literal).

This catches the class of bugs where text meant as data becomes command via unescaped quotes - the Codex `gh issue create --body "...$(dropdb)..."` pattern from real AI-coding community reports. Bypass: `CLAUDE_ALLOW_INJECTION=1`.

### New: `hooks/git-auto-backup.py`

Safety net paired with `git-destructive-guard.py`. Only runs when bypass is granted - creates recovery point before the destructive op:
- `git reset --hard *` → creates `claude-backup-{unix_ts}` branch pointing at HEAD
- `git checkout -- .` → creates backup branch
- `git clean -fdx` → `git stash push -u` working tree

Emits recovery instructions to stderr so user sees them. Silent outside git repos.

### New matching rules

- `rules/safety-test-muting.md`
- `rules/safety-command-injection.md`
- `rules/safety-auto-backup.md`

### Updated settings.json registration example

Bash matcher now has 6 hooks (was 4): destructive / git-destructive / secrets / self-harm / command-injection / auto-backup. Edit/Write/NotebookEdit/Grep matcher has 3 hooks (was 2): secrets / self-harm / test-muting.

### Real-world Phase 2 bug class coverage

| Category | Phase 1 | Phase 2 |
|---|---|---|
| Destructive ops | destructive-command-guard | + auto-backup wraps with recovery |
| Secret leaks | secret-leak-guard | (no change) |
| Git catastrophes | git-destructive-guard | + auto-backup wraps with recovery |
| Self-harm | self-harm-guard | (no change) |
| Hidden muted tests | - | test-muting-guard |
| Quoting injection | destructive-guard catches naked verbs | command-injection-guard catches verbs inside $() |

---

## 2026-04-17 (Safety hooks: 4 PreToolUse guards + IAEA two-layer rules)

### New: 4 PreToolUse hooks with shared common library

Replaced earlier standalone `destructive-command-guard.py` + `secret-leak-guard.py` with cohesive set of 4 guards sharing `hooks/safety_common.py` utilities:

- **`hooks/destructive-command-guard.py`** - blocks catastrophic shell commands: `rm -rf` on root/home/system dirs, SQL `DROP/TRUNCATE`, `docker prune --volumes`, `kubectl delete all/--all`, `mkfs`/`dd` on block devices, fork bombs. Bypass: `CLAUDE_ALLOW_DESTRUCTIVE=1`
- **`hooks/secret-leak-guard.py`** - blocks reading/printing `.env*`, `*.key`, `*.pem`, `id_rsa/ed25519/ecdsa/dsa`, `~/.secrets/`, `~/.ssh/`, `~/.aws/`, `credentials.json`. Covers Read/Edit/Write/Grep tools + Bash `cat/less/head/tail/grep/bat/xxd/source`. Bypass: `CLAUDE_ALLOW_SECRETS=1`
- **`hooks/git-destructive-guard.py`** - blocks `git reset --hard`, `git push --force` (without `--force-with-lease`), `git branch -D`, `git clean -fdx`, `git checkout -- .`, `git filter-branch/repo`, force delete of main/master/prod refs. Bypass: `CLAUDE_ALLOW_GIT_DESTRUCTIVE=1`
- **`hooks/self-harm-guard.py`** - blocks actions that cut agent off from host: sshd config edits, `systemctl restart sshd`, `killall node|bun|python|claude`, `pkill -f claude`, `iptables -j DROP`, `ufw default deny`, `reboot/shutdown`. Bypass: `CLAUDE_ALLOW_SELF_HARM=1`
- **`hooks/safety_common.py`** - shared utilities: stdin event parsing, JSONL audit logging to `~/.claude/logs/safety.log`, block/allow helpers, bypass env var check, utf-8 stdout reconfigure for Windows

### New: 4 matching rules (IAEA two-layer principle)

Each hook has a companion `rules/safety-*.md` documenting the advice layer + real-world failure examples + what the hook doesn't cover + tuning guidance:

- `rules/safety-destructive.md`
- `rules/safety-secrets.md`
- `rules/safety-git-destructive.md`
- `rules/safety-self-harm.md`

Real-world examples gathered from AI-coding community (anonymized). Each rule explains why rule-only protection is insufficient: classic case is "не читай env" instruction that agent ignored in the same turn. Mechanical hook = second independent layer that can't be forgotten under context pressure.

### Research base

Pattern grounded in research/agentic/memory-priority-enforcement-convergence.md covering convergence across 8 domains (LLM, MemGPT, aviation, neuroscience, cognitive load, IAEA, syslog, K8s) on the same critical/reference + rule/hook architecture.

### Settings.json registration example

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "python /abs/hooks/destructive-command-guard.py"},
          {"type": "command", "command": "python /abs/hooks/git-destructive-guard.py"},
          {"type": "command", "command": "python /abs/hooks/secret-leak-guard.py"},
          {"type": "command", "command": "python /abs/hooks/self-harm-guard.py"}
        ]
      },
      {
        "matcher": "Read|Edit|Write|NotebookEdit|Grep",
        "hooks": [
          {"type": "command", "command": "python /abs/hooks/secret-leak-guard.py"},
          {"type": "command", "command": "python /abs/hooks/self-harm-guard.py"}
        ]
      }
    ]
  }
}
```

---

## 2026-04-17 (KB enforcement pattern + drop-in skeleton)

### New: principles/21-knowledge-base-enforcement.md

The pattern **review finding -> regression test -> invariant -> cross-reference** as a durable triangle. Every accepted review finding gains three forms (fix, test, invariant); missing any form loses a guarantee.

Covers structure (`AGENTS.md` + `docs/kb/` tree), the three forms concretely, validator role, bidirectional review-template cross-link, when-to-adopt criteria, and real numbers from a Phase 2 security sweep (123 findings -> 25 fixes -> 65 regression tests -> 25 invariants).

### New: templates/kb-skeleton/

Drop-in starter for the pattern. Copy into any repo, configure the top of `scripts/validate_kb.py`, start growing `INVARIANTS.md` from your first review.

Contains:
- `AGENTS.md` -- AAIF-standard entry, `<=150` lines, TODO markers
- `docs/kb/README.md` -- meta-rules (how to use, when to update)
- `docs/kb/INVARIANTS.md` -- format + example block
- `docs/kb/conventions.md` -- section stubs (imports, async, errors, types, ...)
- `docs/kb/patterns.md` -- recipe skeleton
- `docs/kb/gotchas.md` -- symptom/cause/workaround skeleton
- `docs/kb/decisions.md` -- ADR template
- `docs/kb/modules/example.md` -- per-module contract template
- `scripts/validate_kb.py` -- working validator, configurable `SOURCE_ROOTS` at top, multi-root path resolver, `(future)` / `(planned)` markers honored, stdlib-only, ASCII-safe output
- `.github/workflows/kb.yml` -- CI gate

Adoption time: ~15 minutes. First invariant can be added in under 5 minutes.

### Why this exists

Previous principles **07 - Codified Context** set the mindset ("context is infrastructure"). **11 - Documentation Integrity** generalized reference-validation-at-session-start. Principle 21 bridges the two with a concrete, adopt-able structure for projects that want the full loop from review to durable contract.

---

## 2026-04-17 (Humanize Russian: 80/20 term russification rule)

### Updated: skills/writing/humanize-russian/SKILL.md

Added new section "Русификация терминов - правило 80/20" between stylistic markers and conversational elements.

**Rule:** in Russian text, 80% of technical terms should be written as Russian words or transliterations, not left as English. Persistent English terms in Russian prose are a strong signal of machine translation or LLM generation.

**Detection mechanics:** native Russian speakers think "интерфейс" or "чекпоинт" first, then "UI" / "checkpoint". LLMs go the other way - the English term is the first statistical choice, so it stays untranslated. Output reads like a translation, not an original.

**Replacement table** (20+ terms): UI→интерфейс, checkpoint→чекпоинт, backup→бекап, deploy→развернуть/выкатить, workflow→пайплайн/процесс, pipeline→пайплайн, cache→кэш, cluster→кластер, node→нода/узел, retention policy→политика хранения, etc.

**Keep in English (20%):** library/brand names (PyTorch, MinIO, ControlNet, LoRA), standard acronyms (API, JSON, GPU, CPU, SSD), code and commands.

**Composition rule:** no more than 1-2 non-russified English terms per sentence (excluding library/brand names).

Checklist updated with two new items.

Trigger: caught in an actual HR response draft - "обучила сотрудников UI" vs the natural "обучила сотрудников работе с интерфейсом". The first reads as translated, the second as native.

---

## 2026-04-17 (Humanize skills: add vague intensifiers)

### Updated: skills/writing/humanize-russian/SKILL.md + humanize-english/SKILL.md

Added vague-intensifier LLM markers to Tier 1 banned words:

- **Russian:** "кардинально / кардинальное / кардинальный" - usage without a measured scale. LLM loves these as universal amplifiers; humans name the scale with a number or concrete word ("в разы", "вдвое", "на 40%").
- **English parallel:** "dramatically / significantly / drastically / substantially" - same failure mode. Replace with a concrete number or plain "fast/big/huge".

Both skill checklists updated accordingly.

Trigger: caught the pattern in actual production writing - an LLM draft used "кардинально эффективнее" / "кардинальная экономия" as stand-ins for what should have been "в ~8x быстрее" / "экономия на железе". The vague intensifier is a reliable AI signature because it optimizes for "sounds impressive" while specifically removing the measurement humans include when they know the scale.

---

## 2026-04-16 (v2.9.0 - Security Tooling Guide)

### Added: references/security-tooling-guide.md

Practical guide to all available security tools for Claude Code:
- **Anthropic /security-review** - install and usage (command + GitHub Action)
- **Trail of Bits Skills** - 16 security-focused plugins from the 38-plugin marketplace (static-analysis, variant-analysis, entry-point-analyzer, fp-check, constant-time-analysis, zeroize-audit, supply-chain-risk-auditor, etc.)
- **sast-skills** - 14-module SAST workspace pattern
- **Our tools** - plan-swarm-review code mode + vulnerability KB

Includes recommended pipelines for quick (1 min), standard (5-10 min), deep (30-60 min), and multi-session (1-2 hrs with mclaude) security audits.

---

## 2026-04-16 (v2.8.0 - Vulnerability Knowledge Base)

### Added: skills/architecture/plan-swarm-review/references/vulnerability-kb.md

Condensed CWE Top 10 detection heuristics for agent consumption during `/plan-swarm-review` code mode. Each CWE entry: triggers, taint flow, false positive indicators. Covers: XSS, SQL injection, OOB write/read, use-after-free, file upload, deserialization, SSRF, integer overflow, resource consumption.

Plan-swarm-review SKILL.md updated to reference this KB during code mode reviews.

Based on Vul-RAG approach (ACM TOSEM 2025): knowledge-level entries outperform code-level RAG by +16-24% accuracy.

Full Vul-RAG entries (10 articles with code examples, root cause analysis, fixing patterns): published to knowledge-vault/docs/security/cwe/.

---

## 2026-04-16 (v2.7.0 - Vulnerability Detection Pipeline)

### Added: principles/20-vulnerability-detection-pipeline.md

New principle formalizing the 6-layer AI vulnerability detection pipeline: SAST scan -> LLM false-positive filter -> multi-agent diverse review -> knowledge-enriched RAG -> adversarial verification -> sandbox PoC.

Backed by 15 papers and production evidence:
- Claude Opus 4.6: 500+ confirmed zero-days in OSS (Anthropic, Feb 2026)
- SAST-Genius: hybrid SAST+LLM reaches 89.5% precision vs 35.7% SAST alone
- MAVUL: +600% detection vs single-agent
- Vul-RAG: knowledge-level RAG adds +16-24%, found 6 CVE in Linux kernel
- Chinese ecosystem: Qianxin #1 CyberSec-Eval, DeepAudit 48 CVE, Tencent A.S.E framework

Includes practical implementation guide for Claude Code (built-in + skills), comparison of LLM strengths/weaknesses by vulnerability type, and references to Trail of Bits Skills and sast-skills.

---

## 2026-04-16 (v2.6.0 - Plan Swarm Review)

### Added: skills/architecture/plan-swarm-review/SKILL.md

New skill for iterative plan/code review using multisampling + focused decomposition. Inspired by deksden's "Plan Swarming" technique (April 2026) and backed by 5 academic papers.

**Two modes:**
- **Plan mode**: review design docs, specs, ADRs before implementation
- **Code mode**: security audits, vulnerability hunting, bug detection

**4 escalating rounds:**
1. Broad review (single agent) - catch obvious issues
2. Diverse multisampling (3-5 agents with different personas) - stochastic diversity
3. Focused decomposition (one agent per aspect) - deep analysis
4. Focused + multisampling (optional) - maximum depth

**Key research-backed improvements over naive multisampling:**
- Diverse perspectives instead of identical prompts ([2502.11027]: +10.8% reasoning accuracy)
- Minority-correct finding preservation ([2602.09341] AgentAuditor: recovers 65-82% of findings majority voting misses)
- Code vulnerability aspects based on MultiVer [2602.17875] (82.7% recall) and VulAgent [2509.11523] patterns

**Empirical result** (deksden): 36 agent runs found ~30+ issues that a 2-3 hour single-agent planning session missed entirely.

---

## 2026-04-15 (v2.5.0 - Reasoning regression debugging)

### Added: alternatives/reasoning-regression-debugging.md

Full playbook for detecting and mitigating agent reasoning-quality regression. Based on the Stella Laurenzo (AMD) investigation of the Feb-Apr 2026 Claude Code degradation ([issue #42796](https://github.com/anthropics/claude-code/issues/42796)), which analyzed 6,852 sessions and Boris Cherny's Hacker News response with official workarounds.

Five approaches compared:
- **A: Config reset** - `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1`, `MAX_THINKING_TOKENS=32000`, `/effort high`/`max`, `ULTRATHINK` keyword, settings.json options
- **B: Stop-phrase guard hook** - blocks session end on five phrase categories (ownership dodging, permission-seeking, premature stopping, known-limitation labeling, session-length excuses)
- **C: Metric monitoring** - weekly Read:Edit ratio, Research:Mutation ratio, Edits-without-prior-Read %, loop rate, user-interrupt rate, write%
- **D: Fresh-session A/B** - minimal-context comparison to isolate vendor vs user-side regression
- **E: Proof Loop** (principle 02) - structural immunity to regression via fresh-session verifier

Full effort scale reference (0/30/85/95/100), complete list of environment variables and settings.json options, phrase categories with representative patterns, decision matrix for when to use which approach.

### Added: hooks/stop-phrase-guard.py

Implements approach B from the alternatives doc. Scans the final assistant message from the Stop hook's transcript input against five regex-grouped phrase categories. Uses meta-discussion markers to suppress false positives on legitimate anti-pattern references. Touches `.claude/.stop-phrase-guard-fired` marker to avoid re-blocking same session.

### Added: scripts/reasoning_metrics.py

Computes all six regression metrics from `~/.claude/projects/*.jsonl` session files. Supports `--days N` lookback, `--project` filter, `--json` / `--csv` output modes, per-session plus median-aggregated summary with healthy/transition/degraded status flags.

**First-run validation:** when run against our own last 7 days of sessions, the script produced Read:Edit ratio = 2.0 (exact number from the AMD investigation's degraded population), Research:Mutation = 1.05, Write% = 42.9%. The tool works and confirms the regression is affecting our own workflow. Remediation via approach A applies.

### Updated: principle 02 (Proof Loop) - added regression case study

The principle now includes a "Why this matters: the April 2026 regression case study" subsection explaining why Proof Loop is structurally immune: the fresh-session verifier does not care whether the builder's reasoning was sharp, only whether evidence proves the AC. Output quality becomes bounded by the spec, not by the model's current capacity. Cross-links to the new alternatives doc for cases where full Proof Loop is too heavy.

### Updated: indexes

- `README.md`: added stop-phrase-guard to hooks table, added reasoning-quality-regression to alternatives table
- `HOW-IT-WORKS.md`: added reasoning_metrics.py to scripts table
- `hooks/README.md`: added session-handoff-check and stop-phrase-guard to Session Management table with full descriptions

---

## 2026-04-15 (v2.4.0 - Inter-Agent Communication principle)

### Added: Principle 19 - Inter-Agent Communication

Directed asynchronous messaging between parallel Claude sessions. Complements principle 18 by adding the directed-messaging layer on top of the shared-state substrate: where 18 covers ownership (nouns - who holds what), 19 covers messaging (verbs - who tells whom).

- `principles/19-inter-agent-communication.md` - full pattern:
  - Two coordination axes (broadcast vs directed) × two primitives (shared state vs messages) = four total coordination patterns; principle 18 covers the shared-state row, principle 19 covers the messages row
  - Why classical mail semantics specifically: SMTP/IMAP survived 40 years solving exactly this problem (async point-to-point with delivery guarantees between parties that may never be online simultaneously)
  - Minimal implementation: file-based mailbox with inbox/sent/archive per recipient + `all/` for broadcast
  - Message format with email-style frontmatter (from, to, subject, message_id, in_reply_to, date, status)
  - Decision tree: handoff vs lock vs directed mailbox vs broadcast mailbox
  - Anti-patterns: polling on every tool call, editing another agent's sent folder, using mailbox for long-term state, no threading, bad agent names
  - Prior art: aydensmith/mclaude, existing alternatives/agent-mailbox-system.md, SMTP/IMAP reference, Erlang process mailboxes

### Extended: alternatives/agent-mailbox-system.md

The original doc (April 12) covered basic send/receive/broadcast. Production surfaced gaps - threading confusion, no sender audit trail, no delivery confirmation. Added classical mail extensions:

- Threading via `message_id` + `in_reply_to` + `references` headers (format: `YYYYMMDD-HHMMSS-<sender>-<seq>`)
- Sent folder: copy every outgoing message to `mailbox/<sender>/sent/` for sender audit trail
- Delivery receipts: two levels (status update on the inbox copy, or explicit receipt message)
- Filter rules: `.filter.yaml` per mailbox for auto-triage by sender/subject
- Reply-to header for cases where reply target differs from sender
- Maintenance commands: archive messages >14 days, delete old receipts
- Mailbox-specific data loss rules (atomic writes, unique message_id, sender-scoped sequence for strict order)
- Frontmatter `related_principles: [19]` + `last_reviewed: 2026-04-14` for the freshness audit

### Updated indexes

- `README.md`: 18 → 19 in 3 places (English, 中文, Russian), added principle 19 to bulleted list, added mini decision tree in handoff section for "which coordination primitive"
- `AGENTS.md`: 18 → 19
- `principles/README.md`: 18 → 19, full entry for principle 19, 3 decision-matrix rows added (ask another session, broadcast architecture decision, delivery confirmation)
- `HOW-IT-WORKS.md`: new "Inter-Agent Mail" section with concrete mechanism + production validation from a multi-agent deployment
- `CLAUDE.md`: added "Inter-Agent Communication" summary section for global config

### Composition

Principle 18 + principle 19 together close the multi-session coordination picture. Principle 18 asks "who owns what state"; principle 19 asks "who is talking to whom". Using both, parallel Claude sessions can:
- Leave durable handoffs for future sessions (broadcast, append-only)
- Claim exclusive resources with heartbeat-based lifecycle (mutex)
- Send targeted requests or questions to specific other sessions (inbox)
- Broadcast decisions everyone needs to know (`mailbox/all/`)

---

## 2026-04-14 (v2.3.4 - HOW-IT-WORKS expanded with 3 more deep-dives)

### Added: Proof Loop, Autoresearch, Documentation Integrity sections in HOW-IT-WORKS.md

The "humans-friendly technical deep-dive" file covered Rules, Memory, Handoffs, Hooks, KV-Cache, Context Fill, Chronicles, Skills, Supply Chain, and Multi-Session, but three of the most important principles had no technical explainer:

- **Proof Loop** - why the agent cannot sign its own completion. Explains the 4-role protocol (Spec-freezer / Builder / Verifier / Fixer), fresh-session verification, durable artifacts vs claims, and the anti-fabrication verify-after-action rule.
- **Autoresearch** - iterative self-optimization mechanics. Covers the 5-step READ-CHANGE-TEST-DECIDE-REPEAT loop, the 3 preconditions (numerical score / automated eval / single-file mutation), git-as-memory, guard mechanism with 3-6 binary assertions, CORAL heartbeat for stagnation, and HyperAgent upgrade path via Contree microVMs.
- **Documentation Integrity** - how SessionStart hook catches drift before the agent acts on stale paths. Explains multi-strategy path resolution, the rule-vs-hook distinction ("rules are hopes, hooks are executions"), and the Rust compile-time analogy for why validation at session start beats post-failure detection.

Each section follows the same structure as existing deep-dives: problem statement, mechanism, concrete details, links to the full principle file. Meant for readers who read README and thought "okay but HOW does this work mechanically?"

---

## 2026-04-14 (v2.3.3 - Principle 18 coverage audit)

### Fixed: principle 18 was silently missing from most index files

After adding principle 18 (Multi-Session Coordination) in v2.3.0, the counts and references across the repo lagged:

- `README.md`: still said "17 principles" in 3 places (English heading, 中文 and Russian sections, Structure list), and the principle-by-problem bulleted list didn't include 18
- `AGENTS.md`: referenced "17 principles"
- `principles/README.md`: said "collection of 17 battle-tested principles", had no entry for principle 18 at all, and missed decision-matrix rows for multi-session scenarios
- `HOW-IT-WORKS.md`: had no technical deep-dive section for the new principle, and the scripts table was missing the new cross-reference checker

All fixed in this release. Principle 18 now appears:
- Counted in all three language sections of README.md
- Listed in the "What This Gives You" bulleted principle list
- Full entry in `principles/README.md` with two decision-matrix rows
- Technical section in `HOW-IT-WORKS.md` explaining append-only vs mutable shared state with the Anthropic `.claude.json` corruption incident as cautionary data
- Brief mention in `CLAUDE.md` (global config summary)

### Root cause

When a principle is added, there is no automated check that "every principle is counted in every index". The `cross_reference_check.py` script catches broken links and numbering gaps, but a lagging count like "17" when the reality is 18 reads as valid prose. Added this class of drift as an open concern in MAINTENANCE.md red-flags section.

Extended the script immediately with `check_principle_count_claims`: counts `principles/NN-*.md` files and greps index files (README, AGENTS, principles/README, CLAUDE, MAINTENANCE, HOW-IT-WORKS) for claims like "N principles" / "N принципов" / "N 个架构原则" / "N battle-tested principles" - any mismatch is an error. UPDATES.md is excluded because changelog entries record historical counts that were accurate at the time.

Also added principle 18 sections to `HOW-IT-WORKS.md` (append-only vs mutable shared state explainer with the Anthropic #29217 incident as cautionary data) and `CLAUDE.md` (global config summary with convention-before-automation guidance).

---

## 2026-04-14 (v2.3.2 - Maintenance infrastructure)

### Added: MAINTENANCE.md

Governance doc covering how this repo stays consistent with itself and in sync with personal/internal workflows. Six sections:

1. **Rule audit on new principle** - re-read all rules when adding a principle, catch contradictions in the same PR (this is exactly the check that would have caught the principle-18 vs handoff-rule inconsistency fixed in v2.3.1)
2. **Cross-reference check (automated)** - run `scripts/cross_reference_check.py` before commit
3. **Bi-weekly sync checkpoint** - diff local `.claude/rules/` vs public `rules/`, classify each file as generalizable / local-only / already-ported
4. **Local → public generalization workflow** - 9-step procedure for porting a pattern: strip project context, add prior art, place in right location, verify indexes, grep for personal data leakage
5. **Versioning policy** - major/minor/patch definitions
6. **Red flags** - drift indicators that warrant attention

### Added: scripts/cross_reference_check.py

Automated consistency check. Validates:
- All markdown links resolve to existing files (principles, rules, hooks, templates, skills)
- Principle numbering has no gaps or duplicates
- Every principle is linked from at least one index file
- Every hook is mentioned in README.md

Skips fenced code blocks and inline code so illustrative examples aren't validated. Strict mode (`--strict`) promotes warnings to errors for CI.

**First run result:** 4 real broken links in `alternatives/memory-strategies.md` - inside a markdown code block showing MEMORY.md entry format, pattern examples used markdown link syntax with placeholder filenames (e.g. square-brackets-text-parens-placeholder-md) that didn't resolve to any real file. Even though the enclosing code block made them illustrative, the syntax was misleading: a reader skimming the doc could assume these were real links, and anyone copying the template into their own MEMORY.md would inherit broken links. Fixed by dropping the link syntax for pattern examples (plain `pattern_NAME.md` text). All checks now pass.

### Why this matters

The principle-18-vs-handoff-rule inconsistency (fixed in v2.3.1) was caught by manual review only after commit. The user asked "why didn't we notice?" - because there was no mechanical check for it. The script catches link-level drift. The MAINTENANCE.md workflows catch semantic drift that still needs human reading.

Neither alone is enough. Together they bound how far the repo can drift from its own claims.

### Follow-up: expanded script to shrink the "not caught" list

The original script left three classes of drift to humans: semantic contradictions, outdated trade-off tables, and broken concept references. That framing was wrong - automation should handle everything it can.

Added checks:
- **Principle number references** (error): text mentions of "principle N" must resolve to an actual `principles/NN-*.md` file, not a hallucinated number
- **Alternatives freshness** (warning): opt-in via `related_principles: [N, M]` + `last_reviewed: YYYY-MM-DD` frontmatter. Flags when any referenced principle was modified on a day after the review date. Compares at date precision to avoid same-day false positives.
- **Anti-pattern propagation** (warning): opt-in via `warns_against: [phrase, phrase]` frontmatter on principles. Greps rules/ and alternatives/ for those phrases and warns if they appear - catches cases where a new principle bans X but existing rules still recommend X.

Applied frontmatter to `alternatives/session-handoff.md` as first adopter. Future alternatives should follow the same pattern. MAINTENANCE.md section 2 updated to document all 7 checks and the opt-in frontmatter format.

The "not caught" list is now two items (deep semantics without warns_against phrases, ecosystem shifts external to the repo) instead of three. Every new drift class observed in the future should be added as an automated check rather than left to humans.

---

## 2026-04-14 (v2.3.1 - Handoff rule catches up with multi-session mode)

### Fixed: `rules/session-handoff.md` was stuck on single-file `.claude/HANDOFF.md`

The rule file still recommended the old single-file pattern even though:
- `alternatives/session-handoff.md` already documented 5 approaches including multi-session
- README (v2.2.2 audit) already mentioned `.claude/handoffs/` in handoff section
- Both hooks (`session-handoff-check.py`, `session-handoff-reminder.py`) already support both formats
- Principle 18 (added earlier today) explicitly invokes the multi-session invariant

This left the main rule inconsistent with its own ecosystem. Now the rule:
- Offers **two modes** up front: single-file (simpler, default for most users) vs multi-session (opt-in when parallel chats happen)
- Gives clear switch criteria: "use multi-session only if you've actually hit last-writer-wins data loss"
- Keeps both protocols side-by-side so a user can read whichever fits their workflow
- References principle 18 for the architectural theory behind multi-session

Updated files: `rules/session-handoff.md`, `README.md` (handoff section now shows the two-mode table).

### Note: this repo is maintained separately from any internal workflow

The skills/principles/rules here are a curated set meant to be copy-pasteable into any Claude Code project. Personal workflow evolutions (e.g. project-specific memory files, absolute paths, custom rules) are intentionally excluded. When an internal pattern proves itself and can be generalized, it gets ported here - but the round-trip is manual, not automatic. That's why the public rule lagged: the internal multi-session pattern evolved over weeks before the generalized version was ported.

---

## 2026-04-14 (v2.3.0 - Multi-Session Coordination)

### Added: Principle 18 - Multi-Session Coordination

Pattern for coordinating state between parallel Claude Code sessions that share a single workspace. Addresses a real gap in the ecosystem: isolation solutions (worktrees, sandboxes, Agent Teams) are well-covered, but live shared-state resource locks are not.

- `principles/18-multi-session-coordination.md` - full pattern:
  - Two types of shared state: append-only (handoffs) vs mutable (locks) require different mechanisms
  - Lock-file pattern with heartbeats + external stale verification
  - Convention-first evolution (hooks come later, when patterns stabilize)
  - Per-resource files (not one shared table) to minimize conflict windows
  - Take / Heartbeat / Release protocol with anti-fabrication verify-after-delete
  - Prior art table: Anthropic Agent Teams, claude_code_agent_farm, parallel-cc, Kmux, issue #19364 (proposed session.lock), issue #29217 (`.claude.json` concurrent-write corruption - cautionary data)
  - Why this is a 40-year-old distributed systems problem: translate, don't invent

**Key design decisions:**
- Canonical resource names (`<server>_gpu<N>.lock`) - one resource = one file name, no variants
- Heartbeat obligatory for long tasks (>2h); stale reclaim requires external process verification before taking over
- INDEX.md is append-only (log of TAKE/HEARTBEAT/RELEASE events), lock files are the single source of current state
- Session identity via short task name or session-id prefix, not globally unique UUIDs

**Maturity level:** L2 (Self-Evolving) - live state that accumulates within and across sessions.

---

## 2026-04-12 (v2.2.2 - Freshness audit)

### Fixed: Principle numbering conflict (two #12s)

`12-dbs-skill-creation.md` conflicted with `12-low-signal-residual-training.md`. Renumbered DBS to `17-dbs-skill-creation.md`. Low-Signal Training keeps #12 (was published first, already referenced in UPDATES and README).

### Updated: All index files for accuracy

Comprehensive freshness audit of README.md, AGENTS.md, principles/README.md:
- Principle count: 16 -> 17 across all files
- Skills Catalog: added 6 missing skills (5 video-production + humanize-russian), now 16 total
- Hooks table: added missing `session-handoff-check.py` (SessionStart), now 5 total
- Templates: added `chronicle.md`, `memory-project.md`, `memory-reference.md` to listing
- Session Handoff section: updated from old `.claude/HANDOFF.md` to multi-session `.claude/handoffs/` format
- Chinese (中文) and Russian sections: updated all counts
- Maturity table: added DBS to L1 Foundational
- Decision matrix: added DBS entry

### Added: 2 new alternatives (previously untracked)

- `alternatives/agent-mailbox-system.md` - inter-agent communication patterns
- `alternatives/kb-code-sync.md` - keeping knowledge base in sync with code

---

## 2026-04-12 (v2.2.1 - DBS Skill Creation Framework)

### Added: Principle 17 - DBS Framework (was incorrectly numbered 12)

When creating skills from research, split content into three categories:
- **Direction** (-> SKILL.md): logic, decision trees, error handling
- **Blueprints** (-> references/): templates, guidelines, taxonomies
- **Solutions** (-> scripts/): deterministic code, API calls, calculations

This prevents monolithic SKILL.md files where logic, data, and code are mixed. The model loads Direction into context, fetches Blueprints on demand, and executes Solutions without reasoning.

Source: @hooeem's NotebookLM integration guide (April 2026).

---

## 2026-04-11 (v2.2.0 - Project Chronicles)

### Added: Principle 16 - Project Chronicles

Long-running projects that span weeks/months need more than handoffs. Handoffs answer "what's next?" but not "how did we get here?" Chronicles solve this with a condensed timeline per project.

- `principles/16-project-chronicles.md` - full pattern: chronicle vs handoff vs documentation comparison, entry format, integration with handoffs, when to add entries, scaling strategies
- `templates/chronicle.md` - starter template for new project chronicles
- `rules/session-handoff.md` - updated with chronicle connection: `Project:` field in handoffs, auto-append to chronicle on handoff write

**Key design decisions:**
- Chronicle entry = 3-7 lines of strategic digest (decisions, pivots, results, dead ends), NOT a handoff copy
- One file per project in `.claude/chronicles/`, append-only
- Entries added at milestones (phase completion, pivots, dead ends confirmed), NOT every session
- Chronicles complement handoffs: strategic context (months) + tactical context (days) = full picture

**Maturity level:** L2 (Self-Evolving) - project memory that accumulates across sessions.

### Updated: README, principles/README

- Principle count: 15 → 16
- New maturity row: "Cross-cutting: Session + Project Continuity" (Codified Context, Project Chronicles, Research Pipeline)
- Decision matrix: 2 new entries for project history scenarios

---

## 2026-04-11 (v2.1.0 - Video Production Skills)

### Added: Complete video production skill suite (`skills/video-production/`)

5 new skills for creating product demo videos, ads, and presentations:

- **product-meaning-extractor** - Deep product analysis before creating content. "So What?" test, JTBD, StoryBrand, April Dunford positioning, customer language bank. Outputs structured brief with: core insight, enemy, transformation, unique mechanism, proof, emotional hooks, customer voice bank.

- **video-narrative-arc** - 5 proven narrative templates (10s-90s): Pattern Interrupt, Problem-Solution Flash, Hook-Pain-Demo-Proof-CTA, Apple Keynote Mini, Full Story Arc. Each with beat-by-beat timing, emotional arc mapping, and hook formulas.

- **script-evaluator** - Flatness detector. Scores 6 dimensions (tension, specificity, emotional arc, hook strength, customer voice, visual variety) on 1-10 scale. Identifies 5 common flatness patterns with specific fixes.

- **remotion-production-guide** - Complete Remotion reference: project setup, animation library (fadeIn/slideUp/scalePop/stagger/countTo), spring presets, typography rules, easing reference, color palettes, pacing tables, 3D integration (@remotion/three, Lottie, Spline), export settings for all platforms.

- **video-post-production** - FFmpeg patterns for audio mastering, captions, color correction, platform export (YouTube/TikTok/Reels/Shorts), concatenation, speed changes, GIF creation. Includes volume levels table, BPM guide for music selection, and quality checklist.

Built from deep research: 2500+ lines of rules from Apple HIG, Material Design 3, Disney's 12 Principles, motion design best practices, and analysis of 28 existing Claude Code video/marketing skills.

---

## 2026-04-11 (v2.0.2 - Memory Cross-Links)

### Added: wiki-links graph pattern for memory files

- `rules/memory-crosslinks.md` - guide for adding `[[wiki-links]]` between memory files
- `templates/memory-project.md` - structured project memory with Activity log, Open Items, Key Decisions, Related links
- `templates/memory-reference.md` - structured reference memory with Gotchas and Related links

Inspired by Rowboat knowledge graph approach. Memory files linked via `[[filename]]` create a navigable graph without any database. Five relationship clusters: infrastructure, projects, methodology, tools, feedback.

---

## 2026-04-10 (v2.0.1 - Multi-session Handoff Fix)

### Fixed: handoff scripts now support multi-session format

- `session-handoff-reminder.py` (Stop hook) - now tells agent to write to `.claude/handoffs/` instead of old `.claude/HANDOFF.md`
- Added `session-handoff-check.py` (SessionStart hook) - reads from `.claude/handoffs/` directory, shows recent handoffs, falls back to old format

The old single-file HANDOFF.md format had race conditions when multiple Claude sessions ran in parallel. The new format uses `.claude/handoffs/YYYY-MM-DD_HH-MM_<session-id>.md` with an append-only INDEX.md.

---

## 2026-04-10 (v2.0.0 - Plugin Format)

### BREAKING: Converted to Claude Code plugin format

Added `.claude-plugin/plugin.json` manifest. The repo can now be installed with `claude plugin install` instead of manual file copying. Version bumped to 2.0.0 to reflect this structural change.

### Added: hooks/ directory with 4 ready-to-use scripts

| Script | Event | Purpose |
|---|---|---|
| `session-drift-validator.py` | SessionStart | Validates file path references in CLAUDE.md and rules/ |
| `session-handoff-reminder.py` | Stop | Reminds to write handoff before closing long sessions |
| `destructive-command-guard.py` | PreToolUse | Blocks rm -rf, git push --force, DROP TABLE, etc. |
| `secret-leak-guard.py` | PreToolUse | Prevents writing API keys/tokens into tracked files |

Each script includes setup instructions and works standalone. README covers hook events reference, conditional hooks (v2.1.89+), matcher patterns, and hook response format.

### Added: Principle 14 - Managed Agents

Separate the brain (planning) from the hands (execution). Covers:
- Anthropic Managed Agents API (April 8, 2026): `execute(name, input) -> string` interface
- Brain/Hands/Session architecture with lazy provisioning (p50 TTFT -60%)
- Claude Code Agent Teams (TeamCreateTool behind feature flag - found via Chinese community analysis of 510K LOC TypeScript source)
- HiClaw pattern (Alibaba/AgentScope): Matrix protocol, worker tokens, permission scoping
- Self-hosted alternatives table (CrewAI, Docker Agent SDK, Hermes, tama)
- Cost analysis: $0.08/session-hour + tokens

### Added: Principle 15 - Red Lines (红线)

Absolute prohibitions inspired by Chinese engineering community pattern:
- Red lines vs regular rules: priority, enforcement, incident anchoring
- Three implementation patterns: CLAUDE.md section, separate REDLINES.md, hook enforcement
- Red line categories: data safety, system integrity, external actions, agent-specific
- Lifecycle: incident -> root cause -> draft -> implement -> quarterly review
- Hook > Rule > Hope enforcement hierarchy

### Added: templates/ directory

Starter configurations for common project types:
- `CLAUDE-web-app.md` - React/Vue/Next.js web applications
- `CLAUDE-ml-project.md` - ML/AI training and inference projects
- `CLAUDE-library.md` - npm/PyPI/crates.io packages
- `REVIEW.md` - Code review guidelines (drop-in for any project)

All templates under 150 lines (KV-cache efficient), with `{{placeholder}}` format for customization.

### Updated: Principle 08 - $ARGUMENTS documentation

Added new section on parameterized skills: how `$ARGUMENTS` works, invocation examples, best practices (always handle empty, natural language not CLI flags, scope not behavior).

### Updated: README.md - bilingual sections

Added Chinese (中文简介) and Russian (описание на русском) sections. Not full translations, but navigational summaries for non-English speakers. Includes: feature list, structure overview, installation command.

### Updated: README.md, AGENTS.md, principles/README.md

- Principle count updated from 13 to 15 across all index files
- Added hooks and templates to structure listings
- Added Managed Agents to L3 maturity level
- Added Red Lines to Cross-cutting level
- Added 3 new entries to Decision Matrix
- Added hooks table and templates link to main README

---

## 2026-04-10

### Fixed: Principle numbering conflict

Two files had number 11: `11-documentation-integrity.md` and `11-research-pipeline.md`. Renumbered research-pipeline to `13-research-pipeline.md`. Now 13 principles with clean sequential numbering.

### Updated: Principles README

Added entries for Principles 11 (Documentation Integrity), 12 (Low-Signal Residual Training), 13 (Research Pipeline) to the README overview and decision matrix. Updated principle count from 10 to 13.

### Added: alternatives/managed-agents.md

Comprehensive comparison of Claude Managed Agents (launched Apr 8, 2026) vs Agent SDK vs Claude Code CLI. Covers:
- Brain/Hands/Session architecture and lazy provisioning (p50 TTFT -60%, p95 -90%+)
- Pricing: $0.08/session-hour + standard API tokens. Break-even analysis vs self-hosted
- Vendor lock-in assessment (HIGH for Managed Agents)
- Self-hosted alternatives table (CrewAI, Docker Agent, Hermes, tama)
- Decision matrix and recommendations for teams already using Claude Code
- Real-world cost data: ~$20/week for native Claude Review in GitHub at moderate usage

---

## 2026-04-09 (night)

### Updated: Principle 06 - DeerFlow 2.0 three-layer isolation deep dive

Expanded "Pattern B: Sandbox Isolation (DeerFlow 2.0)" from a brief overview to a full architectural walkthrough. Research source: deep dive into [bytedance/deer-flow](https://github.com/bytedance/deer-flow) README, architecture docs, and DeepWiki analysis.

New content:
- **Layer 1: Virtual Path Translation** (`ThreadDataMiddleware`) - per-thread directories with transparent `/mnt/user-data/*` mapping
- **Layer 2: Docker Container Isolation** (AioSandboxProvider / Kubernetes) - three provisioner modes, 5-10s cold start cost, seccomp/cgroup transparency gap flagged
- **Layer 3: LangGraph State Channel Isolation** - separate `ThreadState` per sub-agent, fan-out/fan-in pattern, unidirectional communication
- **Data flow walkthrough:** `task()` tool -> `SubagentExecutor` -> 3-worker pool -> SSE result, `MAX_CONCURRENT_SUBAGENTS=3`, 15-min timeout
- **Memory weakness** documented: global `memory.json` contamination reintroduces leakage that the isolation layers prevent. Mitigation: per-session memory sharding or append-only with provenance

### Added: Principle 04 - Tool Registry Pattern (Claw Code)

New section citing Claw Code's `rust/crates/tools/` as a reference implementation of declarative tool definitions. `ToolSpec { name, description, input_schema }` struct separates tool definition (data) from dispatch (runtime) from execution (side effect). Three benefits: tiny audit surface, isolated tool tests, new tools without prompt changes. Warning against shipping 200 tools "just in case" (each degrades LLM decision quality) - Claw Code ships 19 as the baseline.

### Added: Principle 10 - Hierarchical Permission Overrides (Claw Code)

New subsection under "Layer 3: Permission Boundaries" showing the Claw Code `PermissionPolicy { default_mode, per_tool_overrides }` structure with a `PermissionMode { Allow, Deny, Prompt }` enum. Cleaner than flat allow/deny lists for single-user setups. Explicit acknowledgment of what it does NOT solve: no RBAC, no resource quotas, no provenance - those require additional mechanisms. Includes a minimal TOML config example for adoption.

### Added: scripts/kvcache_stats.py

Working Python script to measure KV-cache hit rate across Claude Code sessions. Parses `~/.claude/projects/*/*.jsonl` session logs, aggregates `cache_creation_input_tokens` / `cache_read_input_tokens` / `input_tokens` / `output_tokens` from assistant messages, computes per-session and overall hit rate, estimates cost in USD using Claude Opus 4.6 pricing, and shows savings vs a no-cache baseline. Includes percentile distribution, top-N by tokens, worst hit rate detection. Supports filtering by project substring and time window.

Real-world results on a single workspace: 96.9% overall hit rate across 83 sessions in 7 days, $10,929 actual cost vs $78,160 without caching ($67,231 / 86% savings). Median per-session 89.7%. Validates Manus's claim that KV-cache is the dominant production metric.

Run: `python scripts/kvcache_stats.py --days 7 --project <substring>`

---

## 2026-04-09 (evening)

### Updated: Principle 10 - OWASP ASI01-ASI10 + fresh CVEs + 30-minute audit

Major update to the agent security principle based on OWASP Gen AI Security Project's [Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) (published December 2025, 100+ industry experts).

**New sections:**

1. **Full OWASP ASI01-ASI10 mapping** - explicit table showing which of our Attack Taxonomy items cover which OWASP risks, and four new sub-sections for the items our taxonomy did not previously address: ASI07 Insecure Inter-Agent Communication, ASI08 Cascading Failures, ASI09 Human-Agent Trust Erosion, ASI10 Rogue Agent Behavior.

2. **Minimum Viable Security Audit (5 steps, 30 minutes)** - concrete shell commands for version check, environment hardening, MCP/tool inventory, hook audit, and provenance check. Catches ~70% of realistic attack vectors without architectural changes.

3. **Using RedCodeAgent defensively** - how to use the ICLR 2026 red-team agent ([arxiv 2510.02609](https://arxiv.org/html/2510.02609)) against your own setup. RedCodeAgent memory module discovered 82 unique vulnerabilities on OpenCodeInterpreter where baseline red-teaming found zero.

**Timeline additions (2026 real CVEs):**

- **CVE-2025-59944** (Cursor IDE, CVSS 8.0): case-sensitivity bypass in MCP config (`.cursor/mcp.json` vs `.Cursor/mcp.json`) leading to RCE via prompt injection. Fixed in Cursor v1.7.
- **Claude Code source leak (March 31, 2026):** 59.8 MB source map accidentally shipped in npm v2.1.88, exposed internal architecture to attackers.
- **CVE-2026-35020 / 35021 / 35022** (Claude Code CLI): three command injection CVEs with a shared root cause (unsanitized shell interpolation in TERMINAL env var lookup, editor path invocation, and auth helper). Discovered by Phoenix Security hours after the source leak, validated unpatched on v2.1.91 (production) as of April 3, 2026. CVSS 7.2-8.4.

**Why this matters for Claude Code users:** anyone on a Claude Code version at or before v2.1.91 needs to watch for the security advisory and upgrade via the native installer (not npm) when the patch ships.

---

## 2026-04-09

### Added: AGENTS.md at repo root

Linux Foundation / Agentic AI Foundation standard file. 70 lines, under the 150-line best-practice limit from the GitHub analysis of 2500+ repositories. Hybrid with CLAUDE.md: AGENTS.md is the universal entry point for any agent (Codex, Cursor, Claude Code), CLAUDE.md remains the Claude Code-specific overlay. Future-proofs the repo for when Claude Code adds native AGENTS.md support (issue anthropics/claude-code#6235).

### Updated: Principle 01 - SEMAG trace-similarity escalation

Added a new section on execution trace similarity as a stagnation signal for Generator-Evaluator loops. Based on [arxiv 2603.15707](https://arxiv.org/abs/2603.15707). When consecutive attempts produce near-identical runtime traces (rho > 0.85), the loop has stalled and should escalate through three levels: single-shot -> trace-guided debugging -> multi-agent discussion-decision with weighted voting. Explicitly rejects SEMAG's full Automatic Model Selector as too task-specific without difficulty measurements.

### Updated: Principle 02 - Reliability metrics + OpenClaw paid note

Added a new section on reliability as a distinct dimension from accuracy, based on [arxiv 2602.16666](https://arxiv.org/html/2602.16666v1). Extends the single PASS/FAIL verdict with a four-dimensional tuple (consistency, robustness, predictability, safety). Minimum viable adoption: multi-run consistency + prompt paraphrase robustness. Also added a note at the top: OpenClaw is now a paid third-party tool as of April 4, 2026, but the arxiv paper and the pattern remain freely usable.

### Updated: Principle 06 - Coordination Patterns (Paperclip vs DeerFlow)

Added a new section comparing two production-tested coordination approaches: Paperclip's shared-workspace pattern (43K stars, file-based handoff, scales to 50+ trusted agents) vs DeerFlow 2.0's sandbox-isolation pattern (44K stars, per-agent Docker, 10-15 agents with strict blast-radius control). Includes a decision table and a hybrid pattern.

### Updated: Principle 03 - Autoresearch scope limitations

Added SICA v2 findings from [arxiv 2504.15228](https://arxiv.org/abs/2504.15228). Three failure modes: base model saturation, reasoning interruption, path dependency. Revised scope guidance and a "signal to stop" rule: three consecutive iterations without improvement means stop.

### Updated: alternatives/context-management.md - Manus KV-cache insights

Comprehensive section on KV-cache hit rate as THE production metric. Four rules for cache-friendly context: stable prefixes, mask tools instead of swapping, filesystem as extended context, preserve errors. Includes the todo.md recitation trick (exploiting recency bias). Cross-table showing how KV-cache interacts with each of the four context management approaches.

### Updated: Principle 09 - Sapphire Sleet attribution + native installer note

Added Microsoft's Sapphire Sleet attribution alongside Google's UNC1069 attribution (same DPRK actor, different vendor naming). Added explicit Claude Code recommendation: use the native installer instead of npm to eliminate transitive dependency attack vectors entirely.

---

## 2026-04-08 (night update)

### Updated: Principle 12 - Added Trap 7 (Loss Asymmetry on Bipolar Residuals)
- **Critical discovery from visual inspection**: L2 loss silently ignores half of bipolar residual distributions (e.g., Dodge&Burn where dodge spots are +5% but burn spots are -2%)
- Metrics (MAE, PSNR) looked fine because the missed side contributes less to mean error — but visual contrast enhancement revealed model was producing "zero" for darker corrections
- New **Trap 7** section: cause, diagnosis, fix (L1/Huber instead of L2)
- Updated "Which Loss" section: L2 is wrong for bipolar residuals, Huber is safe default, Active weighting helps on dense/complex scenes
- Added diagnostic step #8: compare enhanced prediction vs enhanced GT side-by-side, check both sides of distribution
- Updated quick-reference config: `loss_fn: huber` (was L2)
- Key lesson: **don't trust metrics alone for low-signal tasks - always visually inspect with contrast enhancement ×5-10**

---

## 2026-04-08 (evening)

### Added: Principle 12 - Low-Signal Residual Training
- `principles/12-low-signal-residual-training.md` - 6 traps + fixes for ML tasks where targets have small deviations from a constant baseline
- Covers: "predict zero" attractor, PSNR metric lies, JPEG target poisoning, tanh saturation, subject background pollution, warmup/EMA timing
- Source: 4 rounds of retouch training failure + 7-config parallel sweep
- Includes known-good config (U-Net + EffB4, amp=5, no tanh, Huber/L2, warmup+delayed EMA)
- General applicability: any residual prediction task (denoise, color correction, enhancement)

---

## 2026-04-08

### Added: 3 new alternatives from Telegram research digest
- `alternatives/memory-strategies.md` - verbatim vs extraction vs hybrid, MemPalace 4-layer model, temporal validity, when to use ChromaDB
- `alternatives/token-economy.md` - Caveman Prompting (75% token savings), where to apply/avoid, quantitative benchmarks
- `alternatives/multi-agent-patterns.md` - Generator-Evaluator, Coordinator+Specialists, CORAL heartbeat, Proof Loop, implementation in Claude Code

### Updated: English Text Humanization Skill
- `skills/writing/humanize-english/SKILL.md` - upgraded sources from SEO blogs to peer-reviewed research
- Added Liang et al. (arxiv 2406.07016) data: 10 marker words, excess ratios (delve 25.2x, showcasing 9.2x)
- Added structural anti-patterns section (AI shape, symmetry, tone traps)
- Added co-evolution note (word lists go stale, principles > specific words)
- Replaced "humanizer tool" sources with academic papers + research data repos

### Added: Russian Text Humanization Skill
- `skills/writing/humanize-russian/SKILL.md` - new skill for Russian-language text naturalization
- Russian-specific markers: "является", "не просто..., а...", deverbal nouns (отглагольные существительные)
- English calque detection (word order, syntax patterns)
- Conversational elements dosing (частицы, вводные, оценочные)
- Checklist + comparison table RU vs EN detection differences
- Sources: gramota.ru, Habr 918226, Sber GigaCheck, Russian Wikipedia

---

## 2026-04-07

### Added: Alternative - Workspace Organization
- `alternatives/workspace-organization.md` - система из 3 навигационных .md файлов
- WORKSPACE.md (карта), PROJECTS.md (реестр), session-handoff (правило)
- Research Hub с тематическими подпапками (_inbox, agentic, ml, infra, security, product)
- Потоки данных: raw research → research/{тема}/ → knowledge pipeline → проекты
- Связь с Karpathy LLM Wiki, MemPalace, CORAL patterns

---

## 2026-04-04

### Added: Principle 11 - Research Pipeline
- Save research results to `.research/incoming/` after every research session
- Prevents duplicate work across sessions
- Creates a knowledge pipeline: research -> incoming -> review -> knowledge base
- Connected to Codified Context, Session Handoff, Autoresearch principles

---

## 2026-04-08

### Added: Manual handoff trigger phrases + ready-to-copy rule file

Natural-language trigger phrases ("prepare handoff", "save context for new chat", etc.) for writing `.claude/HANDOFF.md` on demand. Essential for migrating existing sessions that predate any hook-based automation.

- New file: [rules/session-handoff.md](rules/session-handoff.md) - drop-in rule with trigger phrases, HANDOFF.md format, session-start behavior, and rule-vs-hook rationale
- New README section: "Session Handoff - Moving Between Chats" with the trigger phrases and usage explanation for humans
- Updated [alternatives/session-handoff.md](alternatives/session-handoff.md): trigger-phrase variant added to Approach A (Manual HANDOFF.md)

The rule complements hook-based automation: hook handles forgetful users, rule handles deliberate session closure.

### Added: Principle 11 - Documentation Integrity

Fundamental solution to documentation drift for AI agents: validate all file references at session start via a SessionStart hook, not rules.

**Core insight**: rules are instructions of hope - the agent follows them only if it remembers and chooses to. Hooks are shell processes that run unconditionally. For guaranteed behaviors (validation, handoff, cleanup), use hooks, not rules.

The principle ships with a working Python validator (`scripts/validate_config.py`) that:
- Distinguishes real references (absolute paths, multi-segment with `/`) from examples (bare filenames like `foo.py`)
- Uses multi-strategy path resolution (absolute -> relative to file -> cwd -> workspace roots)
- Keeps false positives low via skip patterns for template placeholders

Drop the script into `~/.claude/scripts/` and register a `SessionStart` hook - the agent sees drift warnings automatically on every session start.

See [principles/11-documentation-integrity.md](principles/11-documentation-integrity.md) and [scripts/validate_config.py](scripts/validate_config.py).

---

## 2026-04-03

### Rewritten: README.md

Repositioned from "skills collection" to "configuration system for Claude Code agents". Focus on: what problems each principle solves (not abstract descriptions), alternatives as key feature (agent picks the right approach), security hardening section, principles by maturity level (L1-L3). Skills described as secondary/reference implementations.

### Added: Session Handoff comparison (Alternative)

Five approaches to seamless session transitions compared: Manual HANDOFF.md, Stop Hook (auto), Session Journal (living log), ContextHarness (framework), Memory Only (baseline). Sources: claude-handoff plugin, ContextHarness, JD Hodges patterns, GitHub issue #11455 community patterns.

Key insight: structured handoff (500-2000 tokens) beats raw conversation dump (50-100K tokens) by ~50x compression with higher signal. "What did NOT work" is the most valuable section - prevents the next session from repeating dead ends.

See [alternatives/session-handoff.md](alternatives/session-handoff.md).

---

## 2026-04-02

### Added: Research evidence to Codified Context (Principle 07)

Two contradictory studies on context files (AGENTS.md/CLAUDE.md): one shows -28.6% task time, other shows -3% success rate. Resolution: auto-generated context hurts, human-written non-inferable knowledge helps. Added "The Rule" - only include what the agent cannot derive from reading the code. ETH Zurich data: LLM-generated context = +20% cost, +2-4 extra reasoning steps.

### Added: Principle Map by Reasoning Level to README

Three-level taxonomy (arxiv 2601.12538, 2504.19678) maps to our 10 principles: L1 Foundational (single agent), L2 Self-Evolving (feedback + memory), L3 Collective (multi-agent). Helps users pick which principles to adopt first.

### Updated: Structured Reasoning accuracy to 93% (Principle 05)

Paper v2 results on real-world agent-generated patches: 78% -> 93% accuracy.

---

## 2026-04-01

### Added: axios@1.14.1 case study to Supply Chain Defense (Principle 09)

Real-world supply chain attack on the official `axios` npm package (~100M weekly downloads), attributed to DPRK-nexus threat actor UNC1069 by Google Threat Intelligence. Maintainer account hijacked, RAT deployed via postinstall hook. Exposure window: ~3 hours. `min-release-age=7` would have completely blocked the attack. Full timeline, attack chain, defense matrix, and IOCs documented. Sources: Elastic Security Labs, Snyk, Wiz, Google Cloud Blog.

### Added: Revision Trajectories + problems.md schema to Proof Loop (Principle 02)

Based on Agent-R (arxiv 2501.11425): failed-then-fixed trajectories are more valuable than clean passes. Added structured Evaluator feedback format (cut point + reflection + direction) and a concrete `problems.md` schema with criterion ID, reproduction steps, expected vs actual, affected files, and smallest safe fix. Improves the fix -> verify again cycle.

### Fixed: README principle count (9 -> 10)

README.md listed "9 architectural principles" and was missing Principle 10 (Agent Security) from the principles table. Updated to reflect all 10 principles.

### Added: "Deletion = re-verification" rule to Anti-Fabrication

Added the pattern: after executing a delete command, always verify the object is actually gone. Commands can exit 0 without doing anything (permissions, locks, wrong path). Part of the Anti-Fabrication section in Deterministic Orchestration.

---

## 2026-03-31

### Added: Agent Security (Principle 10)

Comprehensive defense guide against prompt injection and adversarial attacks on AI coding agents. Covers 7 attack categories (in-code injection, repo metadata, package metadata, MCP tool poisoning, web content injection, memory poisoning, sandbox escape) with real CVEs and incidents. Six-layer defense architecture from content isolation to monitoring. See [principles/10-agent-security.md](principles/10-agent-security.md).

### Added: Supply Chain Defense (Principle 09)

Package age gating as defense against supply chain attacks. Two config lines that block packages published less than 7 days ago:

```ini
# ~/.npmrc
min-release-age=7
```

```toml
# ~/.config/uv/uv.toml
exclude-newer = "7 days"
```

Most malicious packages are caught within 1-3 days. The 7-day delay eliminates the attack window with near-zero friction to your workflow. See [principles/09-supply-chain-defense.md](principles/09-supply-chain-defense.md) for full details including per-manager configs, CI considerations, and defense-in-depth layers.

### Fixed: 6 skills were ZIP archives, not readable on GitHub

`diffusion-engineering`, `vlm-segmentation`, `flux2-klein-prompting`, `forensic-prompt-compiler`, `ios-development`, `frontend-design` - all now properly extracted with SKILL.md + references/ as readable markdown.

### Updated: Memento references replaced

The `mderk/memento` repo appears to have been removed from GitHub. All references updated to point to active alternatives: [task-orchestrator](https://github.com/jpicklyk/task-orchestrator), [inngest/agent-kit](https://github.com/inngest/agent-kit). The deterministic orchestration principles remain valid and well-documented.

### Freshness check: all 10 concepts reviewed

| Concept | Status |
|---------|--------|
| Generator-Evaluator | Current - now a standard primitive |
| Proof Loop | Current - watch formal verification + LLM space |
| Autoresearch | Very current - 21K stars, ecosystem explosion |
| HyperAgents | Current - Meta released code |
| HACRL | Current - conceptual pattern is actionable |
| Structured Reasoning | Current - 78%->88% accuracy validated |
| Codified Context | Current - 1M window adjusts urgency, not principle |
| Memento | Repo gone - principles live in alternatives |
| Context Engineering | Current - update for 1M context realities |
| Multi-Agent Decomposition | Current - trend toward adaptive routing |

---

## 2026-03-30

### Initial release

8 architectural principles, 4 alternative comparison docs, 10 skills, CLAUDE.md template. Covers: harness design, proof loops, autoresearch, deterministic orchestration, structured reasoning, multi-agent decomposition, codified context, skills best practices.

## Core Working Rules added (2026-06-07)

Five hard user-directive rules added to rules/: secrets-as-data, quality-no-monkey-patch, finish-the-task, quality-over-tokens-independent-verify, deletion-confirm-and-verify. Registered in CLAUDE.md 'Core Working Rules'. Mirror existing safety hooks (stop-phrase-guard, human-confirmation-guard, verify-deleted-guard, pre-push public-repo scan).

