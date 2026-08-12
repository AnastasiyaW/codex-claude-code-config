---
related_principles: [02, 03, 04, 11]
last_reviewed: 2026-08-12
---

# Reasoning Regression Debugging - detecting and mitigating quality degradation

Date: 2026-04-15

> Case study based on [Claude Code issue #42796](https://github.com/anthropics/claude-code/issues/42796) - the Feb-Apr 2026 regression investigation by Stella Laurenzo (AMD) across 6,852 sessions. The techniques below generalize to any agent whose reasoning quality drifts over time (vendor-side changes, config drift, context poisoning).

## Problem

Your Claude Code agent was working well. Two weeks later it still looks like it's working, but:
- Edits files without reading them first
- Loops on "oh wait, actually" three times per conversation
- Rewrites whole files for single-line changes
- Dodges responsibility: "this was already broken" / "pre-existing issue"
- Asks permission too often, stops prematurely, picks simplest hacks

The model feels dumber, but you can't prove it. You can't tell if it's a vendor-side regression, config drift in your project, context pollution, or confirmation bias.

**Core metric (counter-intuitive but robust):** the ratio of `Read`/`Grep`/`Glob` calls to `Edit`/`Write`/`MultiEdit` calls across sessions. A healthy agent explores before mutating (ratio 5-7). A degraded agent edits blind (ratio < 3). This collapsed from 6.6 to 2.0 across 6852 Claude Code sessions between Jan and Apr 2026.

## Quick Comparison

| Approach | Setup cost | Detection lag | False positives | Actionable | Best for |
|---|---|---|---|---|---|
| **A: Configuration isolation** | 5 min | Instant | Low | Yes (one-shot) | Testing a documented setting change without polluting the baseline |
| **B: Stop-phrase guard hook** | 20 min | Real-time | Medium | Yes (blocks session end) | Catching behavioral tells per-session |
| **C: Metric monitoring** (Read:Edit ratio from JSONLs) | 1 hour | Weekly | Low | No (diagnostic only) | Longitudinal health tracking |
| **D: Fresh-session A/B** | 5 min per test | Instant | High | Yes (manual) | One-off "is it me or the model?" check |
| **E: Comparison against fixed baseline** (Proof Loop) | Existing | Continuous | None | Yes (blocks completion) | Production workflows where regression is unacceptable |

All five compose. Configuration isolation (A) is the first response. Stop-phrase guard (B) and Metric monitoring (C) run continuously. Fresh-session A/B (D) confirms hypotheses. Proof Loop (E) is the ultimate backstop - it makes output quality independent of model regression.

---

## A: Configuration Isolation (first response)

When a vendor-side regression is suspected, first isolate one documented,
reversible setting change. Record the client version, current configuration, test
task, and result; do not paste unverified environment variables from old posts.

Current Claude Code supports persisted `effortLevel` values `low`, `medium`,
`high`, and `xhigh`, and a documented `autoCompactWindow` of 100,000 to
1,000,000 tokens. For example, a bounded comparison may use:

```json
{
  "effortLevel": "high",
  "autoCompactWindow": 500000
}
```

Use `/effort` or `/autocompact` for a reversible experiment where available,
then compare the same fixed task in a fresh session. Confirm supported values in
the [current Claude Code settings reference](https://code.claude.com/docs/en/settings)
before changing a shared configuration.

### Trade-offs

- **Pros:** reversible and attributable: one documented configuration variable
  changes in a controlled comparison.
- **Cons:** settings can vary across machines and teams → silent drift. Record
  the effective non-secret configuration and client version with the result.

---

## B: Stop-phrase guard hook

Degraded reasoning manifests in **language patterns** the model produces. The AMD regression investigation identified five behavioral tells, caught 173 times in 17 days after Mar 8 across sessions that would have previously caught zero.

### Phrase categories

| Category | Representative phrases | Signal |
|---|---|---|
| Ownership dodging | "not caused by my changes", "existing issue", "pre-existing", "this was already broken" | Agent blaming environment for its own bugs |
| Permission-seeking | "should I continue?", "want me to keep going?", "shall I proceed?" | Agent stalling out instead of acting |
| Premature stopping | "good stopping point", "natural checkpoint", "reasonable place to pause" | Agent declaring victory too early |
| Known-limitation labeling | "known limitation", "future work", "out of scope" | Agent punting instead of solving |
| Session-length excuses | "continue in a new session", "getting long", "context is filling up" | Agent hitting context-anxiety early |

### Hook implementation

See [hooks/stop-phrase-guard.py](../hooks/stop-phrase-guard.py) for a Stop-event hook that scans the final assistant message and blocks session end on match - forcing the agent to actually finish or explain.

### Trade-offs

- **Pros:** real-time detection, surgical (blocks only the problem turn), the phrases are **vendor-agnostic** (any model that degrades tends to speak this way)
- **Cons:** false positives on legitimate uses (e.g. a task that really does have known limitations). Requires periodic tuning of the regex. Review hook logs weekly to adjust phrase list.

---

## C: Metric monitoring (longitudinal)

Compute regression indicators from session transcripts in `~/.claude/projects/*.jsonl`. Run weekly; track trends.

### Metrics (all computed from JSONL session files)

| Metric | Formula | Healthy | Degraded |
|---|---|---|---|
| **Read:Edit ratio** | count(Read tool calls) / count(Edit tool calls) per session | 5-7 | < 3 |
| **Research:Mutation ratio** | (Read + Grep + Glob) / (Edit + Write + MultiEdit) | > 8 | < 3 |
| **Edits-without-prior-Read %** | % of Edit calls where target file had no prior Read in same session | < 10% | > 30% |
| **Reasoning-loop rate** | per-1000-tool-calls count of "oh wait"/"actually"/"let me reconsider" | < 10 | > 20 |
| **User-interrupt rate** | per-1000-tool-calls user corrections mid-stream | < 2 | > 10 |
| **Write% of mutations** | Write (full rewrite) / (Edit + Write + MultiEdit) | < 5% | > 10% |
| **Thinking depth** | estimated via signature-length regression (r=0.971) or direct `usage.cache_read_input_tokens` | stable | dropping |

### Script

See [scripts/reasoning_metrics.py](../scripts/reasoning_metrics.py) for a ready-to-run analyzer. Run weekly, plot trends, alert on any metric crossing its degraded threshold.

### Trade-offs

- **Pros:** objective, longitudinal, catches slow drift that per-session eyes miss. Data-driven - reports metrics, you decide what to do.
- **Cons:** detection is weekly, not real-time. Requires baseline data (ideally 2+ weeks of healthy usage before a regression) to compare against. Does not tell you the root cause, only that something changed.

---

## D: Fresh-session A/B

Quick sanity check when you suspect degradation but aren't sure if it's the model or your own context/prompt.

### Procedure

1. Open a fresh session in a **separate workspace** (not `.claude/` of the current project)
2. Present the same failing task with minimal context
3. Observe: does the agent behave well here?
   - **Better in fresh session** → context pollution or rule interference in your project. Audit `.claude/rules/`, CLAUDE.md, recent memory additions.
   - **Same bad behavior** → vendor-side or config-side. Proceed to approach A.
4. For best signal, have the fresh session **not** load any rules/memory (bare CLAUDE.md or none at all)

### Trade-offs

- **Pros:** takes 5 minutes, isolates vendor-side from user-side regression
- **Cons:** subjective - "better" is a feel-check, not a metric. Small sample = high variance. Do 3 runs per side before concluding.

---

## E: Proof Loop as vendor-independence (existing principle)

The most robust answer is to **make output quality independent of model regression**.

[Principle 02 (Proof Loop)](../principles/02-proof-loop.md) mandates:
- Spec is frozen before code is written (Spec-freezer)
- Builder switches to read-only mode to collect evidence
- A **fresh session** (never saw build) verifies against the spec
- Completion requires `verdict.json: PASS` on every AC - not an agent claim

When this loop runs, a regressed agent cannot ship broken code because the fresh-session verifier catches it. The regression shows up as more iterations (fixer burns more cycles) but output stays correct.

This is the reason principle 02 ships with this repo: **vendor regressions are inevitable; correctness guarantees from workflow structure survive them**.

### Trade-offs

- **Pros:** the only approach that's *immune* to undetected regression - the verifier does not care whether the builder was reasoning well, only whether the evidence proves the AC
- **Cons:** heavy. Proof Loop has real setup cost (spec freezing, evidence collection, fresh-session verification). Reserve for high-stakes work where regression-induced silent failure is unacceptable

---

## Decision matrix: which approach when

| Situation | Primary | Supporting |
|---|---|---|
| Vendor just announced a regression with known workarounds | A (config reset) | D (fresh-session A/B to verify fix) |
| Suspicion without confirmation - "model feels dumber" | D (fresh-session A/B) | C (weekly metrics) |
| Running production agent workflows | E (Proof Loop) | B (stop-phrase guard) + C (metrics) |
| Onboarding new project, want baseline health | C (metrics - capture healthy baseline) | B (catch bad tells from day 1) |
| Single developer tinkering, no team context | A (config reset) | D (A/B when curious) |

## Prior art and case study

The **Stella Laurenzo (AMD) investigation** is the canonical example of this failure mode being caught with rigor:

- 6,852 session JSONLs from 4 repos, Jan 30 - Apr 1, 2026
- 17,000 thinking blocks, 234,000 tool calls
- Regression r=0.971 between thinking signature length and content length (allows estimation after Anthropic redacted content on Mar 8)
- Read:Edit ratio collapsed 6.6 → 2.0 (70% reduction)
- Anthropic's Boris Cherny (Claude Code team lead) responded on [HN #47664442](https://news.ycombinator.com/item?id=47664442), confirmed adaptive-thinking zero-allocation bug, published the workarounds in approach A

Full incident timeline and raw data: [GitHub issue #42796](https://github.com/anthropics/claude-code/issues/42796).

## Key Takeaway

Treat agent reasoning quality as a **measurable metric**, not a feel. Version-control the config that affects it. Hook on the behavioral tells that signal degradation. And for anything high-stakes, use principle 02 (Proof Loop) to make correctness **structural**, not dependent on the model being sharp that day.
