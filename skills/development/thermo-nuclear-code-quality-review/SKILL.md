---
name: thermo-nuclear-code-quality-review
description: Run an opt-in strict maintainability review for giant files, spaghetti growth, misplaced logic, weak boundaries, unnecessary abstractions, and missed structural simplifications. Use for a thermonuclear review, harsh code-quality audit, code-judo review, or a file approaching 1000 lines. Do not use as an automatic rewrite mandate or for cosmetic cleanup.
disable-model-invocation: true
---

# Strict Code Quality Review

This is an unusually demanding review mode, not an instruction to rewrite code
by taste. Inspect the current diff and surrounding architecture, then report
only high-conviction findings grounded in a contract, reachable behavior, or a
material maintainability risk.

## Review Bar

Ask:

- Can a simpler ownership boundary remove whole branches or concepts?
- Did the diff add ad-hoc flags, special cases, or feature logic to a shared
  path instead of using the canonical layer?
- Did a cohesive module become more coupled or cross a meaningful shape limit?
- Are wrappers, casts, optionality, and sequential orchestration earning their
  complexity?
- Does a proposed decomposition reduce what a reader must hold in mind, rather
  than merely move the same complexity into more files?

A file crossing roughly 1000 lines is a strong signal to inspect decomposition,
not an automatic failure. Apply the project's actual shape policy and explain
why a split would improve ownership. Do not manufacture a rewrite when the
current structure is coherent and the change is small.

## Output

Report findings in this order:

1. structural regressions;
2. missing simplifications with a concrete alternative;
3. spaghetti or branching growth;
4. boundary and type-contract problems;
5. file shape and decomposition;
6. lower-severity readability issues.

For each finding include file/line, contract or evidence, user/operator impact,
and a concrete remedy. Separate `BLOCKER`, `ADVISORY`, and `ACCEPTED` decisions.
If no finding survives reachability, materiality, and evidence screening, say so.

## Independence and scope

Use a fresh reviewer for non-trivial changes. This review does not replace
focused tests, security proof, or `proof-verify`; it evaluates maintainability
and architecture. It must not silently edit production code or turn an
advisory concern into a rewrite.

## Gotchas

- Ambition without a contract becomes over-engineering. Keep the selection gate:
  a sufficient implementation is a reason to stop expanding.
- A line count is a probe, not a universal design law.
- Moving code across files without reducing coupling is not a successful
  decomposition.
- Passing tests do not erase a material architecture regression, but a style
  preference without impact is not a blocker.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Review proposes a rewrite for a tiny diff | Scope or trigger was too broad | Limit the review to changed behavior and material risks |
| Many low-value nits | No severity/materiality screen | Keep only findings with evidence and an actionable remedy |
| File is large but coherent | Threshold treated as a verdict | Record `ACCEPTED` with rationale and keep the stable boundary |
| Suggested split adds more indirection | Complexity moved, not removed | Reject it and compare the reader's concepts before/after |

## Source

Adapted from Cursor Team Kit's MIT-licensed `thermo-nuclear-code-quality-review`:
https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/thermo-nuclear-code-quality-review
