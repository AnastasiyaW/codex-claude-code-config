---
name: architecture-quality
description: >
  Keep web applications, APIs and services readable as they grow: choose feature or
  domain seams, assign state ownership, enforce dependency direction, keep adapters
  thin, and verify file shape. Use when starting or extending a web app, backend,
  frontend, API or multi-page product; when a change makes a module hard to read;
  when architecture review finds a god file, cross-feature imports, a circular
  dependency or a framework-heavy domain. Load architecture-first first for a new
  system, and refactoring-safely for an existing oversized module. Do not use for a
  one-file script, throwaway spike or a purely local naming change.
---

# Architecture quality — readable by construction

This skill turns the architecture decision into a small, repeatable delivery
contract. It complements `architecture-first`; it does not add layers for their own
sake.

## Working contract

Before a non-trivial web or service change, record these five facts in
`ARCHITECTURE.md` or `docs/architecture/README.md`:

1. **Feature/domain modules** — name them by reason to change, not by a generic
   `utils`, `helpers` or `services` bucket.
2. **Ownership** — each mutable state, database table boundary and external side
   effect has one owner.
3. **Dependency direction** — policy/domain code is independent of the web
   framework, ORM, queue and filesystem; adapters point inward through small ports.
4. **Vertical slice** — prove one user-visible path from entry point to state and
   test before multiplying layers or pages.
5. **Verification boundary** — list the architecture checks and the test command
   that must remain green after the change.

If the project is a small script or a single-module experiment, state that scope and
skip the document. A missing document is a finding only once the project has enough
shape to need one, not a reason to create ceremony around a toy.

## Web application shape

- Keep routes/controllers thin: parse input, call a use-case or feature API, map the
  result and return. Do not put business policy, SQL and provider retries in a route.
- Keep domain/use-case code framework-free where practical. Inject ports for storage,
  clocks, queues and providers; keep concrete adapters at the edge.
- Organize user-facing behavior by feature or bounded context. A page may compose
  features, but one feature must not reach into another feature's private state.
- Give each page a stable route-level composition boundary. Shared UI primitives are
  visual primitives, not a second business-logic layer.
- Treat a `utils` or `common` import that keeps growing as a boundary question. Move
  code to the module that owns its reason to change; do not create a universal bag.
- Prefer a modular monolith until an independently deployable or scalable boundary is
  proven. A microservice split is not a substitute for a missing internal boundary.

## Shape checks

Run the repository audit before broadening a new app and after a structural change:

```powershell
python scripts/architecture_audit.py --root .
```

The audit is intentionally conservative. It reports, rather than invents, findings:

- a sizeable application with no `ARCHITECTURE.md` or architecture directory;
- a source file crossing the calibrated shape thresholds;
- an explicitly declared project marker without a readable architecture anchor.

The live `module-shape-advisor.py` hook repeats the file-shape check after
`Write|Edit|MultiEdit` in both Codex and Claude. It is advisory: acknowledge the
finding, split at an ownership boundary, or record why the file is intentionally
large. `CLAUDE_ALLOW_BIG_MODULES=1` is an explicit, reviewable escape hatch, not a
default.

For dependency rules, use the tool native to the stack when the project has earned
it:

- Python: `import-linter` contracts for allowed import direction;
- JavaScript/TypeScript: `dependency-cruiser` for cycles, orphans and forbidden
  folder edges;
- Java: `ArchUnit` architecture tests alongside unit tests;
- C/C++: compiler/include tooling plus explicit CMake target boundaries; do not infer
  a domain architecture from a raw include graph alone.

Do not install all four. Pick one boundary mechanism, commit its rules, and run it in
the same CI lane as the tests that prove the behavior.

## Review questions

- Can a new feature be changed without editing an unrelated feature's internals?
- Does a route, page or controller own policy that belongs inside a use-case/domain?
- Is state ownership named, or are modules reaching into shared mutable objects?
- Are imports crossing a documented boundary? If yes, is the exception recorded with
  a reason and expiry?
- Is the file becoming large because one change is crossing multiple reasons to
  change? If yes, split the seam before adding more behavior.
- Did the change update the architecture document and the focused architecture/test
  evidence together?

## Gotchas

- **Folders are not boundaries.** Moving files without changing imports or ownership
  only makes the same coupling harder to see.
- **Thin controllers can still hide a fat service.** Inspect the next boundary; a
  generic `ApplicationService` is often a god module with a nicer name.
- **A metric is a signal, not a verdict.** Generated code, migrations and large
  declarative tables need explicit exemptions; production logic needs an explanation
  before an exemption.
- **Microservices can multiply unreadability.** Network boundaries add failure,
  deployment and observability costs; prove the module boundary first.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| The audit reports a missing architecture anchor | An app marker and several source files exist, but the boundary is implicit | Write the small module/ownership/dependency map before adding more features |
| `module-shape-advisor` reports a large file | Local edits accumulated in one ownership boundary | Add characterization tests, split one named slice, then rerun the audit |
| A cycle appears | Two modules own part of the same concept or one imports an implementation detail | Move the concept behind an inner port or extract a genuinely shared concept |
| Every change touches many folders | Layer-first layout scatters a feature across technical layers | Recut the next slice by feature; migrate incrementally with tests |
| The guard is noisy on generated code | The file is outside the built-in exemption list | Add a narrow, documented project exemption; do not silence the whole hook |
