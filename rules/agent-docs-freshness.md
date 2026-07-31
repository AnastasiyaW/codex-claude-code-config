---
paths:
  - "**/docs/kb/**"
  - "**/docs/layers/**"
  - "**/scripts/validate_kb.py"
  - "**/openwiki/**"
  - "**/.github/workflows/kb.yml"
---

# Agent-Docs Freshness — force repo docs to stay written AND current (mechanical)

## Principle (2026-07-07)

Docs that coding agents rely on are only useful if they **exist**, are **correct**
(references resolve), and are **current** (track the code). "Docs exist" ≠ "docs
current" — and a doc the agent cannot trust is operationally absent
(agent-legible-environment). We already have the *authoring* side (kb-skeleton,
`docs/kb/`, `docs/layers/`, feature narratives) and a *correctness* validator
(`scripts/validate_kb.py`) — but enforcement lived only in **CI (on push/PR)**, so
a whole session could drift with a stale KB and get caught late or never.

This rule closes that: keep the human-curated KB, add **mechanical, tested,
defence-in-depth enforcement** that a repo which *adopted* the KB cannot silently
let it rot. Adapted from [OpenWiki](https://github.com/langchain-ai/openwiki) (MIT — auto-generates a
repo wiki and refreshes it so agents read current context). We take the
**mechanical half** (freshness + pointer detection) natively; generation stays a
token-costed opt-in (see below), not a hook.

## Three enforcement tiers (defence-in-depth; all opt-in by artifact presence)

| Tier | Mechanism | When | Blocking? | Fires only if | Checks |
|---|---|---|---|---|---|
| 1. Freshness advisory | `docs-staleness-guard.py` | SessionStart | No (nudge) | `openwiki/` or `docs/layers/` present | git-staleness + AGENTS.md pointer |
| 2b. Adoption gate (docs EXIST) | `kb-validate-gate.py` | Stop | **Yes (blocks close)** | `feature_list.json` present (= [LONG-RUN]) | a long-run project must carry a KB |
| 2. Correctness gate (docs CURRENT) | `kb-validate-gate.py` | Stop | **Yes (blocks close)** | `scripts/validate_kb.py` present | runs the repo's own `validate_kb.py` |
| 3. CI gate | `.github/workflows/kb.yml` | push / PR | Yes | committed in repo | same `validate_kb.py` |

Tiers 2+3 run the **same** project validator — tier 2 just moves the gate earlier
(local session close, not only remote CI). No validation logic is reinvented.

### Tier 1 — freshness (what CI/validate_kb do NOT catch)
`validate_kb.py` checks *reference integrity* (dead paths, missing module docs,
dead pointers) but not "the code moved ahead and nobody refreshed the docs".
`docs-staleness-guard.py` adds the git signal (git = source of truth):
`base = last commit that touched the anchor`; every commit in `base..HEAD` by
construction did **not** touch the anchor, so its count = how far docs fell behind.
`>= CLAUDE_DOCS_STALE_COMMITS` (default 20) → nudge. Plus the OpenWiki pointer
check: `openwiki/` present but not referenced from `AGENTS.md`/`CLAUDE.md` → the
docs exist but agents are not told to read them. Advisory only, fail-open, anti-nag
stamp (`.claude/.docs-staleness-nudged`, 7-day cooldown). Opt-out:
`touch .claude/.skip-docs-staleness`.

### Tier 2b — adoption (force docs to EXIST, scoped)
`kb-validate-gate.py` also **blocks Stop** when a project has declared itself
`[LONG-RUN]` (has `feature_list.json`) yet carries NO agent docs at all
(`docs/kb/` and `docs/layers/` both absent, no validator). This forces a long-run
project to actually *start* a KB — the "документация делается" half. Scoped to
opted-in projects **on purpose**: hard-blocking every folder without docs would
wedge sessions across all projects (the non-monotonic-harm pattern) and contradict
`long-run-harness.md` (the [LONG-RUN] mark is a human decision by design). Same
escape hatch as tier 2.

