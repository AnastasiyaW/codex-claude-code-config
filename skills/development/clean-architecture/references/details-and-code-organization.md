# Clean Architecture — Distilled Chunk 5 (Ch. 30–34)

Operational knowledge for a coding agent. Covers: "The Database Is a Detail" (ch. 30),
"The Web Is a Detail" (ch. 31), "Frameworks Are Details" (ch. 32), the video-sales
case study (ch. 33), and Simon Brown's "The Missing Chapter" on code organization and
enforcement (ch. 34). All paraphrased; no book text reproduced.

---

## 1. The Database Is a Detail

### Core principle
The **data model** (the shapes and relationships of the data your application cares
about) is architecturally significant. The **database engine** (the mechanism that
shuttles bytes between persistent storage and memory) is not. Treat the DBMS as a
low-level utility living in the outermost ring of the architecture — never as a
central organizing element of the system.

### Why the distinction exists
- Relational storage, indexes, caches, and query planners exist to compensate for
  slow storage hardware. They solve an I/O latency problem, not a business problem.
- Once data is loaded into memory, applications immediately reshape it into lists,
  trees, maps, stacks, and domain objects anyway. The tabular (or document) form is
  transient plumbing, not the "true" shape of the data.
- Persistence performance matters, but it is a fully encapsulable concern: it can be
  solved entirely inside low-level data-access components without touching business
  rules.

### Actionable rules
- **Do** define the data model (entities, relationships, invariants) inside the core;
  keep the storage technology behind an interface owned by the core.
- **Never** pass raw database rows, result sets, ORM-managed records, or
  table-shaped objects through use cases, business rules, or UI code. Convert to
  domain structures at the boundary.
- **Do** confine knowledge of tables/collections/SQL to low-level gateway/repository
  implementations in the outer ring.
- **Prefer** designing business logic as if storage did not exist (pure in-memory
  data structures), then attaching persistence as a plugin.
- **Do** treat persistence performance tuning (indexes, caching, query shape) as a
  local concern of the data-access layer — optimizations there must not force changes
  in the core.
- When a stakeholder demands a specific storage product for non-technical reasons
  (checkbox requirement, marketing), **accommodate it at the edge**: bolt it on
  through a narrow, safe data channel while the core keeps its own representation.
  Don't fight the requirement; contain it.

### Anti-patterns / failure modes
- **Row objects everywhere**: data-access framework types flow through the whole
  system. Symptom: changing a column name or switching storage engines forces edits
  in use cases and UI. This couples every layer to one vendor's data representation.
- **Database-centric architecture**: system design starts from the schema; business
  rules become stored procedures or thin wrappers around tables. Symptom: "the
  architecture diagram" is an ER diagram.
- **Treating engine choice as a core decision**: picking Oracle/MySQL/Postgres early
  and letting that choice shape module boundaries.

### Decision heuristics
- Ask: "If storage moved entirely to RAM tomorrow, would this code change?" Anything
  that would change is a detail — push it outward.
- Ask: "Does this module know data lives in tables/documents?" If yes and the module
  is not a gateway implementation, the dependency rule is violated.

---

## 2. The Web / UI Is a Detail

### Core principle
The delivery mechanism — web, desktop GUI, mobile, terminal — is an I/O device.
Systems should be built device-independent: business rules must not know which kind
of interface is driving them. The industry has oscillated for decades between
putting computation on the server and on the client (mainframes → terminals →
client/server → thin browser → rich browser → server-side JS...); each swing is a
short-lived fashion that must not be allowed to reshape the core.

### The abstraction that works
Even though UI interactions are rich, chatty, and platform-specific (validation,
drag-and-drop, widgets), the **boundary between UI and application** can still be
abstracted:
- Model the business logic as **use cases**, each a function performed on the
  user's behalf.
- Each use case is defined by: input data → processing → output data.
- The UI's job is to gather/accumulate the input; at some point the input is
  complete and the use case executes; the output data goes back to the UI for
  rendering.
- Package input and output as plain data structures. Then every use case treats the
  UI as an interchangeable I/O device.

### Actionable rules
- **Do** separate business rules from UI code behind a boundary — always, even when
  no second UI is planned. Marketing-driven UI rewrites arrive without warning.
- **Do** define use-case input/output as simple data structures (request/response
  models) that carry no UI or web types (no HTTP request objects, no session
  objects, no widget references inside the core).
- **Never** let the core know whether it is being driven by a browser, a desktop
  app, a test harness, or a queue consumer.
- **Prefer** iterating toward this abstraction rather than abandoning it because
  "the UI is too intertwined" — it is achievable, just not in one pass.
- **Do** expect complete look-and-feel overhauls as a normal category of change; the
  architecture's job is to make them cheap.

