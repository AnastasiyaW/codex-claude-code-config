# Per-Subsystem Checklist

Use this checklist to collect evidence, not to impose one repository layout. Record each observation as `documented`, `demonstrated`, or `unknown`: a file, setting, or field is not proof that its behavior ran.

## Apply the contract before counting signals

Identify the project's actual delivery and continuity needs first: for example, a feature-delivering long-running project, a knowledge repository, a short research repo, or a service with mutable shared resources. Then assess the applicable outcomes below.

- **Required outcomes** are scored when the project needs them. A missing outcome is a gap.
- **Supporting signals** are useful ways to prove an outcome, not universal prerequisites. `CLAUDE.md`, `PROBLEMS.md`, `feature_list.json`, `init.sh`, and hooks are canonical examples in this stack, not compulsory names or formats.
- Do not infer a runtime, CI, hook, or schema result from its configuration. If no appropriate receipt is available, record `unknown`.
- A line count is a maintainability signal. It is never sufficient evidence that instructions are good or a standalone reason to lower a score.

Score the collected observations with [the scoring rubric](scoring-rubric.md). Do not add a second numeric formula here.

---

## 1. Instructions (How the agent knows what to do)

### Required outcomes

- [ ] An agent-facing entrypoint or clear route identifies the project's operating instructions.
- [ ] It communicates the project-specific constraints and the work-start path needed for the project's risk.
- [ ] Hard constraints are distinguishable from preferences where both exist.
- [ ] Available evidence shows the instructions are usable and do not contradict each other.

### Supporting signals

- [ ] `CLAUDE.md` or `AGENTS.md` is the entrypoint; `.claude/rules/` separates conditional detail.
- [ ] The entrypoint stays compact enough to navigate; under 200 lines is a useful prompt-budget signal, not a requirement.
- [ ] `REVIEW.md` exists when the repository uses PR review.
- [ ] A startup route names what to read first and sampled referenced paths resolve.

---

## 2. State (What the project knows about itself)

### Required outcomes

- [ ] Work that must survive a session has a durable, inspectable continuation record.
- [ ] For a project delivering features or changes, active scope and unresolved/deferred work have a current, inspectable location.
- [ ] The record is usable for the project's handoff cadence; if no cross-session continuity is needed, explain why it is not applicable.
- [ ] Sampled records support their claimed status rather than merely naming an evidence field.

### Supporting signals

- [ ] `PROBLEMS.md` records active/deferred issues and statuses.
- [ ] `feature_list.json` (or an equivalent tracker) records feature identity, status, and acceptance evidence.
- [ ] `.claude/handoffs/` has recent, usable handoffs; `INDEX.md` and timestamped names improve retrieval.
- [ ] A chronicle, changelog, release record, or issue tracker can meet the continuity need of a knowledge or release-oriented project.
- [ ] `[LONG-RUN]` projects have a project chronicle when their operating model requires it.

---

## 3. Verification (How does the project know it works)

### Required outcomes

- [ ] A documented, target-appropriate bootstrap or verification command exists; `init.sh` is one possible convention.
- [ ] The documented command covers the checks required by this project's declared acceptance.
- [ ] The project has a test, validator, or other check where its risk and target call for one.
- [ ] A current, inspectable receipt demonstrates the required boundary when the audit claims that it passed.

### Supporting signals

- [ ] A test runner is configured and has an enabled relevant test.
- [ ] Instructions reference a staged validation/proof process appropriate to the project.
- [ ] CI or equivalent runs the same required checks when the project uses CI.
- [ ] Completion records link to inspectable acceptance evidence.

Runtime proof is required only when the declared acceptance requires runtime behavior. Configuration alone remains `documented`, not `demonstrated`.

---

## 4. Scope (Does the agent stay in bounds)

### Required outcomes

- [ ] The project states its in-scope boundary and an explicit definition of done for work that changes it.
- [ ] Deferral has named valid reasons and a durable destination when work is intentionally left out.
- [ ] A policy protects shared mutable resources when they exist; independent or read-only work is not penalized for omitting a serialized WIP limit.
- [ ] Available history or task records show that the policy is followed, or the audit labels this `unknown`.

### Supporting signals

- [ ] Rules name in-scope work and completion criteria.
- [ ] An issue/status tracker distinguishes valid deferred states.
- [ ] A stop hook or equivalent checks unresolved work when that enforcement is warranted.
- [ ] Sampled handoffs and commits do not abandon work without its registered destination.

---

## 5. Lifecycle (What happens at session boundaries)

### Required outcomes

- [ ] The project documents the session-boundary behavior it actually needs, including entry and verification when applicable.
- [ ] Required boundary controls have current evidence of execution; a configured hook without a trace is `documented` only.
- [ ] The project has a clean-state or recovery convention proportionate to its risk.

### Supporting signals

- [ ] `.claude/settings.json` or `.claude/settings.local.json` configures needed lifecycle hooks.
- [ ] Stop, handoff, backup, and cleanup hooks are used where their protected risk exists.
- [ ] Recent handoffs show sessions end with recoverable state.

---

## How to Apply When Auditing

1. Mark the delivery model and which required outcomes apply before reviewing artifacts.
2. For each applicable outcome, record the smallest direct evidence and its status: `documented`, `demonstrated`, or `unknown`.
3. Use supporting signals to explain confidence, never as a substitute for the outcome.
4. Use the rubric's documented/demonstrated caps; a 5/5 remains exemplary, not merely a count of files.
5. Keep an audit-only request read-only. A requested repair may use the findings as input, but its implementation proof is separate from the audit scorecard.
