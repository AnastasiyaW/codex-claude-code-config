# Readable architecture for web applications and services

Date: 2026-08-03
Status: adopted as a tested harness improvement

## Decision

Use a small three-part contract:

1. `architecture-first` decides seams, ownership and dependency direction before a
   new service, site, API or subsystem grows.
2. `architecture-quality` keeps those decisions usable during implementation: thin
   adapters, feature/domain slices, one owner for mutable state and an architecture
   anchor in Git.
3. `module-shape-advisor.py` and `scripts/architecture_audit.py` provide mechanical
   signals for whole-file growth and missing architecture evidence.

The signal is advisory, not a universal blocking gate. A generated file, migration or
deliberately large declarative module can be exempted with a narrow documented reason.
Production logic should not be silenced without an ownership decision and evidence.

## What the research confirms

### English sources

- Martin Fowler's modular architecture material treats bounded contexts and modular
  boundaries as a way to contain the blast radius of change and align structure with
  team ownership: [Linking Modular Architecture to Development Teams](https://martinfowler.com/articles/linking-modular-arch.html).
- `dependency-cruiser` validates a project's own dependency rules and can report
  circular dependencies, orphans and forbidden edges for JavaScript/TypeScript:
  [repository and rule reference](https://github.com/sverweij/dependency-cruiser).
- `import-linter` provides explicit import contracts for Python rather than asking a
  model to infer architecture from names: [project repository](https://github.com/seddonym/import-linter).
- ArchUnit makes architecture rules executable tests beside Java unit tests and can
  check package/layer dependencies and cycles: [user guide](https://www.archunit.org/userguide/html/000_Index.html).
- LLVM's `clang-tidy` supplies C++ readability, core-guideline and static-analysis
  checks. It improves code quality but does not replace domain/module boundaries:
  [official documentation](https://clang.llvm.org/extra/clang-tidy/).

### Chinese sources

- Microsoft Azure guidance says service boundaries should consider domain, team,
  data, scaling, availability and security; if two parts communicate too often they
  likely belong together: [微服务边界](https://learn.microsoft.com/zh-cn/azure/architecture/microservices/model/microservice-boundaries).
- Google's Android guidance warns that modules that are too large recreate the
  monolith, while too many tiny modules add cost: [模块化](https://developer.android.com/topic/modularization?hl=zh-CN).
- AWS Prescriptive Guidance keeps a modular monolith as a valid target when service
  boundaries are unclear rather than splitting blindly:
  [拆分单体应用](https://docs.aws.amazon.com/zh_cn/prescriptive-guidance/latest/modernization-decomposing-monoliths/welcome.html).

## What we adopted and what we did not

Adopted:

- feature/domain-first ownership rather than a universal layer or `utils` bucket;
- a modular monolith as the default until an independent deploy/scale boundary is
  proven;
- executable shape feedback after `Write|Edit|MultiEdit` in both Codex and Claude;
- one dependency-rule tool per project when the stack and size justify it;
- a repository-level, dependency-free audit that reports evidence without guessing
  semantic boundaries.

Not adopted globally:

- installing `dependency-cruiser`, `import-linter`, ArchUnit or extra C++ tooling in
  this configuration repo;
- making file-size thresholds a hard blocker;
- a generic architecture linter that claims to understand every language and domain;
- microservices as a default architecture.

## Verification contract

For a new web/service project:

1. Invoke `architecture-first` and record the module/ownership/dependency map.
2. Invoke `architecture-quality` while implementing the first vertical slice.
3. Run `python scripts/architecture_audit.py --root <project>`.
4. Run the project's native dependency contract if one is committed.
5. Run focused behavior tests, then the release lane required by the changed boundary.
6. If a gate is noisy or blocks the wrong profile, report it through
   `harness-feedback`; do not silently bypass it.

The audit has two modes: normal mode reports advisory findings and exits zero;
`--strict` turns findings into a CI failure after the project has calibrated its
exemptions. This keeps staging smoke from being forced to prove release architecture
attestation while still making the evidence visible.