### Anti-patterns / failure modes
- **Fashion-driven rewrite ripple**: a UI restyle or platform swing (e.g., desktop →
  web-like → back) forces changes in business logic. Symptom: renaming screens or
  changing navigation breaks core tests.
- **Web types in the core**: controllers pass HTTP/session/framework objects into
  use cases. Symptom: business logic cannot run in a unit test without a fake web
  server.
- **Assuming the current platform swing is final**: designing as if "everything is a
  web app now, forever."

### Decision heuristics
- Ask: "Could I drive every use case from a command-line test harness with plain
  data structures?" If not, the UI boundary is leaking.
- When someone argues device independence is impractical because the interaction is
  rich: agree that the *interaction* is device-specific, but insist the
  *use-case boundary* (complete input in, result out) is still abstractable.

---

## 3. Frameworks Are Details

### Core principle
A framework is a tool built by its author to solve the author's problems. Your
problems overlap only partially. The relationship is asymmetric: adopting a
framework the way its documentation recommends means committing your codebase to it
deeply and permanently, while the framework owes you nothing — no stability, no
direction aligned with your needs, no migration path.

### The risks of deep coupling
- Frameworks routinely violate the dependency rule by design: their tutorials tell
  you to inherit from framework base classes and annotate your **entities** —
  injecting the framework into the innermost ring. Once there, it is nearly
  impossible to remove.
- Your product can outgrow the framework: what accelerated the first features later
  becomes something you fight against.
- The framework can evolve away from you: forced upgrades, removed/changed features
  you depended on.
- A better alternative can appear, and you'll be unable to switch.

### Actionable rules
- **Do** use frameworks — but keep them at arm's length, in the outer ring, as
  plugins to your business rules.
- **Never** derive business objects/entities from framework base classes. If a
  framework asks for that, wrap it: create proxy/adapter classes in an outer
  component that plugs into the core.
- **Never** put framework annotations/decorators (DI markers, ORM mappings, route
  attributes) on core business objects. Business objects should not know the
  framework exists.
- **Do** confine framework wiring to the dirtiest, lowest-level component — the
  Main/composition-root component. Main may know about the DI container; nothing in
  the core may.
- **Prefer** deferring the commitment: postpone framework adoption decisions as long
  as practical; keep the option to swap.
- **Accepted exceptions**: the language's standard library (and equivalents like
  STL) are unavoidable marriages. Even then, treat the commitment as a deliberate,
  acknowledged decision — you will live with it for the product's lifetime.

### Anti-patterns / failure modes
- **Framework marriage**: `extends FrameworkBase` on entities, framework annotations
  on domain classes. Symptom: unit-testing a business rule requires booting the
  framework; upgrading the framework produces diffs in domain code.
- **Framework-defined architecture**: project structure, module boundaries, and
  naming are dictated by the framework's scaffolding rather than by use cases and
  actors. Symptom: the repo layout screams the framework's name, not the domain.
- **Asymmetric commitment ignored**: assuming the framework will keep supporting
  your use pattern because you depend on it.

### Decision heuristics
- Before adopting: "Can I get the benefit while keeping this behind a boundary?"
  (Get the milk without buying the cow.)
- For each framework touchpoint: "If this framework disappeared, how many files
  change?" Target: only outer-ring adapters and Main.
- Distinguish *using* (calling it from an adapter) from *marrying* (letting it into
  entities/use cases). Only the first is safe by default.

---

## 4. Case Study Method: From Use Cases to Components (video-sales example)

### The process a good architect follows
1. **Identify actors** — the distinct kinds of users the system serves (e.g.,
   viewer, purchaser, content author, administrator). By the Single Responsibility
   Principle, each actor is a distinct source of change.
2. **Identify use cases** per actor. Factor out **abstract use cases** — a shared
   general policy that several concrete use cases specialize (e.g., a generic
   "browse catalog" specialized by viewer-browsing vs purchaser-browsing). Create
   the abstraction when two use cases are near-duplicates; it's optional, but
   recognizing similarity early pays off.
3. **Partition into components along two axes**:
   - **By actor** (SRP axis): changes serving one actor must not touch components
     serving another.
   - **By layer/policy level** (dependency-rule axis): views, presenters,
     interactors (use cases), controllers — separated by architectural boundaries.
   The grid of (actor × layer) gives candidate components, each potentially an
   independently deployable unit (jar/dll).
4. **Direct the dependencies**: control flow runs controller → interactor →
   presenter → view, but **source-code dependencies must all point toward
   higher-level policy** (inward), crossing boundaries in one direction only.
   "Uses" relationships follow control flow; inheritance/implements relationships
   point against it — that inversion is the Open-Closed Principle in action: changes
   in low-level detail cannot ripple into high-level policy.
