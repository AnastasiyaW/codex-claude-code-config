---
name: lean-code
description: On-demand minimalism intensifier — find the smallest sufficient, verified implementation for the requested outcome. Use when the user says "be lazy / yagni / simplest / minimal / shortest / don't over-engineer", complains about bloat / boilerplate / unnecessary dependencies / abstraction, or before writing a substantial chunk of new code. Supports intensity: lite / full / ultra. Pairs with the always-on quality-code rule and the over-engineering-advisor hook. Do NOT use as a general code-review or bug-hunting pass — it only removes over-building and will not find unrelated correctness defects; use /code-review or /review for those.
---

# Lean Code

Aggressive YAGNI mode, on demand. The always-on baseline is `rules/quality-code.md`; this skill is the **intensifier** you invoke when minimalism matters most. The win is the smallest solution that fully satisfies the accepted task outcome, not the fewest lines or the shortest explanation.

## The ladder — stop at the first rung that holds
1. **Does this need to exist at all?** Speculative need → skip it, say so in one line. (YAGNI)
2. **Stdlib does it?** Use it.
3. **Native platform feature covers it?** (`<input type="date">` over a picker lib, CSS over JS, a DB constraint over app code.)
4. **An already-installed dependency solves it?** Use it. Never add a new dependency for what a few lines do.
5. **Can the accepted behavior safely be one line?** Prefer it; do not contort control flow, validation, or errors merely to make it fit.
6. **Only then** — the minimum code that works.

The ladder is a reflex, not a research project: two rungs hold → take the higher one and move on.

## Intensity
- **lite** — build what the user asked; mention one leaner alternative only when it materially helps. Do not pause accepted implementation for an optional choice. Ask only when an unresolved decision materially changes the requested outcome or authority.
- **full** — enforce the ladder; prefer stdlib/native and the smallest sufficient, verified diff. (Default.)
- **ultra** — challenge a requested mechanism, scope assumption, or speculative extension against the required outcome; do not challenge an explicit user decision merely to reduce code. Once retained, implement it without re-arguing.

## When NOT to be lean (load-bearing — never simplify these away)
Input validation at trust boundaries · error handling that prevents data loss · security · accessibility · the calibration real hardware needs · anything the user explicitly asked to keep. **Lean ≠ incomplete:** non-trivial logic leaves one runnable check behind (assert-demo or one small test). User insists on the full version → build it, no re-arguing.

## Hard boundary — lean targets OVER-building, never completeness
This is orthogonal to thoroughness. "Minimal" means less unnecessary complexity while delivering every accepted branch, not fewer branches done, a lower line count, or a shortcut. It must never excuse under-delivery, skipped verification, or a hack — see `rules/finish-the-task.md` (its completeness + quality pillars win) and `rules/quality-code.md` (the no-monkey-patch pole). Mark a deliberate shortcut with a `simplification:` comment naming the ceiling + upgrade path.

## Output
Complete and verify the requested result first. Then use at most three short lines for what was deliberately skipped and the trigger to add it. Do not suppress an explanation needed to document a safety boundary, user decision, or upgrade path. Read the surrounding code and requirements before pruning — prune to the task, not to a blanket rule.

## Why this works (evidence, not marketing)
GitClear's 2025 report observed rising copy/paste and falling moved-line rates across 211M changed lines; Faros observed higher team task/PR throughput alongside slower review and no demonstrated organization-wide gain. Those are ecosystem signals, not proof that a particular agent or diff is bloated. A "do I even need this?" check is therefore useful, but not a line-count target. [GitClear](https://gitclear-public.s3.us-west-2.amazonaws.com/GitClear-AI-Copilot-Code-Quality-2025.pdf) · [Faros](https://www.faros.ai/blog/ai-software-engineering)

Generic prompt additions can trade one measured behavior for another in small local experiments; they do not establish a universal minimalism rule. Keep this on-demand and advisory, then evaluate its instructions on representative held-out tasks. [arXiv:2601.22025](https://arxiv.org/abs/2601.22025)

## Gotchas
- A one-liner is worse when it hides a required failure path, access need, or future-maintenance boundary.
- `ultra` can question how to achieve an outcome; it cannot silently remove an outcome or override the user's retained choice.

## Troubleshooting
- **The diff is short but a required behavior vanished.** Restore the behavior, then remove only the unnecessary mechanism around it and run the smallest relevant check.
- **A simplification has an explicit scale or correctness ceiling.** Keep the simple version only with its `simplification:` ceiling and upgrade trigger; otherwise implement the proper architecture now.