### Tier 2 — correctness (the «принудительно» / forcing tier)
`kb-validate-gate.py` (Stop) runs the repo's configured `scripts/validate_kb.py`
and **refuses to end the session** while it exits 1 (KB out of sync), surfacing the
validator's own output as the block reason. Same shape as `problems-md-validator.py`
/ `feature-list-validator.py`: opt-in (silent unless `scripts/validate_kb.py`
exists), anti-loop (`stop_hook_active`), fail-**open** on infra (validator exit 2 /
crash / timeout never wedges a session shut). Bypass: `CLAUDE_SKIP_KB_GATE=1` or
`touch .claude/.skip-kb-gate`.

## Generation is opt-in and token-costed (NOT a hook)
Auto-*generating* the wiki (OpenWiki `openwiki --init` / `--update`, or writing
`docs/layers/`) needs LLM calls → external-provider tokens → **opt-in only**, with
a spend cap, per `safety.md §`. The hooks here **detect** staleness for
free; they never spend tokens. Do not wire OpenWiki's daily GitHub Action until
quality + cost are seen on a couple of manual runs. Note: OpenWiki is fresh
(released ~2026-07-02); `min-release-age=7` in `~/.npmrc` gates `npm i -g openwiki`
— which doubles as supply-chain buffer.

## Adoption (who turns tier 2/3 on)
Adoption stays a human decision, but the PROPOSAL is automatic (user directive
2026-07-07): when a project **looks complex** (long-run signals: ≥3 handoffs /
≥40 commits / ≥200 tracked files / PROBLEMS.md) and has **no agent-docs tree**,
`long-run-detector.py` (SessionStart) explicitly proposes adopting the KB
(kb-skeleton: `docs/kb` + `scripts/validate_kb.py`) alongside the long-run
harness — surface it to the user as a concrete offer, not silence. Other
triggers: `/harness-audit`, scaffolding `templates/kb-skeleton/`. Once
`scripts/validate_kb.py` + docs exist, tiers 2+3 enforce automatically. A repo
with no KB pays nothing (one `Path.exists()`); already-adopted `[LONG-RUN]`
repos without docs are caught by tier 2b instead.

## Anti-patterns
- ❌ Relying on CI alone → drift caught only after push, or never if CI unwired.
- ❌ Blocking freshness for EVERY repo → non-monotonic (arXiv 2601.22025); tier 1 is
  advisory, tiers 2/3 are opt-in by artifact presence.
- ❌ Auto-generating docs on a schedule without a spend cap → billing burn (§`safety-billing`).
- ❌ Reinventing validation in the hook → tier 2 runs the project's own `validate_kb.py`.
- ❌ Treating auto-generated wiki as ground truth → it is `semi_trusted`; curated
  layer docs / INVARIANTS stay canon.

## Mechanically (wired, tested)
- `docs-staleness-guard.py` — SessionStart, advisory, `--self-test` (real temp git repo).
- `kb-validate-gate.py` — Stop, blocking, `--self-test` (spawns real pass/fail validators).
- Registered in the active Claude Code and Codex hook configuration; both fail-open and have an escape hatch.
- Reuses `templates/kb-skeleton/scripts/validate_kb.py` + `.github/workflows/kb.yml`.

## Related
- `principles/21-knowledge-base-enforcement.md` — parent principle (validate_kb, kb-skeleton).
- `principles/28-feature-layer-architecture.md` — `docs/layers/` anchor.
- `long-run-harness.md` — adoption trigger; `long-run-detector.py` nudge.
- `safety.md` — generation token cost (OpenWiki providers, daily Action).
- `git-source-of-truth.md` — git-based staleness signal.
- `finish-the-task.md` / `no-pre-existing-evasion.md` — docs are part of "done", not deferred.
- OpenWiki (MIT): https://github.com/langchain-ai/openwiki — the adapted tool.