5. **Keep deployment grouping flexible**: components can be merged into fewer
   deployment units (one per layer, or views+presenters vs everything else, etc.).
   Because the code is partitioned finely and correctly, you can regroup deployment
   units later as the system's evolution reveals what actually changes together.

### Actionable rules
- **Do** derive component boundaries from actors + policy levels, not from
  technology ("the web stuff", "the JSON stuff").
- **Do** keep both separations even if you deploy as a monolith — fine-grained
  logical partitioning is what preserves the option to split deployment later.
- **Prefer** leaving deployment granularity open (merge/split jars later) over
  fixing it early.
- **Do** verify on the dependency diagram that every boundary-crossing arrow points
  toward the higher-level policy; any arrow pointing outward/downward toward detail
  is a defect.

### Decision heuristics
- Two pieces of code belong in different components if they **change for different
  reasons** (different actors) or **at different rates** (different policy levels).
- Introduce an abstract use case when two concrete use cases share most of their
  policy; skip it when the similarity is superficial.

---

## 5. Code Organization Styles and Their Trade-offs (The Missing Chapter)

Four ways to organize the same feature (e.g., "view orders": controller → service
interface → service impl → repository interface → JDBC repository impl):

### 5.1 Package by layer
Horizontal slicing: one package for web, one for services/business logic, one for
persistence. Dependencies point "down" layer by layer.
- **Pros**: trivially simple; fine for getting started on small projects.
- **Cons**:
  - Says nothing about the domain — two unrelated products look identical
    (web/services/repositories). The structure doesn't "scream" what the system does.
  - Scales poorly: three big buckets get overcrowded; you'll need finer structure.
  - Easiest to corrupt (see relaxed-layering failure below).

### 5.2 Package by feature
Vertical slicing: all types for one domain concept/aggregate (controller, service,
repository for "orders") live in one package named after the domain concept.
- **Pros**: top-level structure reflects the domain; finding all code for a
  use-case change is easy — it's colocated.
- **Cons**: still exposes the same internal types; author considers it (like
  layering) suboptimal — a stepping stone, not the destination.

### 5.3 Ports and adapters (hexagonal / boundary-control-entity)
Two regions: an **inside** (domain: use-case interfaces, domain services, domain
types named in ubiquitous language — e.g., `Orders`, not `OrdersRepository`) and an
**outside** (infrastructure: web controllers, DB implementations, third-party
integrations). Iron rule: **outside depends on inside, never the reverse**.
- **Pros**: domain code is technology-free; dependency direction is enforced by
  structure.
- **Cons / trap**: see "périphérique anti-pattern" below.
- Naming note: inside-region types take clean domain names from the ubiquitous
  language; "repository/DAO/impl" suffixes belong to the outside.

### 5.4 Package by component (Brown's recommendation for monoliths)
Bundle **business logic + persistence for one area behind a single component
interface** in one package (e.g., `OrdersComponent` fronting service logic and
repository internals). The UI/controllers stay separate and may only talk to the
component's public interface.
- Component here = a grouping of related functionality behind a clean interface,
  living inside one runtime (from the C4 model: container → components → classes).
  Whether each component is a separate build artifact is secondary.
- **Pros**:
  - All code for an area is in one place.
  - Internal separation (service vs repository) becomes an implementation detail
    invisible to consumers.
  - The **compiler enforces** the rule "controllers must not reach the data layer"
    — the repository types simply aren't visible outside the package.
  - It is a natural stepping stone toward extracting microservices later: a
    well-formed component maps to a service.

### Decision heuristics for choosing a style
- Small/short-lived project: package-by-layer is acceptable to start; plan to
  refactor as complexity grows.
- Monolith intended to live and grow: prefer package-by-component (or ports &
  adapters with disciplined access modifiers) so that architectural rules are
  compiler-enforced.
- Considering microservices someday: build the monolith as well-encapsulated
  components first; extraction becomes mechanical.

---

## 6. Encapsulation Is the Enforcement Mechanism (the actual "missing advice")

### Core principle
An architectural style that exists only in diagrams and conventions is fiction. If
every type is `public`, packages/namespaces degrade into mere folders, and **all
four organization styles become syntactically identical** — indistinguishable
layered mush. What makes a style real is using the language's visibility mechanisms
so that illegal dependencies **fail to compile**.

### Actionable rules
- **Never** mark types `public` (or `export`) by reflex. Every access modifier is an
  architectural decision.
- **Do** minimize the public surface per package/module: expose only the types with
  legitimate external consumers; make implementations package-private/internal.
  - Package by layer: interfaces (`OrdersService`, `OrdersRepository`) must be
    public; implementation classes should not be.
  - Package by feature: only the entry point (controller) needs visibility; all else
    can be package-scoped.
  - Ports & adapters: inside-region interfaces with external consumers are public;
    implementations package-scoped, wired by DI at runtime.
  - Package by component: only the component interface is public; everything behind
    it (including the repository) is invisible — fewest public types of all four.
