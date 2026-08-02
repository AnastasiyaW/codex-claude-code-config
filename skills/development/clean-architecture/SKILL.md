---
name: clean-architecture
description: >
  Clean Architecture operational rules distilled from Robert Martin's "Clean Architecture"
  and Giordani's "Clean Architectures in Python" (both books parsed in full). AUTO-APPLY on
  ANY coding process: writing new code, adding a feature, refactoring, designing a module /
  service / API, structuring a new project, code review, choosing a framework or dependency,
  splitting a monolith, wiring a database or web layer. Triggers: "напиши код", "добавь фичу",
  "сделай сервис/модуль/класс", "спроектируй", "refactor", "implement", "new project",
  "architecture", "структура проекта", "куда положить код", "какой фреймворк". Key
  capabilities: the Dependency Rule, SOLID applied correctly, component cohesion/coupling
  (REP/CCP/CRP, ADP/SDP/SAP + I/A/D metrics), boundaries and Humble Object, entities vs use
  cases, DB/web/frameworks-as-details, Python implementation recipes (entities, use cases,
  repositories, request/response objects, integration testing, prod wiring).
  Do NOT use for a one-file script or a throwaway experiment, for a bug fix inside an
  existing seam that does not move a boundary, for word-level style and naming (use
  clean-code), or for splitting a module that has already grown too large (use
  software-design-philosophy — that is a cut, this is a layout). This skill decides where
  code LIVES; it is not a licence to add layers a project has not earned.
---

# Clean Architecture — always-on coding guardrails

Distilled from two books read cover-to-cover: **Robert C. Martin, "Clean Architecture"**
(theory: principles, components, boundaries) and **Leonardo Giordani, "Clean Architectures
in Python" 2nd ed.** (practice: a working Python implementation, TDD, real DB integration,
production). All content paraphrased into operational rules.

## Scope guard — scale to the problem (read first)

Clean architecture is a set of guidelines, not a checklist to apply blindly (Giordani's own
framing). Combined with our `quality-code` rule (minimal correct architecture, YAGNI):

- **Throwaway script / one-off tool** → apply only §1 (dependency direction) and naming
  hygiene. Do NOT scaffold layers, interfaces, request objects. The abstraction tax must pay.
- **Anything expected to live, grow, or be tested** → apply the core rules below.
- **Multi-module system / service / long-run project** → also load the relevant
  `references/` file before designing.
- Architecture must be *sized to the problem*: layers that isolate nothing anyone will
  change are pure overhead. Every deliberate rule break gets a loud comment
  (`# simplification: ...` per our quality-code convention).

## 1. The Dependency Rule (the single law — never violate silently)

Source-code dependencies point **only inward**, toward higher-level policy:

```
External systems (web fw, CLI, DB engine, msg bus)   ← outermost, most volatile
  → Gateways / adapters (repo impls, controllers, presenters, ALL SQL/HTTP-client code)
    → Use cases (application-specific business rules)
      → Entities (domain models, business vocabulary)  ← innermost, most stable
```

- Inner code never names anything from an outer ring: no framework imports, no ORM types,
  no HTTP request/session objects, no SQL in use cases or entities.
- **Golden Rule (Giordani): talk inward with plain data, talk outward through interfaces.**
  Outer→inner = direct call with plain structures. Inner→outer (use case needs storage) =
  through an interface the inner layer owns; concrete impl injected at the composition root.
- What crosses a boundary: simple DTOs / dicts / dataclasses shaped for the **inner** side.
  Never entities, never DB rows, never framework objects.
- The API belongs to the caller (policy side), not the implementor.
- Quick audit: read the imports. `domain/` imports stdlib only; `use_cases/` imports domain;
  everything else may import inward, never the reverse.

## 2. Pre-code checklist (before writing/changing code)

1. **Who is the actor?** One module = one actor = one reason to change (SRP). Persistence,
   reporting, and business calculation almost always serve different actors — keep apart.
2. **Which way do new dependencies point?** Toward policy/stability. High-level code needing
   a low-level service → define the interface on the high side, implement on the low side.
