---
name: harness-audit
description: Score a project's agent harness across 5 subsystems (Instructions / State / Verification / Scope / Lifecycle), identify the bottleneck, and produce a prioritized improvement plan. Use when assessing if a project is ready to graduate to [LONG-RUN] status, when an agent keeps failing despite good models, or when adopting our stack on a new codebase. Do NOT use to design or build a new harness from scratch — this only scores an existing one; for greenfield harness/agent architecture use harness-design (or agent-harness-design).
when_to_use: |
  Trigger on phrases like: "audit my harness", "evaluate my agent setup", "score my CLAUDE.md", "is my project ready for long-run", "5-subsystem assessment", "what's missing from my project setup", "/harness-audit". Run proactively when joining an unfamiliar codebase that has agent artifacts (CLAUDE.md, .claude/, AGENTS.md) but obvious gaps. Skip for single-file scripts and pure exploration.
license: MIT
---

# Harness Audit

Score a project's agent harness across five subsystems and tell the user which evidenced bottleneck to address first. Distinguish an artifact's presence from demonstrated behavior; never present metadata alone as runtime proof.

**Source**: Five-subsystem framework adapted from [Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/) (walkinglabs, MIT). Adapted to our concrete stack: CLAUDE.md, `.claude/rules/`, PROBLEMS.md, `feature_list.json`, `init.sh`, hooks, handoffs, chronicles.

## What This Skill Does

Given a project directory, produces a scorecard like this:

```
=== Harness Audit: project-xyz ===

Instructions  4/5  ✓ CLAUDE.md present, modular rules in .claude/rules/
                   ✗ No project-level REVIEW.md for PR review guidance
State         2/5  ✓ .claude/handoffs/ exists (3 files)
                   ✗ No PROBLEMS.md - issues scattered in handoffs
                   ✗ No feature_list.json - scope state not machine-readable
Verification  3/5  ~ pytest configured; no current execution receipt supplied
                   ✗ No documented bootstrap command
                   ✗ 3-layer gate not documented in CLAUDE.md
Scope         3/5  ✓ in-scope principle in CLAUDE.md
                   ~ concurrency policy is not documented for this project
                   ✗ Definition of Done not explicit
Lifecycle     2/5  ✗ No SessionStart hook (no .claude/settings.json)
                   ✗ No Stop hook for clean-state check
                   ~ Manual cleanup convention exists but not enforced

Bottleneck: State (2/5) — lack of structured progress tracking

Priority improvement (only when the user asks for recommendations):
- Record an execution receipt for the existing test command   ↗ Verification evidence
```

The skill does **not** make changes. It produces the scorecard. The user decides whether to apply recommendations.

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

For each subsystem, use the checks in `references/checklist-per-subsystem.md`. Mark every finding as `documented`, `demonstrated`, or `unknown`; score from evidence rather than file presence alone.

- **5** = documented, demonstrated, and consistently followed for the project type
- **4** = strong evidence with bounded gaps
- **3** = basics exist but behavioral evidence or continuity is partial
- **2** = weak or mostly undocumented/demonstrated only by stale evidence
- **1** = missing or actively harmful

For each subsystem, list:
- ✓ what's present and working
- ✗ what's missing or broken
- ~ partial / unclear

### Phase 3 — Identify Bottleneck

The lowest-scoring subsystem is the bottleneck. **Even if other subsystems are weaker by absolute count of checks**, the lowest score is the one to fix first because it limits the value of the rest.

Tie-breaker (multiple subsystems at same low score): pick the one whose improvement *unlocks* progress in others. State usually wins ties because feature_list.json + PROBLEMS.md unlock Verification and Scope checks.

### Phase 4 — Prioritized Improvement Plan

Only if the user requests recommendations, propose the smallest number of independently shippable actions that address the evidenced bottleneck. For each, name the expected evidence and a local template/example if one actually fits. Do not invent effort, score gains, or a fixed number of steps; do not expand the requested audit into implementation.

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
- **Not a fix tool** — produces recommendations only, user applies them
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

## Quick Self-Audit (for skill development)

This skill is itself a `[LONG-RUN]`-style artifact. To audit the audit:

- **Instructions**: SKILL.md is this file (✓)
- **State**: Scoring decisions are reproducible from `references/scoring-rubric.md` (✓)
- **Verification**: 5 example evals in `references/example-audits.md` (TODO if added)
- **Scope**: Clear "what this skill is NOT" section (✓)
- **Lifecycle**: No hooks needed — this is a query skill, not a continuous one (N/A)