- **Prefer compiler-enforced boundaries over both (a) trust/discipline/code review
  and (b) post-compile static-analysis rules.** Discipline decays under deadline
  pressure; analysis tools have slow feedback loops and get disabled. The compiler
  is immediate and non-negotiable.
- **Do** use module systems (e.g., Java 9 modules, OSGi; .NET `internal` +
  per-component assemblies) when available — they distinguish "public within the
  module" from "published to the outside," an even stronger boundary.
- **Do** consider separate source trees / build modules as another decoupling mode:
  e.g., domain code tree with no outward dependencies; web tree and persistence tree
  each depending on the domain tree at compile time. Balance against build
  complexity and maintenance overhead — two trees (domain + infrastructure) is a
  pragmatic compromise, but see the trap below.
- **Never** defeat encapsulation via reflection or similar backdoors to reach hidden
  types.

### Anti-patterns / failure modes
- **Relaxed/leaky layering**: a developer in a hurry wires the web controller
  directly to the repository, skipping the business layer (and whatever
  authorization/validation lives there). The dependency graph is still acyclic and
  "looks fine," but the architecture is violated. Symptom: use cases that bypass
  business rules; discovered only when someone finally visualizes the codebase.
  Root cause: nothing *prevented* it.
- **Public-by-default muscle memory**: every class public because tutorials and
  scaffolds do it. Symptom: IDE autocompletion offers internal types from anywhere;
  any class can use any other class's implementation.
- **"We enforce it with code review and trust"**: works until schedule pressure;
  then shortcuts accumulate into a big ball of mud.
- **Grep-rule enforcement as primary defense**: wildcard rules like "types in
  `**/web` must not use `**/data`" checked after compilation — error-prone, slow
  feedback, easy to switch off. Acceptable as a supplement, not as the foundation.
- **Périphérique (ring-road) anti-pattern for ports & adapters**: with all
  infrastructure code in one tree/region, one piece of infrastructure (web
  controller) can call another (DB access) directly, *around* the domain — like a
  ring road bypassing the city center. Symptom: inside/outside split looks clean at
  the tree level, but outside-to-outside calls skip domain policy. Guard: access
  modifiers still matter within the infrastructure region.

### Decision heuristics
- For every type ask: "Who outside this package legitimately needs this?" No one →
  restrict visibility.
- When defining an architectural rule ("X must never call Y"), immediately ask:
  "What mechanically prevents it?" Preference order: compiler visibility > module
  system / separate compilation units > build-time static analysis > code review >
  documentation.
- In a monolith with a single source tree, lean hardest on the compiler; in a
  multi-repo/multi-service setup, the network boundary does some of this work, but
  the same leak logic applies within each service.

---

## 7. Cross-Chapter Synthesis: Rules of Thumb for an Agent

- **Detail test**: database engine, web/UI platform, frameworks, delivery
  technology = details. Data model, use cases, business rules, entities = core.
  Dependencies point only from detail to core.
- **Deferral test**: a good architecture maximizes decisions *not yet made*. Keep
  storage engine, UI platform, framework, and deployment grouping swappable for as
  long as feasible.
- **Boundary payload rule**: what crosses a boundary is a simple data structure in
  the core's vocabulary — never a framework/DB/HTTP type.
- **Two axes of partitioning**: split code by actor (who requests changes) and by
  policy level (how abstract/stable it is). Both, not either.
- **Enforcement ladder**: any rule worth stating is worth mechanizing. Encode
  architecture in compiler-checked visibility first; treat conventions and reviews
  as backup layers only.
- **Non-technical requirements are real**: irrational, market-driven demands (a
  specific DB, a specific look) will come. The architecture's job is to make
  satisfying them a bolt-on at the edge, not a rewrite of the core.
- **Screaming structure**: the top-level organization of the repo should reveal the
  domain (orders, catalog, licensing), not the technology stack (web, services,
  repositories) and not the framework's scaffold.

# Clean Architecture — Chunk 6: Architecture Archaeology (Appendix A)

> Scope of this chunk: the book's appendix — a retrospective of ~15 real systems (1970s–1990s)
> used as case-study evidence for the book's core principles. Narrative details are stripped;
> what remains below is each project's transferable architectural lesson, restated as
> operational guidance for a coding agent. This chunk also contains publisher front-matter
> (no technical content).

---

## 1. Boundaries: the central concept this chunk demonstrates

### 1.1 Definition
An architectural boundary is a line across which two parts of a system know as little as
possible about each other. A boundary is real only if dependency direction is controlled at
that line — either dependencies cross it in the direction of control flow (lower-level detail
depends on higher-level policy), or the dependency is deliberately inverted through a
polymorphic interface so the high-level side never learns the low-level side's details.