3. **Is this a detail?** DB engine, web framework, UI platform, vendor SDK, delivery
   mechanism = details → behind a boundary, swappable, wired only in main/composition root.
4. **Adding a variant of existing behavior?** Add code (new implementation of an existing
   interface), don't edit shared policy (OCP). Cascading edits across modules = design flag.
5. **True or accidental duplication?** Unify only if all copies must always change together
   for the same reason. Same-shape-today but different-evolution → keep separate.
6. **Testable by construction?** Business logic must run in a plain test harness with no
   server, no DB, no framework booted. "Hard to test" = architecture smell, not tooling gap.
7. **Cycle check:** new inter-module dependency must not create a cycle (break with an
   interface or an extracted shared module — never ship the cycle).

## 3. Review checklist (after code exists)

- Imports audit passes (§1). No framework annotations/base classes on domain objects.
- All SQL/ORM/HTTP-client code lives in gateway implementations; use cases see intent-named
  interfaces (`repo.list_rooms_with_status(...)`, not query text).
- Views/handlers are humble: translation only (parse input → build request → call use case →
  map response to transport). All formatting decisions in presenters/serializers.
- Use cases never raise across their boundary — they return response objects
  (SUCCESS / PARAMETERS_ERROR / RESOURCE_ERROR / SYSTEM_ERROR); transport-code mapping lives
  in the gateway.
- Repositories return domain entities (assert `isinstance` in at least one test per impl),
  normalize input types at the boundary, translate neutral filter grammar to native queries.
- Wiring/DI/config literals concentrated in main/composition root; multiple roots per
  environment instead of env-flags deep in code.
- Visibility minimized: public only what has legitimate external consumers — the compiler
  (or module system) enforces the boundary, not code review discipline.
- After changing a use-case signature: sweep every adapter (endpoints, repos, CLI) + one
  end-to-end check. Green all-mocked unit tests prove nothing about wiring.

## 4. Fast decision table

| Situation | Rule |
|---|---|
| New feature variant | New implementation of existing interface (OCP), not edits to shared code |
| Subtype/API impl differs from contract | Fix the impl or change the abstraction — never `if (impl is X)` in clients (LSP) |
| Client uses a slice of a fat module | Narrow role interface (ISP); check transitive baggage of new deps |
| Grouping classes into modules | Early project: co-change (CCP) wins. Mature/shared: no unused baggage (CRP) + sensible release unit (REP) |
| Stable module starts depending on volatile one | SDP violation → extract interface both depend on |
| Heavily-used + concrete + often-changed module | Zone of Pain → extract abstractions now |
| Microservices "for decoupling" | Services ≠ architecture; check data coupling + cross-cutting features first; prefer service-ready monolith |
| Tempted by deeply integrated framework magic | Use, don't marry: adapter at the edge; entities never inherit framework bases |
| Copy codebase for new market/customer | Refuse; variation behind boundaries + config. Forks diverge exponentially |
| Big-bang rewrite of a live system | Refuse; strangle incrementally behind stable interfaces |
| Build a reusable framework/library | Only against 3–4 real concurrent consumers |
| Workflow steps likely to be rewired | Externalize state machine to data; code implements steps |
| When to materialize a deferred boundary | At the friction inflection point — when cost-of-ignoring exceeds cost-of-building; watch continuously |

## 5. Python quick recipe (default shapes)

- **Entity** = dataclass with `from_dict` / `to_dict` / value equality; zero persistence or
  presentation knowledge. Serialization lives in encoder classes outside the model.
- **Use case** = plain function `use_case(repo, request)` returning a response object;
  first line guards `if not request:`; body wrapped `try/except Exception → SYSTEM_ERROR`.
- **Request builder** validates at construction, whitelists accepted keys, accumulates ALL
  errors as `{parameter, message}`; valid/invalid both defined by `__bool__`.
- **Repository**: business-named minimal API; `__init__` is NOT part of the contract;
  returns entities; mock it in use-case tests; NEVER mock the ORM — integration-test real
  repos against a real engine (markered `integration`, opt-in flag, compose-managed,
  readiness wait, non-default host ports, per-function seed+cleanup fixtures).
