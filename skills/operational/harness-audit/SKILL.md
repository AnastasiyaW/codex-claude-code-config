---
name: harness-audit
description: Score a project's agent harness across 5 subsystems (Instructions / State / Verification / Scope / Lifecycle), identify the bottleneck, and produce a prioritized improvement plan. Use when assessing if a project is ready to graduate to [LONG-RUN] status, when an agent keeps failing despite good models, or when adopting our stack on a new codebase. Do NOT use to design or build a new harness from scratch — this only scores an existing one; for greenfield harness/agent architecture use harness-design (or agent-harness-design).
license: MIT
---

# Harness Audit

Trigger on phrases like: "audit my harness", "evaluate my agent setup", "score my CLAUDE.md", "is my project ready for long-run", "5-subsystem assessment", "what's missing from my project setup", "/harness-audit". Run proactively when joining an unfamiliar codebase that has agent artifacts (CLAUDE.md, .claude/, AGENTS.md) but obvious gaps. Skip for single-file scripts and pure exploration.

Score a project's agent harness across five subsystems and tell the user which evidenced bottleneck to address first. Distinguish an artifact's presence from demonstrated behavior; never present metadata alone as runtime proof.

**Source**: Five-subsystem framework adapted from [Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/) (walkinglabs, MIT). Adapted to our concrete stack: CLAUDE.md, `.claude/rules/`, PROBLEMS.md, `feature_list.json`, `init.sh`, hooks, handoffs, chronicles.

## What This Skill Does

Given a project directory, produces a scorecard like this. This example assumes
`project-xyz` delivers features across sessions and uses pull requests:

```
=== Harness Audit: project-xyz ===

Instructions  4/5  ✓ Agent entrypoint and modular rules are documented and used
                   ~ PR review guidance is not found in the inspected evidence
State         2/5  ✓ 3 handoffs preserve some continuation state
                   ✗ No current record locates active scope and deferred work
                   ~ PROBLEMS.md / feature_list.json are suitable conventions, not prerequisites
Verification  3/5  ✓ Documented test command; pytest is configured
                   ~ No current execution receipt supplied
                   ✗ No documented staged validation/proof route
Scope         3/5  ✓ in-scope principle in CLAUDE.md
                   ~ shared-resource policy is unknown; no serialized lane is declared
                   ✗ Definition of Done not explicit
Lifecycle     2/5  ✗ Needed session-boundary entry/stop behavior is not documented or demonstrated
                   ~ Manual cleanup convention exists but not enforced

Bottleneck: State (2/5) — no current locator for feature scope and deferred work

Priority improvement (only when the user asks for recommendations):
- Record an execution receipt for the existing test command   ↗ Verification evidence
```

For an **audit-only** request, this skill produces the scorecard without making
changes or running probes merely to convert `unknown` into a pass. If the user
also requested correction or implementation, the scorecard is an intermediate
result: return the confirmed findings to the owning task and execute its
necessary, authorized reversible fixes, verification and delivery. Do not stop
at a report or assign agent-owned fixes back to the user. Preserve the original
acceptance criteria and real external/irreversible boundaries.

---

## The Five Subsystems (Our Adaptation)

| Subsystem | Concrete files/conventions in our stack |
|---|---|
| **Instructions** | `CLAUDE.md` (root + `~/.claude/`), `.claude/rules/*.md` (project), `~/.claude/rules/*.md` (global), optional `REVIEW.md` |
| **State** | `PROBLEMS.md`, `feature_list.json`, `.claude/handoffs/`, `.claude/chronicles/` |
| **Verification** | a documented command plus current receipt appropriate to the target, tests/config where applicable, Proof Loop usage |
| **Scope** | explicit in-scope/Definition of Done policy and a concurrency policy appropriate to the work |
| **Lifecycle** | SessionStart hooks, Stop hooks (stop-test-gate, check-problems-md), cleanup convention |

See `references/checklist-per-subsystem.md` for per-subsystem concrete checks.
See `references/scoring-rubric.md` for how to interpret 1-5 scores.

---

## How to Run an Audit

### Phase 1 — Gather

Read these files in order (skip silently if missing):

1. `CLAUDE.md` in project root
2. `AGENTS.md` in project root (some projects use this name)
3. `.claude/rules/*.md` (project-level rules)
4. `.claude/settings.json` and `.claude/settings.local.json` (hooks config)
5. `PROBLEMS.md` in root
6. `feature_list.json` in root
7. `init.sh` in root (and `Makefile` / `package.json` scripts as fallback)
8. `.claude/handoffs/` (count files, check `INDEX.md` existence)
9. `.claude/chronicles/` (count files)
10. Sample test config: `pytest.ini` / `package.json` test script / `Cargo.toml`