### 1.2 Two boundary shapes (from the earliest case study)
Even a bare-metal assembly system with no OS exhibited both fundamental boundary shapes:

- **Forward boundary (dependency follows control flow).** Application code calls an I/O
  dispatcher through an abstraction; the application never learns what device type, speed, or
  buffering sits behind the call. Rule embodied: *callers depend on an abstraction of the
  service, not on the device.*
- **Inverted boundary (dependency opposes control flow).** The dispatcher launches
  applications but has no compile-time knowledge of them — every application is invoked
  through one uniform entry point (a primitive polymorphic interface). Rule embodied: *the
  orchestrator knows only a start-point contract, never the internals of what it starts.*

**Agent rule:** when you design any scheduler/plugin-host/callback system, give the host a
single uniform invocation contract and keep all knowledge of concrete implementations out of
the host. When you design any I/O or device access, hide the device behind an interface the
business code calls; never let device parameters leak upward.

### 1.3 Boundaries decided by hardware/economics later
One case: line-selection hardware and line-measurement hardware were fused in one unit
because nobody drew the boundary between "control" and "measurement" concerns. Years later
the industry's shift (digitalization) required exactly that split, forcing an expensive
emergency redesign. The author's verdict: recognizing that obvious domain boundary years
earlier would have saved a fortune.

**Agent rule:** identify boundaries along *conceptual responsibilities of the domain*
(control vs measurement, selection vs analysis, UI vs rules), not along the current
packaging of hardware or deployment. A boundary that costs little to honor now can be
ruinously expensive to introduce later.

---

## 2. Hard boundaries with minimal protocols pay off immediately

Case: a monolith doing both line testing and report generation on the same underpowered
machine was split into two machines — testers (many, remote) and an analysis/reporting
computer (one, central). The interface between them became a tiny domain-specific command
protocol (short packets like "dial this / measure that").

Observed payoffs:
- Each side could shrink to cheaper hardware fitted to its own job.
- Response time for users improved dramatically because presentation moved next to the user.
- The narrow DSL-style protocol made the boundary "clean and tough" — neither side could
  grow tendrils into the other.

**Agent rules:**
- Prefer a **narrow, domain-level message protocol** at a boundary over shared memory
  structures, shared code, or wide APIs. The smaller and more domain-shaped the vocabulary
  crossing the boundary, the harder it is to accidentally couple the sides.
- Separate "collect/act" components from "analyze/present" components; they scale, deploy,
  and change on different rhythms.

---

## 3. Independent deployability, polymorphism, and plugin architecture (the vectorization story)

Case: a 30 KB firmware image spanned 30 ROM chips as one absolute binary. Any one-line
change shifted every address, so **every chip** had to be re-burned and swapped in every
field unit — a logistics disaster.

Fix: split the binary into ~1 KB independently compiled units, each with a fixed-size
**jump-vector table** at a known address; all cross-unit calls went indirectly through a
RAM-resident vector array populated at boot.

Results and the principles they demonstrate:
- A change now touched only the one or two units it belonged to → **independent
  deployability** is the practical test of decoupling.
- Indirect calls through vectors = **polymorphic dispatch**; the team had effectively
  reinvented objects and late binding in assembly.
- New features could ship as an extra chip that self-registered (menus appeared
  automatically) = **plugin architecture**.
- Unplanned bonus: individual routines could be hot-patched remotely by redirecting one
  vector to a fresh routine loaded into spare RAM — decoupling created a capability nobody
  designed for.

**Agent rules:**
- Structure code so the unit of change equals the unit of deployment. If fixing one function
  forces rebuilding/redeploying everything, the architecture has no internal boundaries.
- Route cross-module calls through interfaces/dispatch tables, not direct concrete
  references — this is what makes modules replaceable one at a time.
- Expect decoupling to yield second-order benefits (hot-swap, remote patching, feature
  toggles) that direct coupling forecloses.

---

## 4. Unreadable code becomes frozen code (the "genius who quit" story)

Case: the economically most valuable routine in a product was written by one brilliant,
uncommunicative programmer who then left. Nobody could understand the code; every attempted
change broke it; management ultimately declared the code officially immutable.

**Symptoms of this failure mode:**
- One module everyone is afraid to touch.
- Every fix attempt introduces a regression.
- Institutional decision to "never change it" — the code is now a liability with a fence
  around it.

**Agent rules:**
- Treat readability as a survival property, not a courtesy: code whose logic can't be
  followed by a second person is one departure away from being frozen.
- Never accept "it works, don't touch it" as an end state for business-critical logic;
  that state means the organization has lost the ability to evolve its own core asset.
- When writing clever/dense logic, spend the extra effort to structure and name it so the
  next maintainer can modify it safely.

---

