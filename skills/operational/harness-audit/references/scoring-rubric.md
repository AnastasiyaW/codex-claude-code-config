# Scoring Rubric

Score each subsystem against the project's applicable outcomes in [the checklist](checklist-per-subsystem.md), its declared acceptance, and the evidence actually inspected. The numbers are anchored; exact filenames, a fixed line count, or a fixed number of artifacts are not.

## Evidence boundary and caps

- `documented` proves that a convention is stated or configured. It does not prove a runtime, CI, hook, schema, or workflow result.
- `demonstrated` requires a current inspectable receipt appropriate to the claim: for example, a command result, hook trace, validated record, or sampled handoff that actually supports the stated status.
- If an applicable subsystem is only documented, cap it at **3**. If it is demonstrated but not documented well enough to repeat safely, cap it at **3**. If it is documented and demonstrated but consistency is unknown, cap it at **4**.
- Do not require runtime evidence for a documentation-only acceptance. When runtime behavior is part of the declared acceptance, lack of runtime evidence is `unknown`, not a pass.
- If a requirement is not applicable to the project's delivery model, say why and omit it from the subsystem judgment; do not turn that omission into a failure or an automatic 5.

## The five levels

### 5 — Exemplary

All applicable outcomes are documented, demonstrated by current inspectable evidence, and consistently followed in the available relevant sample. Mechanical enforcement, schemas, hooks, or CI have execution evidence where they are the chosen control. This subsystem is a credible model for comparable projects.

### 4 — Good, mostly complete

The applicable foundation is documented and demonstrated. One or two bounded gaps remain, such as incomplete enforcement coverage, a weaker supporting signal, or limited but sufficient continuity evidence. It is functional and unlikely to be the bottleneck.

### 3 — Adequate, partial, or uncertain

Some applicable outcomes work, but the evidence is incomplete: the subsystem is only documented, only demonstrated, lacks a material continuity element, or has a relevant unknown boundary. It provides a usable base but is likely to degrade or become unreliable across handoffs.

### 2 — Weak, incomplete

The project has isolated structure or historical artifacts, but it does not meet most applicable outcomes. The remaining convention is accidental, stale, or cannot support the stated delivery model. This is normally the bottleneck.

### 1 — Missing or actively harmful

The applicable subsystem is structurally absent, or its documented behavior is actively unsafe, contradictory, or misleading. Fix it before adjacent improvements can reliably pay back.

## Calibration rules

### Project model before artifact names

`PROBLEMS.md` and `feature_list.json` are strong conventions for a long-running feature project, but neither is a universal State requirement. A current issue tracker, changelog, release record, or other inspectable durable source can satisfy a project's actual continuity need. Conversely, a feature project with no current locator for active scope or deferred work has a material State gap even if it has many handoffs.

Likewise, a 400-line instruction entrypoint is a navigability concern to investigate, not an automatic Instructions failure. Score whether the agent can find applicable constraints and startup guidance, whether the hierarchy is coherent, and whether current evidence supports use. Use the 200-line signal to recommend a simplification only when the observed instructions are difficult to navigate or causing drift.

### Evidence and enforcement

Inspect enough recent, relevant artifacts to establish a pattern without fabricating a sample size. A configured hook, non-empty evidence field, existing `init.sh`, or validator script is not a behavior receipt. When no receipt is available, report `unknown` and apply the caps rather than inferring success.

Mechanical enforcement is evidence only when it is the project's chosen control and its execution is inspectable. Do not lower a knowledge repository merely because it lacks hooks designed for an application deployment; do lower a project that relies on hooks but cannot show that they execute.

### Avoid double counting and grade drift

Assign a gap to the subsystem it affects. A missing documented verification command is Verification, not Lifecycle. Do not reward intent or a plan to add an artifact. Do not grade-inflate merely because a familiar filename exists, and do not grade-deflate a project that meets its actual contract through a different, inspectable mechanism.

## Calibration examples

These are text-scenario evaluations of the contract below, not runtime execution receipts.

### Example 1: Fresh prototype repository

- 50-line `CLAUDE.md`, mostly project description; one test file; no `.claude/` directory; some recent commits.

- Instructions: **2** — an entrypoint exists, but it does not supply usable project guidance or constraints.
- State: **1** — no evidence of continuity, active scope, or deferred-work record for work that must continue.
- Verification: **2** — a test exists, but no documented verification path or current receipt establishes the boundary.
- Scope: **2** — no explicit scope/done/defer policy; drift is not controlled.
- Lifecycle: **1** — no documented boundary behavior or evidence of a recovery convention.

### Example 2: Mature feature project with older conventions

- 400-line but navigable `CLAUDE.md`; five modular rule files; a current handoff demonstrates the startup route and rule use.
- Thirty handoffs over six months and a current index, but no current record that locates active scope and deferred work.
- A current CI or local receipt demonstrates the documented Makefile-based verification command.
- Settings define SessionStart and Stop hooks; one current hook execution trace is available. Recent records demonstrate the project-specific scope policy.

- Instructions: **4** — documented and demonstrated; length is a bounded navigability signal, not a failed prerequisite.
- State: **3** — demonstrated handoff continuity, but the feature project lacks a material current scope/deferred-work locator. `PROBLEMS.md` and `feature_list.json` would be suitable fixes, not scoring prerequisites.
- Verification: **4** — documented command plus current receipt; bounded gaps remain.
- Scope: **4** — documented and demonstrated; no serialized WIP limit is required because there is no declared serialized lane.
- Lifecycle: **4** — documented hooks plus a current trace; remaining lifecycle evidence is bounded.

### Example 3: Public knowledge/skill repository

- Agent instructions, principles, rules, templates, hooks, maintenance guidance, and current validators.
- A current changelog/release record serves as the project's durable continuity record; it has no feature-delivery backlog and no reason to serialize independent documentation work.
- Validators exist, but the repository has no documented command that maps required validators to the project acceptance and no current aggregate receipt.

- Instructions: **4** — project-specific guidance is documented and current maintenance artifacts demonstrate its use; additional review routing would be improvement, not a universal requirement.
- State: **4** — the current release/changelog record demonstrably meets this knowledge repository's continuity need without a feature tracker.
- Verification: **2** — validators alone are isolated structure; the usable verification path and current result are not established.
- Scope: **4** — the documented model and maintenance history cover scope; a WIP=1 policy is not applicable to independent documentation work.
- Lifecycle: **3** — boundary conventions exist, but lifecycle execution coverage is partial or unknown.
