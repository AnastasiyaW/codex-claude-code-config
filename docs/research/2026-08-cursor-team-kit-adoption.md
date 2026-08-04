# Cursor Team Kit adoption

**Date:** 2026-08-05
**Decision:** selective adoption after source comparison
**Public source:** this file contains no private transcripts, machine paths, or credentials.

## What was verified

The official Cursor plugin manifest describes a MIT-licensed, third-party-free
team kit for CI, code review, shipping, test reliability, control-cli,
control-ui, verification, cleanup, and work summaries. The repository currently
ships 18 skills, two agents, and two always-on rules. See the [official
marketplace entry](https://cursor.com/marketplace/cursor/cursor-team-kit), the
[plugin manifest](https://raw.githubusercontent.com/cursor/plugins/main/cursor-team-kit/.cursor-plugin/plugin.json),
and the [source directory](https://github.com/cursor/plugins/tree/main/cursor-team-kit).

## Adoption matrix

| Cursor component | Existing local equivalent | Decision | Reason |
|---|---|---|---|
| `verify-this` | `proof-verify` and `testing-strategy` | **Adopted** | Claim-level baseline/treatment comparison is narrower than a frozen multi-AC proof loop and fills a real gap. |
| `control-cli` | Installed locally, absent from public source | **Promoted** | Repeatable interactive CLI/TUI evidence is useful for Windows/C++ tooling and should not depend on an untracked install. |
| `control-ui` | Browser/CDP skills exist, but no general evidence contract | **Adopted** | Adds stable-marker selection and before/after UI evidence without requiring a new dependency. |
| `deslop` | Installed locally; `lean-code` and architecture skills exist | **Promoted** | Narrow diff cleanup is a distinct workflow; guardrails prevent it becoming an unverified rewrite. |
| strict quality reviewer | `deep-review`, `architecture-quality`, `module-shape-advisor` | **Adopted as opt-in mode** | Keeps Cursor's useful code-judo/shape prompts while making materiality, evidence, and no-overengineering explicit. |
| `workflow-from-chats` | `session-feedback-capture` + `distill-feedback` + `feedback-pending-show` | **No duplicate** | Our loop already queues sessions, uses semantic extraction, deduplicates, and keeps human approval before rules change. |
| `ci-watcher` | GitHub skills and CI commands | **Promoted as agent** | The on-demand workflow is reusable; background behavior remains host-dependent and is not claimed as active automatically. |
| `loop-on-ci`, `fix-ci`, `review-and-ship`, `new-branch-and-pr`, `get-pr-comments`, `make-pr-easy-to-review` | Existing GitHub/review/merge workflows | **No duplicate** | Importing aliases would create several names for the same delivery path. |
| `run-smoke-tests`, `check-compiler-errors` | `testing-strategy`, project test policies, compiler-specific skills | **No global duplicate** | These belong to a project's commands and language surface, not a universal hook. |
| `pr-review-canvas`, `what-did-i-get-done`, `weekly-review` | Handoffs, chronicles, review reports | **No duplicate** | Existing durable artifacts cover the same state; add only if a measured workflow gap appears. |
| TypeScript rules | Main C++/Python focus | **Deferred** | `no-inline-imports` and exhaustive union switches are language-specific and should be adopted only by TypeScript projects. |

The upstream descriptions are concise and useful, but they are guidance rather
than proof. The adopted skills therefore include explicit boundaries, privacy
rules, Windows-safe harness notes, evidence requirements, gotchas, and
troubleshooting sections from this repository's skill contract.

## Verification performed

The adoption is accepted only when the following deterministic checks pass:

```text
python scripts/test_cursor_team_kit_adoption.py
python scripts/skill_lint.py skills --strict
python scripts/generate_skills_catalog.py --check
python scripts/generate_skills_lock.py --check
python scripts/test_keyword_skill_router.py
python scripts/audit_skill_hook_wiring.py --strict
```

The proof target is wiring and artifact integrity, not a claim that a background
agent is currently running. A live CI watcher must be proved from process/PR
state when requested.

## Rejected shortcut

Do not install the entire Cursor plugin as a second global harness. It would
duplicate our feedback loop, proof loop, GitHub delivery path, and architecture
checks while making ownership unclear. The source is valuable as a set of
small, composable patterns; the public repository remains the single source of
truth for the adopted variants.