## 5. Business rules entangled with devices and UI (the scattered-modem story)

Case: a 60 K-line assembly monolith had modem control code — bit-level register writes —
smeared through business rules and UI code in hundreds of places. Message formatting and
terminal control were equally scattered. When a second, differently controlled modem model
arrived, the team could not introduce a device abstraction; the "solution" was a low-level
translation layer that sniffed bit patterns intended for the old device and rewrote them
(addresses, timings, bit layouts) for the new one — acknowledged as the worst option, chosen
because the cost of touching hundreds of scattered sites was even higher.

**Anti-pattern:** *device/vendor details woven through policy code.*
Symptoms:
- grep for a hardware register / SDK call / SQL keyword returns hits across all layers;
- supporting a second variant of anything (device, DB, protocol, provider) requires flags
  and special cases at every site;
- teams start writing adapters that translate at the lowest possible level because no seam
  exists at the right level.

**Agent rules:**
- Wrap every external device, driver, vendor SDK, wire protocol, and I/O mechanism behind
  one interface owned by the application, from the very first use.
- Business rules must be describable and testable with no knowledge of which concrete
  device/DB/transport is present.
- If you find yourself translating one low-level command stream into another, recognize it
  as a symptom that the abstraction is at the wrong level — the right fix is an interface at
  the domain level of "what" is requested, not "which bits."
- The economic argument: the cost of an interface is paid once; the cost of scattering is
  paid at every future change, multiplied by the number of call sites.

---

## 6. The Grand Rewrite trap and the fork trap

Two intertwined failure modes from the same product line:

### 6.1 Grand rewrite that never catches up
A hand-picked team set out to rewrite an actively developed legacy system from scratch on a
new stack. First attempt burned years and died; the second dragged on for many more years
and possibly never shipped. Root cause: the old system kept evolving under a large active
team, and the rewrite team was permanently chasing a moving target.

**Agent rules:**
- Never propose a big-bang rewrite of a system that continues to receive features; the
  rewrite must chase everything the legacy team ships, plus reproduce years of embedded
  fixes.
- Prefer incremental strangulation: introduce boundaries in place, replace one component at
  a time behind stable interfaces, keep one codebase authoritative.

### 6.2 Codebase fork instead of parameterization
To enter a new market with different rules, a copy of the codebase was taken and modified
independently. Bugs then had to be found and fixed twice; modules diverged so far that fixes
were no longer portable; multiple later attempts to reunify the two trees into one
configurable system all failed.

**Agent rules:**
- Do not fork a codebase to handle regional/customer/product variation. Isolate the varying
  policies behind boundaries and drive variation with configuration or plugins from day one.
- Divergence is exponential: reunification of long-lived forks routinely fails outright, so
  treat the moment of "let's just copy it and patch" as the last cheap moment to say no.
- Note the compounding: the fork also multiplied the moving target for the rewrite team —
  architecture failures interact and amplify each other.

---

## 7. The schedule trap (deferred architecture becomes an emergency)

Case: a needed architectural evolution was repeatedly postponed because urgent work kept
arriving and the external deadline looked comfortably far away. The deadline then jumped
forward abruptly (a customer moved faster than planned), leaving one month to do a
person-year of work.

The escape in that instance was a lesson in itself: the "full" architecture wasn't actually
needed for the first real customer — a drastically simplified composition of existing
components (a small router box plus stock units, exploiting a regularity in the data)
covered the concrete case and shipped in about a week.

**Agent rules / heuristics:**
- Architectural work postponed "because there's time" silently converts into an emergency;
  external schedules you don't control can collapse without warning.
- When cornered, scope to the *actual concrete case in front of you*, not the general
  architecture: ask what subset of the vision this one customer/deployment truly requires.
- Look for accidental regularities in the real data (e.g., an identifier already encoding
  the routing decision) that let a simple component stand in for a general mechanism.

---

## 8. Multiple architectures can be equally valid (pipeline vs task-per-entity)

Case: two halves of one product were built by two engineers with opposite architectures —
one as a dataflow pipeline (small single-purpose tasks passing work through queues, like an
assembly line, including fan-out/fan-in), the other as one large identical task per terminal
doing everything for its terminal (like a craftsman building the whole product). Both
worked; both were maintainable; neither proved superior.

**Agent rules / heuristics:**
- Architecture style (pipes-and-filters vs actor-per-entity vs layered ...) is a means, not
  a virtue. Judge by fitness: decoupling achieved, deployability, comprehensibility for the
  team — not by conformity to a favored pattern.
- Do not "correct" a working style choice to match your preferred paradigm; radically
  different decompositions of the same problem can be equally effective.
- Pipeline style suits flows where stages are genuinely independent transformations;
  task-per-entity suits systems where per-entity state dominates and stages interleave.

---

