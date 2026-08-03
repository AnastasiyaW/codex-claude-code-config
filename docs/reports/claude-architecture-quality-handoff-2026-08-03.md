# Claude handoff: architecture quality and readable web services

Date: 2026-08-03
Status: implemented and verified

## Problem addressed

The previous harness had a good planning skill (`architecture-first`) and a live
whole-file shape hook, but the delivery contract for web applications was implicit.
That allowed a multi-page or backend feature to grow through locally minimal edits
until the code became difficult to read. This change makes the contract visible,
routeable and testable.

## What is now active

- `architecture-first`: use before the first file of a non-trivial service, site, API
  or subsystem. It decides modules, state ownership and dependency arrows.
- `architecture-quality`: use while implementing web/service code. It keeps routes
  thin, policy inward, feature boundaries explicit, and one vertical slice verifiable.
- `module-shape-advisor.py`: live `PostToolUse` advisory on `Write|Edit|MultiEdit` in
  both Codex and Claude. It reports whole-file lines, definitions, mutable module
  state and long functions/classes.
- `scripts/architecture_audit.py`: dependency-free repository report. It checks an
  architecture anchor and calibrated file-shape signals without pretending to infer
  domain boundaries.
- `harness-feedback`: use when a check is too strict, mis-scoped or blocks staging
  smoke. Report the profile mismatch; do not silently bypass it.

Live locations verified:

- Codex hooks: `~/.codex/hooks.json`
- Claude hooks: `~/.claude/settings.json`
- Public source of truth: `~/.claude/claude-code-config`
- `architecture-quality` synchronized to `~/.codex/skills` and `~/.claude/skills`

The `secret-leak-guard.py` registration was removed from the global Claude settings
file where it was found. The four requested settings locations were checked; all
existing JSON files remain valid and no registration remains.

## How Claude should work on a new web/service task

1. Load `architecture-first` and write or update `ARCHITECTURE.md` (or
   `docs/architecture/README.md`) with modules, ownership, dependency direction,
   data flow and the first vertical slice.
2. Load `architecture-quality` while adding pages, routes, handlers or adapters.
3. Keep policy/domain code independent of framework, ORM, queue and filesystem where
   practical. A route maps input/output; it does not become the business layer.
4. Run:

   ```powershell
   python scripts/architecture_audit.py --root <project>
   ```

5. If the project has committed dependency rules, run the stack-native check too:
   `import-linter` for Python, `dependency-cruiser` for JavaScript/TypeScript,
   ArchUnit for Java, or compiler/include/CMake boundary checks for C/C++.
6. Run focused behavior tests and the project test lane. Report architecture
   warnings separately from test proof; an advisory finding is not a passing proof.
7. If an intentional large module remains, record why and its owner. Use
   `CLAUDE_ALLOW_BIG_MODULES=1` only with that written explanation.

## Research used

- [Martin Fowler: linking modular architecture to team ownership](https://martinfowler.com/articles/linking-modular-arch.html)
- [dependency-cruiser: rules, cycles and forbidden edges](https://github.com/sverweij/dependency-cruiser)
- [import-linter: Python import contracts](https://github.com/seddonym/import-linter)
- [ArchUnit user guide](https://www.archunit.org/userguide/html/000_Index.html)
- [LLVM clang-tidy](https://clang.llvm.org/extra/clang-tidy/)
- [Microsoft Azure: microservice boundaries, Chinese](https://learn.microsoft.com/zh-cn/azure/architecture/microservices/model/microservice-boundaries)
- [Google Android: modularization, Chinese](https://developer.android.com/topic/modularization?hl=zh-CN)
- [AWS: decomposing monoliths, Chinese](https://docs.aws.amazon.com/zh_cn/prescriptive-guidance/latest/modernization-decomposing-monoliths/welcome.html)

The full decision record is in `docs/research/2026-08-architecture-readable-code.md`.

## Verification evidence

- `architecture_audit.py --self-test`: PASS, 4 checks.
- `module-shape-advisor.py --self-test`: PASS, 12 checks.
- `test_keyword_skill_router.py`: PASS; architecture-quality cases route correctly.
- `test_task_completion_hooks.py`: PASS on both live Codex and Claude settings,
  including the forbidden secret-leak-guard wiring check.
- `evals/hooks/run_hook_evals.py`: PASS, 34/34. The suite caught and the router then
  removed a false architecture-first match for an ordinary React dashboard styling
  request.
- `skill_lint.py skills --strict`: 44 skills, 44 clean, 0 findings.
- `audit_skill_hook_wiring.py --strict`: PASS; 51 active skills, 44 source skills,
  55 hooks, 26 curated routes.
- `validate_config.py --strict`: PASS, 36 files with no drift.
- skills lock and generated catalog checks: PASS, 44 skills.
- lifecycle hook contracts: PASS, 7 tests.

The normal audit of the configuration repository itself reports three pre-existing
long Python functions in `hooks/session-handoff-check.py`,
`scripts/recover_skill_trees.py` and `scripts/sync_public_config.py`. It has no
missing architecture anchor and exits zero in advisory mode. Those findings are
kept visible and are not presented as repaired by this change.

## Boundary and next action

No external architecture dependency was installed globally, and the dirty retouch
product worktree was not modified. The next useful proof is to run the audit against
the real web/service project Claude is about to change, then implement one vertical
slice and verify that its module boundary stays local without turning staging smoke
into a release-signing gate.