Use `Glob` + `Read` for the harness, then inspect the smallest relevant evidence path: a current test/CI receipt, hook execution trace, or sampled state artifact. This is not a broad code review; absence of behavioral evidence is `~ unknown`, not `✓ working`.

### Phase 2 — Score

For each subsystem, first identify the project delivery model and applicable
outcomes in `references/checklist-per-subsystem.md`. Mark every finding as
`documented`, `demonstrated`, or `unknown`; score from evidence rather than file
presence alone. The canonical files in the table are useful conventions, not
universal prerequisites.

- **5** = applicable outcomes are documented, demonstrated, and consistently followed
- **4** = documented and demonstrated with bounded gaps
- **3** = only documented, only demonstrated, materially partial, or unknown at a relevant boundary
- **2** = isolated or stale structure does not meet most applicable outcomes
- **1** = missing or actively harmful

For each subsystem, list:
- ✓ what's present and working
- ✗ what's missing or broken
- ~ partial / unclear

### Phase 3 — Identify Bottleneck

The lowest-scoring subsystem is the bottleneck. **Even if other subsystems are weaker by absolute count of checks**, the lowest score is the one to fix first because it limits the value of the rest.

Tie-breaker (multiple subsystems at same low score): pick the one whose improvement *unlocks* progress in others. State often wins when the project lacks a durable locator for active scope and unresolved work; do not assume two particular filenames are required.

### Phase 4 — Prioritized Improvement Plan

Only if the user requests recommendations, propose the smallest number of independently shippable actions that address the evidenced bottleneck. For each, name the expected evidence and a local template/example if one actually fits. Do not invent effort, score gains, or a fixed number of steps. Do not expand an audit-only request into implementation; when implementation was already requested, continue that owning task after the audit instead of requesting the same authorization again.

---

## Output Format

Use the visual scorecard format shown at the top of this skill. Sections:

1. **Header**: `=== Harness Audit: <project-name> ===` (one line)
2. **Scorecard**: 5 lines, one per subsystem, with score + ✓/✗ findings
3. **Bottleneck**: one line naming the subsystem and score
4. **Priority improvements**: only when requested, with expected evidence + pointer
5. **Projected total**: optional, only if user asks and the stated evidence supports a bounded projection

Keep the entire output under 50 lines. The user is scanning for next steps, not reading an essay. Detail goes into the per-subsystem checklist file, not the audit output.

---

## What This Skill Is NOT

- **Not a code review** — does not look at source code quality
- **Not a security audit** — does not check for vulnerabilities (use `/security-review` instead)
- **Not a broad test runner** — does not manufacture a green result from configuration. It may inspect a current CI/test receipt, or run one user-authorized, task-relevant probe when runtime evidence is part of the requested audit
- **Not a standalone implementation methodology** — an audit-only request ends with its findings; an audit inside an already authorized repair returns control to that repair, not to user homework
- **Not for short-lived work without a durable handoff need** — state why the audit is disproportionate instead of applying arbitrary feature/session thresholds

---

## Honest Tradeoffs

- The 5-subsystem framework is **opinionated**. A project can be perfectly functional with 3 of 5 strong and 2 weak (e.g., a research repo with no lifecycle needs).
- Scoring is **subjective at the margins**. A 3 vs 4 for "covers basics" is a judgment call. Use the checklist to keep it consistent across audits, not to claim numeric precision.
- The skill assumes our stack conventions. For projects using completely different tooling (e.g., AGENTS.md without `.claude/`), translate concepts before scoring — don't fail the project on naming.

---

## Related

- **Principle 27** (feature-tracking) — full framework explanation
- **Principle 01** (harness-design) — Generator-Evaluator pattern, source of "subsystems" thinking
- **Templates** `templates/long-run-project/` — drop-in files for fixing State + Verification gaps
- **Rule** `rules/long-run-harness.md` — convention this audit checks against

---

## Gotchas

- A scorecard example must use the same evidence rules as the checklist; a missing filename alone does not prove a missing outcome.
- Presence of this skill or its rubric is not proof that auditors apply it consistently. Do not cite an example-evaluation file unless it actually exists and was inspected.

## Troubleshooting

- **Two auditors give different scores to the same evidence:** compare the declared delivery model and applicable outcomes, then resolve the checklist/example contradiction; do not add files just to raise the score.
- **An authorized repair ends at the scorecard:** return each confirmed finding to the original task, implement the necessary correction and verify it. An audit-only request remains read-only.