## 9. The database is a detail — the vendor-lock story

Case: a team embedded a then-fashionable database's SQL — including its non-standard
dialect and proprietary API calls — directly into application code "everywhere, because we
could." The product succeeded; then the DB vendor discontinued the product. A three-month
migration attempt to another DB failed completely — the coupling was irreversible at
reasonable cost — and the company was forced into an ever-more-expensive third-party
maintenance contract for a dead product.

A second instance in this chunk: an object-oriented database chosen for a flagship tool
because it felt like magic ("objects just appear in memory") turned out to be a large, slow,
intrusive, expensive third-party framework that impeded work at every level and was one of
the two decisive mistakes of that product.

**Agent rules:**
- Treat the database (and any storage/ORM/third-party framework) as a replaceable detail:
  confine all vendor-specific statements and API calls to one gateway/repository layer.
- Never scatter raw query strings or vendor calls through business code — the trigger for
  this rule is the *first* such statement outside the data layer.
- Evaluate any framework that wants to be woven through your code (persistence magic,
  embedded query dialects) as a marriage proposal you probably shouldn't accept: intrusive
  frameworks are the hardest dependencies to leave.
- Vendor discontinuation is a normal event, not a black swan; architecture should make it a
  line item, not a company-threatening crisis.

**Symptoms of the anti-pattern:**
- SQL strings / vendor API calls visible in UI or business-rule files;
- a "migrate to another DB" spike fails or balloons;
- rising maintenance payments for a product that no longer evolves.

---

## 10. Services, externalized state machines, and open–closed behavior

Two related cases (an automated call-handling product and a dispatch product):

- Each stage of handling a call/ticket ran as its own independently started process; a
  finishing stage decided, recorded context, and launched the next. In modern terms:
  service-oriented, later effectively micro-service-like decomposition.
- In the second system, all state transitions of the workflow were described in a **text
  file read at runtime**, not hard-coded. New processing steps could be added and the flow
  rewired by editing that data file — even while the system ran (hot deployment). The author
  explicitly frames this as the open–closed principle: behavior extended without modifying
  code.