- **Composition root** (CLI script / app factory / endpoint) is the only place concrete
  classes meet: build repo → build request → call use case → serialize response.
- Full patterns + prod wiring (gunicorn/Nginx, env-var config, Alembic, named volumes):
  `references/python-implementation.md`.

## 6. References map (load on demand)

| File | Load when |
|---|---|
| `references/solid-and-components.md` | Designing classes/modules; SOLID questions; deciding component grouping; dependency metrics (I, A, D), cycles |
| `references/boundaries-and-layers.md` | Drawing/reviewing architecture; boundaries, Humble Object, Main, services vs components, test architecture, embedded/SDK coupling |
| `references/details-and-code-organization.md` | DB/web/framework adoption decisions; package-by-layer/feature/component choice; enforcement via visibility; rewrite/fork/schedule traps |
| `references/python-implementation.md` | Implementing any of this in Python; web adapter, error mgmt, real-DB integration testing, production deployment |

## Gotchas

- **SRP ≠ "do one thing".** That's a function-level rule. SRP = one *actor* per module.
- **"Detail" is topological, not "simple".** A DB is more complex than your core and still
  a detail: replaceable without touching the core.
- **Accidental duplication trap:** deduplicating across actors/use cases welds together
  things that must diverge; un-merging later is painful.
- **All-mocked green suite ≠ working system.** Mocks hide integration drift by design;
  after inner-API changes, adapters crash at runtime while unit tests stay green.
- **Partial boundaries erode silently.** Without compiler-enforced visibility, wrong-direction
  dependencies creep in; re-inspect them periodically.
- **Framework tutorials teach marriage.** They put annotations/base classes on your entities
  — that injects the framework into the innermost ring; nearly impossible to remove later.
- **Type coercion belongs in the repo:** query-string `"60"` vs int `60` silently matches
  nothing on Mongo; each backend's quirks are absorbed by its repository, never by callers.
- **Repo returning raw rows can stay green:** field-value assertions don't catch it — assert
  entity types explicitly.
- **Over-layering kills too:** dependencies pointing along control flow (UI→…→DB) make
  layering cosmetic; more layers than the problem needs = communication tax (real product
  deaths in Martin's appendix).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Small change requires edits across many modules | OCP/CCP violation: shared policy edited per variant, or one reason-to-change scattered | Extract interface for the variant axis; re-slice modules by co-change |
| Business logic untestable without server/DB | Details leaked inward | Push I/O behind inner-owned interfaces; test core with stubs/in-memory repo |
| `if isinstance(impl, X)` / URL-prefix special cases in clients | LSP violation by an implementation | Fix impl to honor contract or isolate deviation in a boundary adapter/config table |
| Testing one module needs building half the system | Dependency cycle | Map the graph; break with interface (DIP) or extracted shared component |
| Merge conflicts concentrate in one file | Multiple actors own it (SRP) | Split file along actor lines |
| Hundreds of tests break on a small refactor | Structural coupling: tests mirror class structure / drive rules through UI | Introduce a testing API that hides structure; stop 1:1 test-class mirroring |
| Switching DB/framework estimated as a rewrite | Vendor types/queries scattered through policy code | Quarantine behind gateway now — cost multiplies per new call site |
| Unit tests green, app crashes on start | Mocked-out adapters drifted from changed inner API | Sweep all adapters after signature changes; add one e2e smoke check |
| New backend forces edits inside use cases/entities | Boundary leak — architecture failed its main promise | Fix the leak (move translation into repo), not the backend |

## Sources

- Robert C. Martin — *Clean Architecture: A Craftsman's Guide to Software Structure and
  Design* (RU edition 2018/2021), parsed in full: 34 chapters + Appendix A case studies.
- Leonardo Giordani — *Clean Architectures in Python*, 2nd ed. (2022), parsed in full:
  8 chapters (layers → basic build → web → errors → Postgres → Mongo → production).