- Inter-service messages needed a structure-preserving, pointer-free representation (their
  shared memory couldn't carry pointers), so they invented a labeled hierarchical
  name–value tree serialized to strings — functionally the same idea as XML/JSON, in 1985.

**Agent rules:**
- Externalize workflow/state-machine topology into data when the sequence of steps is a
  likely axis of change; code implements steps, data wires them.
- Design inter-service payloads as self-describing hierarchical data (names + values, no
  memory references) so services stay independently deployable and restartable.
- "Nothing is new under the sun": current buzzword architectures (SOA, microservices,
  message buses, JSON) are recurring shapes of the same decoupling forces — evaluate them
  as boundary mechanisms, not as fashion.
- The author's honesty about limits applies too: services with clear ownership of a domain
  slice and mostly correctly directed dependencies already capture most of the value even
  without a full plugin structure.

---

## 11. "No time for architecture" (the startup-crunch failure)

Case: a well-funded startup of experienced, motivated engineers consciously skipped design
under schedule pressure — enormous enthusiasm, huge amounts of hastily written code, one
infamous 3000-line do-everything function. Three years later the company was effectively
dead; the author counts the dirty code among the causes and the period among his worst.

**Agent rules:**
- Velocity bought by skipping structure is a payday loan; in this account the balance came
  due within the lifetime of the same product, not in some distant maintenance era.
- Team quality does not immunize against mess: experienced, driven engineers wrote the
  worst code of the author's career under "code now, architecture later."
- Concretely ban the mega-function: a single routine accreting thousands of lines and many
  responsibilities is the unit-level signature of this failure mode. Split by
  responsibility as it grows, not after.

---

## 12. Over-architecture: layers must fit the problem size

Case: a large diagramming tool was built with a genuinely layered architecture — but the
dependencies between layers pointed **along control flow** (UI → presentation → data-ops →
database) rather than **toward high-level policy**, and there were far more layers than the
problem needed. Each extra layer added communication overhead and taxed team productivity.
The heavyweight product, after years of effort and two weak releases, was displaced by a
small, simple competing tool from a tiny team.

**Two distinct lessons:**

1. **Direction of dependencies matters more than the existence of layers.** Layering where
   everything ultimately depends on the database is traditional but backwards; dependencies
   should point toward the business policies, with UI and persistence as replaceable
   details. Wrongly directed layering contributed directly to the product's death.
2. **Architecture must be sized to the problem.** Enterprise-grade layering wrapped around
   what should be a small desktop tool is a recipe for failure. Great architectures can
   produce great failures when their weight exceeds the problem's needs.

**Agent rules:**
- Before adding a layer, name the concrete change-axis it isolates; a layer that isolates
  nothing anyone will change is pure overhead (communication cost, indirection cost,
  productivity cost).
- Check dependency direction explicitly: does the domain core compile/test without the UI
  and without the DB? If the "rules" layer imports the persistence layer, the layering is
  cosmetic.
- Match ambition to scope: a small tool with a simple architecture beats a cathedral that
  ships late and slow.

---

## 13. Reusable frameworks must be grown against multiple real consumers

Case: 36 planned applications shared obvious commonality, so two engineers spent a year
building a large reusable framework alongside the *first* application. When application #2
began, the framework "almost" fit but grated everywhere — it had unconsciously specialized
to its single consumer. They restarted: built a second framework **concurrently with four
real applications**, refactoring shared code until it fit all four without modification.
That framework worked; subsequent applications then took only weeks each, as originally
promised — but the false start cost a year and client goodwill.

Structural detail worth keeping: in the successful version, applications were **plugins to
the framework** — high-level shared policy lived in the framework, and each app was thin
glue. In the inverse sub-case (the evaluation apps), the high-level policy lived in the
application and the framework plugged into *it*; dependency direction followed the policy,
not habit. Even statically linked, the dependency structure was a plugin architecture in
all but name.

**Agent rules:**
- Never build a "reusable" library/framework from a single use case. One consumer produces
  a framework shaped exactly like that consumer.
- Rule of thumb: extract shared infrastructure only while at least 3–4 genuinely different
  consumers are being built against it simultaneously, and require that shared code fit all
  of them *without per-consumer modification*.
- Decide per subsystem where the high-level policy lives, and point dependencies at it;
  "framework calls app" and "app calls framework" are both valid, chosen by where policy is.
- Budget honestly: a framework-first plan that promises "slow first app, fast rest" often
  needs one full restart; the fast-follow-on payoff is real but only after the framework has
  survived multiple consumers.

---

## 14. Minor but reusable observations from this chunk

- **Cooperative scheduling primitive:** a "yield to pending lower-priority work" call
  (compared by the author to `Thread.yield()`) is the essential primitive of a
  non-preemptive scheduler: tasks block on an event-check function; a polling loop resumes
  whichever task's predicate turns true. Simple, adequate for I/O-bound systems; the same
  design also brought classic costs — manual context copying, locks/semaphores for shared
  state, and persistent re-entrancy and race-condition pain. Prefer preemptive/managed
  concurrency when available; if building cooperative scheduling, expect races around
  every shared variable.
- **DSLs as boundary material:** twice in this chunk a small domain-specific language forms
  the boundary (customer-facing job-control language over a machine; command packets
  between machines). A DSL both simplifies the client's world and hardens the boundary —
  but note the first DSL leaked lower-level details upward and thus was a *soft* boundary;
  a DSL is only as clean as the isolation layer that interprets it.
- **Duplicate outputs for unreliable channels:** with a 1-in-10 failure rate per long
  operation, the team wrote every build artifact to two tapes. Generalization: when a
  pipeline step is slow and its medium unreliable, produce redundant artifacts rather than
  re-running the slow step.
- **Product economics dominate architecture:** two technically sound systems in this chunk
  died for market reasons (wrong sales channel, abandoned patent). Architecture quality is
  necessary, not sufficient; conversely (the frozen-code and vendor-lock stories) bad code
  and bad dependencies can kill even a commercially successful product line.

---

## 15. Consolidated decision heuristics from this chunk

| Situation | Heuristic |
|---|---|
| Designing any host that launches/loads work units | Uniform entry contract; host knows nothing about concrete units (inverted dependency) |
| First call to a device / vendor SDK / DB | Introduce the application-owned interface *now*; scattering cost multiplies per call site |
| Pressure to copy a codebase for a new market/customer | Refuse; extract variation behind boundaries + configuration instead |
| Proposal for a from-scratch rewrite of a live system | Refuse big-bang; strangle incrementally behind stable interfaces |
| "We'll do the architecture work later, deadline is far" | External deadlines collapse; do boundary work while it's cheap, or consciously scope a minimal concrete solution |
| Choosing between two workable architecture styles | Either may be fine; optimize for decoupling and team comprehension, not paradigm purity |
| Tempted by a magic, deeply integrated framework | The more it wants to interpenetrate your code, the harder the divorce; keep it at arm's length behind a boundary |
| Building shared infrastructure | Only with 3–4 concurrent real consumers; shared code must fit all without modification |
| Sizing the architecture | Layers/indirection proportional to the problem; small tool → small architecture |
| A change requires redeploying everything | Missing internal boundaries; move toward independently compilable/deployable units with indirect dispatch |
| Workflow steps likely to be reordered/extended | Externalize the state machine to data; code implements steps, data wires them (open–closed) |
| Critical code only one person understands | Emergency: refactor for readability before that person leaves, or the code freezes |

