# Clean Architecture — Distilled Chunk 3 (Chapters 15–21)

Operational knowledge extracted for coding agents. Covers: definition and purpose of
architecture (ch. 15), independence (ch. 16), drawing boundaries (ch. 17), boundary
anatomy (ch. 18), policy and level (ch. 19), business rules (ch. 20), screaming
architecture (ch. 21). Everything below is paraphrased and reorganized for direct use
when designing or reviewing code.

---

## 1. What Architecture Is and What It Is For

### Core definitions

- **Architecture** = the shape given to a system: how it is partitioned into
  components, how those components are arranged, and how they communicate. It is not
  a diagram artifact — it is the actual dependency structure of the code.
- **The purpose of architecture is NOT primarily "making the system work."** Plenty
  of badly architected systems function correctly. Architecture's real job is to ease
  development, deployment, operation, and — above all — maintenance over the system's
  whole lifetime, minimizing lifetime cost and maximizing developer productivity.
- **The prime directive: keep as many options open as long as possible.** A good
  architecture maximizes the number of decisions NOT yet made.
- **Policy vs. detail split.** Every system decomposes into:
  - **Policy** — the business rules and procedures; the actual value of the system.
  - **Details** — everything that lets people/machines talk to the policy without
    changing what it does: I/O devices, databases, web servers, frameworks,
    communication protocols, dependency-injection mechanisms.
  The architect's job is to shape the system so policy is the central element and
  details are irrelevant to it — which is exactly what lets detail decisions be
  deferred.
- An architect who codes: architecture work degrades when the person shaping the
  system stops feeling the pain their structural decisions inflict on implementers.
  Stay in contact with the code you constrain.

### Lifecycle concerns architecture must serve

| Concern | What good architecture does |
|---|---|
| Development | Team structure shouldn't fight the component structure; multiple teams need well-defined components with stable interfaces to work in parallel. |
| Deployment | Aim for "single-action" deployment. Don't require dozens of scripts, hand-made directories, or fragile ordering. Consider deployment cost EARLY — a design that's pleasant to develop can be hell to deploy (e.g. too many microservices with brittle inter-service wiring). |
| Operation | Hardware is cheaper than people; most performance problems can be bought off with more hardware, so operation weighs less in the cost equation than development/deployment/maintenance. Still, a good structure makes the system's runtime behavior legible to developers. |
| Maintenance | The most expensive phase. Cost = "spelunking" (finding where to make a change) + risk (probability of breaking something). Stable-interfaced, well-separated components cut both. |

### Actionable rules

- **Do** design so that use cases, features, and behaviors are first-class, visible
  elements at the top of the source tree.
- **Do** defer decisions about database type, web server, REST vs. other delivery,
  DI framework — high-level policy must not know about any of them.
- **Do** treat externally imposed decisions ("the company already committed to
  database X") as if they hadn't been made: structure the system so the commitment
  could still be changed late and cheaply.
- **Never** let the schedule pressure of team organization dictate the final
  component structure (one-component-per-team is a Conway's-law default, not a
  design).
- **Prefer** more experiments over earlier commitment: while an option is open you
  can plug in candidate databases/frameworks and measure, instead of guessing.
- The longer a decision is deferred, the more information exists when it must
  finally be made — deferral is an information-maximizing strategy, not
  procrastination.

### Anti-patterns

- **Device/vendor coupling**: business logic that emits printer commands, knows
  disk geometry, speaks a specific wire protocol, or embeds a vendor SDK's types.
  Symptom: replacing a peripheral/storage/transport requires rewriting business
  code and migrating hard-coded addresses scattered everywhere.
- **Physical addressing analog (modern form)**: business rules that know row IDs,
  file paths, partition layouts, shard topology, or storage-engine specifics.
  Fix: interpose a tiny translation layer (logical → physical) so policy sees only
  logical addresses/abstract records.
- **"It works, so the architecture is fine"**: correctness today says nothing about
  the cost of the next change. Architecture problems show up as spiraling
  development/deployment/maintenance cost, not as failing behavior.

---

## 2. Independence — What a Good Structure Must Allow

A good architecture simultaneously supports: the system's use cases, its operational
needs (throughput/latency), independent development by multiple teams, and
independent deployment of parts.

### Decoupling along two axes

1. **Horizontal layers** — group by reason/rate of change (SRP + Common Closure at
   architecture scale):
   - UI (changes for cosmetic/interaction reasons)
   - Application-specific business rules (e.g. input validation workflows)
   - Application-independent domain rules (e.g. interest computation)
   - Database/persistence (schema, query language — pure technical detail)
   Each layer changes at a different speed for different reasons → separate them so
   they can change independently.
2. **Vertical use-case slices** — each use case cuts a thin slice through all
   layers (its bit of UI, its application rules, its domain rules, its persistence).
   Different use cases change at different rates for different reasons (adding
   orders ≠ deleting orders) → keep the slices separate too.

**Payoff:** new use cases can be added without touching existing ones, when both the
layer separation and the per-use-case grouping are respected.

### Decoupling modes (the "how physically separate" dial)

Three levels, in increasing isolation and cost:

1. **Source level** — separate modules, disciplined dependencies, one executable,
   in-process function calls ("monolith"). Cheapest crossings.
2. **Deployment level** — independently deployable units (DLL/jar/gem/.so); still
   usually one process/address space; changing one unit doesn't force rebuilding
   and redeploying others.
3. **Service level** — communication only via network messages; each unit fully
   independent of others' source and binaries (services/microservices). Most
   isolated, most expensive.

### Decision heuristics for the mode

- **You cannot know the right mode up front, and it changes over the project's
  life.** Design so the mode itself is an open option.
- **Default recommendation:** push separation to the point where components COULD
  become services, but keep them in one address space as long as possible
  ("service-ready monolith"). Promote selected deployment units to services only
  when development/deployment/operational pressure actually appears — and be able
  to demote back when pressure subsides.
- **Never** start with services just because it's fashionable: service-first is
  expensive (dev effort, memory, cycles per boundary crossing) and tends to force
  premature, too-coarse decomposition.
- Operational scaling argument: if use cases and layers are properly decoupled,
  high-throughput parts can later run on their own servers — but only if components
  don't secretly assume a shared address space. Avoid baking that assumption into
  component interaction styles.
- Conway's law is a force to design WITH: for multi-team orgs, provide independently
  developable components that can be allocated to teams — but choose the component
  boundaries on change-axis grounds, then map teams onto them, not vice versa.

### The duplication trap (critical heuristic)

- **True duplication**: every change to one copy must be replicated in the others.
  Eliminate it.
- **Accidental/false duplication**: two pieces of code (or screens, or schemas)
  merely LOOK alike now but will evolve at different rates for different reasons.
  Unifying them welds together things that must diverge, and un-merging later is
  painful.
- **Rules:**
  - Before deduplicating across use cases or layers, ask: "will a change to one
    always imply the same change to the other?" If no — leave the apparent
    duplication alone.
  - Do NOT pass a database record straight to the UI just because the shapes match
    today. Create the separate view/presentation model; the similarity is almost
    always accidental and the small copying cost buys proper layer separation.
  - Resist merging use cases that happen to share similar screens, algorithms, or
    queries.

---

## 3. Boundaries — Where to Draw the Lines

### Principles

- Architecture is the art of drawing **boundary lines** between software elements
  such that elements on one side don't know what's on the other.
- **Draw boundaries between things that matter and things that don't** (to each
  other): GUI doesn't matter to business rules; database doesn't matter to the GUI;
  database doesn't matter to business rules → boundary between each pair.
- **Boundaries follow the axis of change**: components on opposite sides change at
  different rates and for different reasons. This is the Single Responsibility
  Principle applied at architectural scale.
- The enemy is **coupling to premature decisions** — decisions that have nothing to
  do with the use cases: framework choice, database, web server, utility libraries,
  DI containers. A good architecture makes these late, low-impact, and reversible.
- **The database is not the embodiment of the business rules.** It is a tool the
  rules use indirectly through a small set of load/save operations. Business rules
  need no knowledge of schema, query language, or engine. Hide the whole thing
  behind an interface owned by the business-rules side.
- **I/O is a detail.** Users equate the system with its GUI, but the model/rules
  behind it can run — and be tested — without any interface at all. Don't define
  the system in terms of its input/output surface.

### The plugin pattern (the unifying structure)

- Make everything that is not core business rules a **plugin** to the business
  rules: UI plugs in, persistence plugs in, delivery mechanism plugs in.
- Dependency arrows must point ONE way across every boundary: **from detail toward
  policy** (from plugin toward core). The interface the plugin implements lives in
  the CORE component, not in the plugin (Dependency Inversion in action).
- Asymmetric protection: whoever is depended-upon is immune to the dependent's
  changes (the IDE/plugin relationship). Reproduce that asymmetry deliberately —
  business rules must be structurally immune to UI/DB churn.
- Payoff pattern from practice: with persistence behind an in-core interface you
  can develop for a long time against a stub, then in-memory implementation, then
  flat files — and adopt (or permanently skip) a real DBMS later; a new backend is
  just one more derived implementation. Meanwhile tests run fast because no
  database sits in the loop.

### Actionable rules

- **Do** define data-access as an interface owned by the business-rules component;
  implement it in a separate persistence component that depends inward.
- **Do** start new work with stub/in-memory implementations of boundary interfaces;
  postpone real infrastructure until features force it.
- **Do** check the direction of every `import`/`using`/`require` crossing a
  boundary: all must point toward the higher-level side.
- **Never** let core code name concrete infrastructure (class names, URIs,
  connection details, registry keys of lower-level pieces).
- **Never** begin a project by choosing the framework stack and shaping the system
  around it. Choose boundaries first; frameworks plug in later.

### Anti-patterns / failure modes (with symptoms)

- **Premature distribution ("three-tier on paper")**: deciding early that objects
  will live on separate tiers/servers → every trivial change (add one field)
  fans out into per-tier class edits, message-format edits, and multiple
  serializer/deserializer pairs; the system pays marshaling, socket, timeout, and
  retry costs forever — even when it always ships on a single machine. Symptom:
  simple feature = edits in N executables + protocol changes.
- **Premature SOA / grand domain-object service layer**: a central registry of
  services fronting a giant domain model, where inserting one small record requires
  discovering a service, populating dozens of mostly-unknown fields, and chaining
  messages through buses/queues. Symptoms: tests require standing up a fleet of
  services and middleware; adding features means touching many service contracts
  and redeploying widely.
- **Common thread:** in both failures the expensive structure was bought before any
  need was demonstrated, and the cost was paid in man-hours forever after. Services
  are not wrong per se — committing to them prematurely is.

---

## 4. Boundary Anatomy — Physical Forms of a Boundary

A boundary crossing at runtime is just "a function on one side calls a function on
the other and passes data." The engineering content is managing the **source-code
dependencies** around that crossing, because a source-level dependency is what forces
recompilation and redeployment to ripple.

### Forms, cheapest to most expensive

1. **Source-level boundary (monolith)** — no physical manifestation; pure
   discipline of module dependencies inside one executable. Crossings are plain
   function calls: fast, so they can be frequent/chatty. Requires (dynamic)
   polymorphism to invert dependencies; without OO-style polymorphism, teams tend
   to skip decoupling entirely. Even invisible at deploy time, these boundaries
   still buy independent development.
2. **Deployment-level boundary** — independently deliverable binaries (jar/DLL/
   gem/.so), typically still one process and address space. Same dependency rules
   as the monolith; crossings still cheap function calls (plus one-time dynamic
   load cost).
3. **Local process boundary** — separate address spaces on the same machine,
   talking via sockets/IPC/queues/shared memory. Crossings cost syscalls,
   marshaling, context switches → **moderately expensive; limit chattiness.**
   Higher-level processes must not contain names/addresses/keys of lower-level
   processes: lower-level processes are plugins to higher-level ones.
4. **Service boundary** — strongest isolation; location-independent; all
   communication over the network. Crossings cost milliseconds-to-seconds →
   **minimize the number of interactions and design for latency and failure.**
   Source of a high-level service must contain no concrete info (e.g. URIs) about
   low-level services.

### Direction rules for crossings

- **Call DOWN the level gradient naturally**: when a low-level client calls a
  high-level service, runtime flow and source dependency both point the same,
  correct way (toward high level); the data structure definition lives on the
  callee's (high) side.
- **Call UP against the gradient via inversion**: when high-level code needs a
  low-level service, insert an interface on the high side; the low side implements
  it. Runtime control flows high→low, but every SOURCE dependency still points
  low→high; the data structure definition lives on the caller's (high) side.
- Threads are NOT architectural boundaries or deployment units — just scheduling;
  a thread may live inside one component or span several.
- Real systems mix forms: a "service" is often a facade over local processes, each
  of which is internally a component-structured monolith. Expect and design for a
  mix of cheap (chatty-OK) and expensive (must-be-coarse) crossings in one system.
- Note on generics/templates (static polymorphism): useful for dependency
  management inside a monolith, but unlike dynamic polymorphism they cannot spare
  you recompilation/redeployment, and they are unavailable across deployment
  boundaries.

---

## 5. Policy and Level — The Vertical Ordering Rule

### Definitions

- A program is a statement of **policy**: a detailed description of how inputs are
  transformed into outputs. Nontrivial systems contain many sub-policies (business
  rules, report formatting, input validation, ...).
- **Level = distance from inputs and outputs.** The farther a policy sits from I/O,
  the higher its level. I/O-managing policies are the lowest level in the system.
- Architecture work = separating policies that change for different reasons/times,
  regrouping policies that change together (SRP/CCP), and arranging the groups into
  a **directed acyclic graph** of components where every source-code dependency
  edge points toward higher level.

### Rules

- **Source dependencies must be decoupled from data flow and coupled to level.**
  Data may flow low→high→low, but `import`s must always point low→high.
- The compact-but-wrong version of a system is one function whose high-level logic
  directly calls low-level read/write functions. The right version puts the
  high-level transform behind interfaces (e.g. Reader/Writer abstractions) that the
  concrete I/O classes implement — all dependencies crossing that ring point
  inward, at the transform.
- **Change-frequency gradient:** the farther from I/O, the less often a policy
  changes and the weightier the reasons when it does; the closer to I/O, the more
  frequent and more trivial the changes. Ordering dependencies by level means
  urgent-but-trivial low-level changes cannot disturb important high-level policy.
- Equivalent formulation: **low-level components are plugins to high-level
  components** — the high-level component compiles and runs knowing nothing about
  them.
- Heuristic when placing a module: ask "which of these two changes more often, and
  which changes for the more fundamental reason?" The rarer/more-fundamental side
  is higher level; dependencies must point at it.

---

## 6. Business Rules — Entities and Use Cases

### Two kinds of business rules

1. **Critical business rules** — rules that make or save money EVEN IF executed by
   hand with no computer (e.g. "charge N% interest on a loan"). They operate on
   **critical business data** — data that would exist even without automation
   (balance, rate, payment schedule).
   - Bundle critical rules + the data they govern into an **Entity**: a module
     exposing functions that implement those rules over that data.
   - An Entity is "the business, pure": zero knowledge of database, UI, or
     frameworks; reusable across many applications. (No OO language required —
     what matters is the bundling and the isolation into its own module.)
2. **Application-specific business rules = Use Cases** — rules that make/save
   money only as part of an automated system, by defining and constraining how the
   application operates (e.g. "don't show the payment-schedule screen until contact
   info is validated and the credit score clears the threshold").
   - A use case specifies input, output, and the processing steps connecting them,
     and orchestrates when/how Entities' critical rules are invoked.
   - A use case object holds its application rules, input/output data elements,
     and references to the Entities it coordinates.

### Level relationship (direction of knowledge)

- **Entities are higher level than use cases.** Entities generalize across many
  applications (far from I/O); use cases are specific to one application (closer
  to I/O).
- Therefore: use cases know about and depend on Entities; **Entities know nothing
  about use cases.** (Dependency Inversion applied again.)

### Use-case I/O rules

- A use case must be **delivery-agnostic**: nothing in it may reveal whether the
  system is a web app, CLI, thick client, or service. Use cases describe
  application-specific interaction rules, never UI appearance.
- **Request/response models**: use case classes accept plain input data structures
  and return plain output data structures with NO dependencies — not framework
  types (no HttpRequest/HttpResponse), no HTML, no SQL, no UI attributes.
- **Never embed Entity references inside request/response models**, however much
  the field lists overlap. The two serve different purposes and change for
  different reasons; coupling them violates SRP/CCP and breeds tramp data and
  scattered conditionals.

### Placement heuristics

- Field validation tied to a specific app's workflow → application rule (use-case
  layer). Domain computations meaningful outside any app (interest, inventory
  math) → critical rule (Entity).
- The business-rules code should be the most independent, most reusable code in
  the system — the heart, with everything else plugged into it.

---

## 7. Screaming Architecture — Structure Reveals Intent

### Principle

- A building's floor plan announces its purpose at a glance; a codebase's
  top-level structure should do the same. The repository layout should shout
  "health-care system" / "accounting system" / "inventory system" — NOT "Rails" /
  "Spring/Hibernate" / "ASP".
- Architecture is a **structure that supports the use cases** of the system. Use
  cases — not frameworks — are the first-class organizing elements.

### Frameworks discipline

- Frameworks are tools, not ways of life, and not architectures. Their authors and
  advocates naturally push all-pervasive adoption; do not accept that framing.
- **Adopt frameworks skeptically and defensively**: ask what it costs, how you'd
  use it, and how you'll protect the use-case-centered structure from it. Keep the
  framework at arm's length, behind boundaries, in the detail zone.
- The web itself is a delivery mechanism — an I/O device. "We deliver over the
  web" is a detail to defer, and the core should survive re-targeting to console,
  desktop, or service delivery without structural change.

### Testability payoff (verification heuristic)

- If the architecture truly centers on use cases with frameworks held at bay, then
  **all use cases are testable with no web server running and no database
  connected**: entities are plain objects; use-case objects coordinate them; both
  run in a plain unit-test harness.
- Use this as a litmus test: "can I run every business scenario without booting
  infrastructure?" If not, details have leaked into policy.

### Symptom checklist (is my architecture screaming the wrong thing?)

- Top-level directories named after framework concepts (controllers/views/models
  of tool X) rather than domain capabilities.
- New developers can name the framework instantly but must dig to find what the
  system does.
- Tests require a running server, container, or live schema to exercise business
  logic.
- Answer to "where are the controllers/views?" should legitimately be "a detail we
  haven't chosen yet" during early development — if that answer is impossible on
  day one, framework commitment came first.

---

## 8. Consolidated Agent Checklist (from this chunk)

When writing or reviewing a design, verify:

1. **Dependency direction**: every cross-boundary source dependency points toward
   higher-level policy (toward business rules). No exceptions for data flow
   direction.
2. **Interface ownership**: boundary interfaces live in the high-level component;
   low-level components implement them (plugins).
3. **Deferral**: no premature commitments to DB engine, web framework, delivery
   mechanism, DI container, or service decomposition. Each such choice should be
   swappable behind a boundary.
4. **Entity purity**: critical business rules + data isolated in modules with zero
   framework/DB/UI knowledge.
5. **Use-case purity**: application rules delivery-agnostic; plain-data request/
   response models; no framework types; no Entity references inside I/O models.
6. **Change-axis boundaries**: things that change for different reasons/rates are
   separated (layers AND use-case slices); things that change together are grouped.
7. **Duplication test**: before unifying similar code/screens/schemas, confirm the
   duplication is true (changes always co-occur), not accidental.
8. **Decoupling-mode headroom**: components could be promoted to processes/services
   without rewriting policy code — but aren't, until real pressure exists.
9. **Crossing cost awareness**: chatty interactions only across cheap (in-process)
   boundaries; coarse, latency-tolerant interactions across process/service
   boundaries.
10. **Screaming test**: the top of the source tree names domain capabilities;
    business scenarios run in tests without infrastructure.

# Clean Architecture — Distilled Chunk 4 (Ch. 22–29)

Operational knowledge for a coding agent. Covers: the Clean Architecture ring model and Dependency Rule, the Humble Object pattern, partial boundaries, layers vs. boundaries in practice, the Main component, services/microservices vs. real architecture, tests as an architectural component, and embedded/hardware-coupled code (HAL/OSAL).

---

## 1. The Clean Architecture Ring Model

### Core idea
All the well-known layered architectures (Hexagonal/Ports-and-Adapters, DCI, BCE) converge on the same goal: separation of concerns via layers, with business rules isolated from delivery mechanisms. Clean Architecture unifies them as concentric rings:

1. **Entities** (innermost) — enterprise-wide critical business rules. Can be objects with methods or plain data structures plus functions; what matters is that they encode the most general, most stable rules. They must not change because a page layout, navigation flow, or security scheme changed.
2. **Use Cases** — application-specific business rules. They orchestrate the flow of data to and from Entities and direct Entities to apply their rules. Changes to UI, DB, or frameworks must not touch this layer; changes to application behavior legitimately will.
3. **Interface Adapters** — converters between the format most convenient for use cases/entities and the format most convenient for external agents (web, DB, external services). MVC controllers, presenters, and views all live here. ALL SQL lives here (in the DB-facing part) — never further in.
4. **Frameworks & Drivers** (outermost) — the DB engine, the web framework, devices. Mostly glue code. Everything here is a replaceable detail.

### Properties a system gains from this layering
- Framework-independent: frameworks are tools you call, not cages you fit into.
- Testable: business rules run without UI, DB, web server, or any external element.
- UI-independent: swap web UI for console UI without touching business rules.
- DB-independent: swap SQL engine for a document store without touching business rules.
- Independent of any external agent: business rules know nothing about the outside world.

### The Dependency Rule (the single governing law)
**Source-code dependencies must point only inward, toward higher-level policy.**

- Nothing in an inner ring may reference ANY name declared in an outer ring — no functions, classes, variables, or data formats.
- Data formats produced by outer-ring frameworks must never be used by inner rings.
- Inner = policy, abstract, general, stable. Outer = mechanism, concrete, detailed, volatile.
- Four rings is a schematic, not a law: use as many rings as needed. The Dependency Rule always holds regardless of ring count.

### Actionable rules
- DO keep every `import`/`include`/`using` in inner-layer code pointing at inner-layer or same-layer names only. If a use case imports a framework type, that is a violation.
- DO put all SQL, ORM calls, HTTP client code, and framework annotations in the adapter layer or further out.
- NEVER let a use case or entity see a framework-generated row object, request object, or response object.
- PREFER treating a framework as a detail you plug in at the edge over building the system "inside" the framework.

---

## 2. Crossing Boundaries: Dependency Inversion at Every Seam

### Problem
Control flow often runs outward (use case needs to deliver output to a presenter in an outer ring), but dependencies must point inward.

### Mechanism
Use dynamic polymorphism to invert the dependency wherever control flow opposes the Dependency Rule:
- The inner ring declares an interface (e.g., a use-case **output port**).
- The outer ring implements it (e.g., the presenter implements the output port).
- The use case calls the interface it owns; it never names the presenter.

This same trick is applied at every boundary crossing in the system, in whatever direction control needs to flow.

### What data crosses boundaries
- Only simple, isolated data structures: DTOs, plain structs, function arguments, basic maps. Nothing clever.
- NEVER pass Entity objects across a boundary.
- NEVER pass database rows / framework "row records" inward — that forces the inner ring to know about the outer ring.
- The data format crossing a boundary must always be the one convenient for the **inner** ring.

### Reference flow (typical web + DB request)
Controller packs raw input into a plain InputData object → passes it through an InputBoundary interface to the UseCaseInteractor → interactor drives Entities, pulls persisted data through a DataAccessInterface (never SQL directly) → builds a plain OutputData object → hands it through an OutputBoundary interface to the Presenter → presenter converts everything into a ViewModel of display-ready strings and flags → View merely copies ViewModel fields to the screen. Every source dependency in this chain points inward even though control flows outward at the end.

### Actionable rules
- DO define boundary interfaces in the layer that USES them (the inner/consumer layer), and implement them in the outer layer. "The API belongs to the caller, not the implementor."
- DO convert domain types (dates, money) into display strings inside the presenter, not the view and not the use case.
- NEVER hand a live ORM entity, ResultSet, or request/response object to business logic.

---

## 3. Humble Object Pattern

### Definition
Split any behavior that straddles a hard-to-test boundary into two parts: a **humble** part containing only the untestable essence stripped to the bare minimum, and a testable part holding everything else. Originally a unit-testing pattern; in practice it marks and protects architectural boundaries.

### Canonical instances
- **Presenter (testable) / View (humble).** The View only copies values from a ViewModel to the screen. The Presenter does ALL formatting: dates → strings, currency → formatted strings with signs/colors flags, button/menu names, enabled/disabled booleans, tables of numbers → tables of formatted strings. Everything the app controls on screen appears in the ViewModel as a string, boolean, or enum.
- **Database gateways.** Between use cases and the DB sits a polymorphic gateway interface with one method per create/read/update/delete operation the application needs (e.g., a method that takes a date and returns a list of last names). Implementations live in the DB layer and are humble: they just run SQL/driver calls. Use-case interactors stay testable because gateways can be stubbed.
- **ORM ("data mappers").** There is no true object-relational *mapping* — objects are bundles of operations, data structures are bundles of public data. ORMs are data mappers moving data from relational tables into data structures; they belong in the database layer, forming another humble object boundary between gateway interfaces and the DB.
- **Service adapters.** For outbound services: app loads data into plain structures, passes them across a boundary to modules that format and transmit. For inbound: a listener receives, converts to plain structures usable by the app, passes them inward.

### Heuristics
- Testability is a proxy metric for architecture quality: the line between easy-to-test and hard-to-test almost always IS an architectural boundary.
- At nearly every boundary you can and should apply Humble Object; doing so system-wide dramatically improves overall testability.

### Actionable rules
- DO make the untestable side (view, SQL executor, device writer) so simple it obviously cannot be wrong.
- DO route every DB operation a use case needs through a named gateway method expressing intent, not query text.
- NEVER put conditional logic, formatting, or business decisions in the humble side.

---

## 4. Partial (Incomplete) Boundaries

### Problem
A full architectural boundary is expensive: two-way boundary interfaces, Input/Output data structures, dependency management, independently compilable and deployable components, version administration. Sometimes you anticipate needing a boundary but cannot justify full cost now (YAGNI says skip it; experience says "I might need it").

### Three strategies, in decreasing strength
1. **Build it fully, skip the last step.** Create all the paired interfaces and data structures as if for separate components, but compile and deploy as ONE component. Same design work, zero multi-component administration burden. Risk: with no compile-time enforcement, dependencies quietly start crossing the line in the wrong direction and the boundary erodes (this happened in real projects — once eroded, re-separating is very hard).
2. **One-dimensional boundary (Strategy pattern).** Client depends on a `ServiceBoundary` interface; `ServiceImpl` implements it. Dependency inversion exists in one direction only. Cheaper, but nothing except developer discipline prevents back-channel dependencies from forming.
3. **Facade.** A single Facade class fronts the services; no dependency inversion at all. Weakest: the client keeps transitive dependencies on all service classes (in statically typed languages, changes in services force client recompilation), and reverse coupling is trivially easy to introduce.

### Actionable rules
- DO choose the cheapest boundary form that fits current risk, and document that it is a placeholder for a possible full boundary.
- DO periodically re-inspect partial boundaries for erosion (wrong-direction dependencies).
- NEVER assume a partial boundary maintains itself — without paired interfaces, only vigilance keeps it intact.
- All three forms degrade over time if the boundary is never materialized; that is an accepted cost, not a surprise.

---

## 5. Layers and Boundaries in Practice (where to draw lines)

### Key insight
"UI + business rules + database" is enough only for trivial systems. Real systems hide many potential boundaries, each defined by an **axis of change**:
- The human language of the UI can change (English/Spanish) — one axis.
- The text delivery mechanism can change (console, SMS, chat) — a separate, independent axis, deserving its own API between language and transport.
- The storage backend can change (flash, cloud, RAM) — another axis.

### Structure that falls out
- Abstract components define APIs; concrete components (variants) implement them.
- The API is defined by and belongs to the component one level UP (the user/policy side), never to the implementor.
- Draw the diagram with all dependency arrows pointing up toward the top-level policy (e.g., GameRules): highest policy at the top, details at the bottom.
- Data flows form streams (user-interaction stream, data-storage stream) meeting at the top policy component. Added capabilities (e.g., networking) add streams. Note: dependency arrows ≠ data-flow arrows.

### Streams split as complexity grows
Even the "top" policy component divides: e.g., low-level move mechanics vs. higher-level player-state policy. The lower policy emits events (FoundFood, FellInPit); the higher policy consumes them and decides outcomes. That internal line may itself become a full architectural boundary — including a service boundary if the parts get deployed to different machines (local client component vs. server microservice).

### The economics of boundaries (decision heuristic)
- Boundaries exist EVERYWHERE potentially; implementing all of them fully is absurdly expensive.
- Over-engineering is often worse than under-engineering (YAGNI has real wisdom) — but retrofitting a missing boundary later is also very costly and risky, even with good tests and refactoring discipline.
- Therefore: this is not a one-time decision made up front. **Watch the system evolve. Notice where friction from a missing boundary first appears. Implement the boundary at the inflection point where implementing it becomes cheaper than continuing to ignore it.** This requires continuous, attentive observation, weighing cost-to-implement against cost-to-ignore, repeatedly over the project's life.

### Actionable rules
- DO identify axes of change explicitly (language, transport, storage, platform) and treat each as a candidate boundary.
- DO defer full boundaries you can't justify, but keep watching for early friction that signals it's time.
- NEVER lock in "which boundaries exist" as a day-one decision that is never revisited.

---

## 6. The Main Component

### Definition
Every system has at least one component that creates, wires, and supervises the others — Main. It is the ultimate detail, the lowest-level policy, the entry point. Nothing depends on Main except the OS; Main depends on everything it wires.

### Responsibilities
- Create all Factories, Strategies, and global facilities; then hand control to the high-level, abstract parts of the system.
- Dependency injection frameworks belong in Main and only Main. Main resolves dependencies via the DI container, then distributes them onward as ordinary constructor/argument passing — inner code never touches the container.
- Main legitimately holds the "dirty" stuff: literal string tables, resource loading, raw input stream setup, the outermost event/command loop that translates raw input into commands executed by higher-level components, initial world/map construction, configuration constants.
- Even loading a concrete implementation by class-name string in Main can be deliberate: it decouples Main's compile/deploy cycle from an even-dirtier implementation class.

### Main as a plugin
Treat Main as a plugin to the application — one that sets up the initial environment and hands off to top-level policy. Because it's a plugin, you can have MANY Mains: one per configuration (dev, test, prod), per country, per jurisdiction, per customer. Configuration problems get much simpler when config lives in swappable Main plugins behind an architectural boundary.

### Actionable rules
- DO concentrate all wiring, DI-container usage, environment setup, and concrete-class knowledge in Main/composition root.
- DO create separate composition roots for distinct deployment configurations rather than branching on environment flags deep in the code.
- NEVER reference the DI container from use cases, entities, or adapters.
- NEVER scatter literal configuration (strings, tuning constants that vary per deployment) through inner layers — push it to Main.

---

## 7. Services and Microservices vs. Architecture

### Central claim
Using services is not, by itself, an architecture. Architecture is defined by boundaries separating high-level policy from low-level detail and by adherence to the Dependency Rule. A service is just a function call that happens to cross a process/platform boundary and costs more. Some service calls are architecturally significant; most function-into-service splits are not.

### The decoupling fallacy
Services appear fully independent (separate processes, no shared variables, defined interfaces) — but only partially are:
- They can still be coupled through shared machine/network resources.
- Most importantly, they are strongly coupled by **shared data**: add a field to a record passed between services and EVERY service using that record must change and must agree on its meaning. Data coupling = indirect service-to-service coupling.
- Service interfaces are no more formal, rigorous, or well-defined than function interfaces. The "independence" benefit is largely illusory.

### The independent develop/deploy fallacy
The claim: each service is owned by one team that dev/deploys it independently, and this scales. Reality:
- History shows large systems scale fine as monoliths and component systems too; services are not the only route.
- Services coupled by data or behavior must be developed, deployed, and coordinated together — exactly to the degree they are coupled.

### The cross-cutting concern failure mode (the "kittens" problem)
A system decomposed into services along functional lines (UI service → finder → selector → dispatcher) meets a new feature that cuts across every functional step (new delivery type, with new constraints touching driver selection, customer allergy rules, supplier participation). Result: **every service must change, in coordination.** Functional service decomposition is maximally vulnerable to new features that cross-cut the functional slices.

### The fix: component architecture inside (or instead of) services
- Apply SOLID within: design a set of abstract base classes / polymorphically extensible components. A new cross-cutting feature becomes a new component (new jar/DLL/Gem) containing derived classes, loaded dynamically — existing components stay untouched except the composition edge (e.g., the UI that instantiates via factories). This is the Open-Closed Principle applied at deployment granularity.
- Services can host this too: a service = a set of abstract classes in jars; new features = new jars added to the load path, no redeploy of the service core.
- Consequence: **architectural boundaries do not run BETWEEN services; they run THROUGH services**, dividing them into components. A service may be a single component fully wrapped by a boundary, or several components separated by boundaries.

### Actionable rules
- DO judge a proposed service split by whether it creates a real policy/detail boundary obeying the Dependency Rule — not by process topology.
- DO structure each service internally as components with SOLID-style extension points so cross-cutting features arrive as new components.
- NEVER decompose into services purely along functional pipeline stages and expect independent deployability.
- NEVER claim independence for services that share mutable record formats; count that as coupling when planning changes.
- PREFER in-process component boundaries first; escalate to a service boundary only when process/platform separation itself is required (scaling, ownership, deployment reality).

---

## 8. Tests as Part of the Architecture

### Position of tests
Architecturally, all tests are the same (unit, integration, acceptance, BDD, etc.): they are the OUTERMOST ring. They always depend inward on the code under test; nothing in the system depends on them. They are independently deployable (usually only to test environments), maximally isolated, not required for production operation — and still a first-class system component, in fact a model of what a well-behaved component looks like.

### The fragile test problem
- Tests tightly coupled to the system change with the system: a trivial change to a common component breaks hundreds/thousands of tests.
- Symptom escalation: developers begin RESISTING beneficial production changes because of the test breakage they'd cause (e.g., refusing a simple navigation change because 1000 UI-driven tests would die). Fragile tests make the system rigid.
- Root cause instance: business-rule tests that drive the GUI. The UI is volatile; any suite that verifies rules THROUGH the UI is fragile by construction.

### Design for testability
- First rule of software design (for testability as for everything): **do not depend on volatile things.** The GUI is volatile → test business rules without the GUI.
- Build a dedicated **testing API**: a superset of the interactors + interface adapters that the UI uses. Its jobs: let tests verify ALL business rules directly; bypass security constraints; avoid expensive resources (databases); force the system into testable states.
- The testing API's deeper purpose is **structural decoupling**: hide the application's structure from the tests.

### Structural coupling (the most insidious form)
Anti-pattern: one test class per production class, one test method per production method. Such a suite mirrors the application's structure, so any structural refactor breaks swaths of tests. Over time, tests should become ever more concrete and specific while production code becomes ever more abstract and general — structural coupling blocks exactly this co-evolution.

### Security note
If the testing API (with its security bypasses and state-forcing hooks) would be dangerous in production, keep it and its risky implementation in a separately deployable component that is never shipped to prod.

### Actionable rules
- DO write business-rule tests against a test-facing API, not the UI, and not the raw class structure.
- DO let tests and production code evolve independently: tests get more specific, production gets more general.
- NEVER mandate 1:1 test-class-to-class or test-method-to-method mirroring.
- NEVER verify business rules through the GUI in the main suite.
- DO package dangerous test hooks separately from production deployables.

---

## 9. Clean Embedded Architecture (generalizes to ALL platform-coupled code)

### Redefinition of "firmware"
Firmware is not defined by living in ROM/flash — it's any code whose dependency on hardware/platform makes it hard to change as that platform evolves. By that definition, most teams write far too much "firmware": embedding SQL in application code, binding logic to a vendor API, mixing Android API calls into business logic — all of these convert would-be long-lived software into short-lived firmware. Software should outlive the hardware/platform generations beneath it.

### "It works" is the entry bar, not the goal
Kent Beck's sequence: make it work → make it right → make it fast. Most platform-coupled code stops after "work" (plus scattered micro-optimizations). Getting the app to work is merely a developer's aptitude test; structuring it so it can live long and change safely is the actual job. Plan to restructure/replace the first working version.

### Symptoms of the target-coupled anti-pattern
- One source file mixing domain logic (calculations, averaging, measurements), interrupt handlers, button handlers, ADC reads, flash storage, and processor sleep — grouped by nothing.
- Code testable ONLY on the target hardware/environment. If the target is the only test venue, the coupling is already throttling you: slow iteration, full manual regression on every small change, fear of change.
- Vendor compiler extensions and register names sprinkled everywhere: the code "looks like C" but no longer compiles anywhere else.
- Development can't proceed until physical hardware exists and is stable; hardware bugs stall software progress.

### The layered cure
- **Hardware ↔ everything else** is the hardest, most objective line. Enforce it before hardware knowledge infects the codebase.
- **HAL (Hardware Abstraction Layer)** — the seam between software and firmware. Its API serves the SOFTWARE's needs and vocabulary, not the hardware's: expose "store name/value pair," not "write bytes to flash"; expose `Indicate_LowBattery()`, not `Led_TurnOn(5)` (raise the abstraction to product intent). Layers recurse fractally — sublayers are fine. Never leak hardware details through the HAL to its users.
- **PAL (Processor Abstraction Layer)** — quarantine vendor compiler extensions and register access in very few files, all on the firmware side. Prefer standard headers (`stdint.h`) over vendor type headers; if the toolchain lacks them, write a thin standard-shaped shim that delegates to vendor types only when compiling for the target.
- **OSAL (Operating System Abstraction Layer)** — the OS (RTOS, embedded Linux/Windows) is also a detail. If the software depends only on the OSAL, an OS switch means writing a new OSAL, not rewriting semantics scattered through the app. The OSAL also standardizes app structure (e.g., message passing instead of per-thread ad-hoc concurrency) and provides off-target test seams. Duplication concentrated in the abstraction layer is cheap; don't fear it.

### Interfaces and substitutability on small platforms
- Program against interfaces even in C: header files ARE the interface definitions. Keep headers to function declarations plus only the constants/struct names callers need.
- NEVER stuff implementation-only types, constants, and data structures into interface headers — clutter creates unwanted dependencies. Assume implementation details will change; minimize the number of places that know them.
- Every interface is a seam/substitution point enabling layer-by-layer testing off-target.

### DRY vs. conditional compilation
`#ifdef PLATFORM_X` used once is fine; repeated thousands of times across the codebase it is a massive DRY violation. Hide platform identity inside the HAL: with HAL interfaces in place, platform selection moves to the linker or runtime binding, and the `#ifdef` forest disappears.

### Actionable rules (apply beyond embedded: any vendor SDK, cloud API, mobile platform)
- DO keep domain logic 100% free of platform/vendor names; route all platform access through an abstraction layer whose vocabulary matches the domain.
- DO make the code testable off-target from day one; treat "can only test on the real platform/environment" as an architecture bug.
- DO confine nonstandard language/SDK extensions to a minimal, named set of files.
- NEVER let a message parser, protocol handler, or business calculation live in the same module as device/transport access.
- NEVER let convenience accessors from a vendor toolkit spread through the codebase — wrap them once.
- PREFER expressing HAL/OSAL APIs in terms of what the application MEANS (intent) over what the hardware DOES (mechanism).

---

## 10. Consolidated Decision Heuristics

| Situation | Decision |
|---|---|
| Control flow must run outward across a boundary | Inner layer declares the interface (output port); outer layer implements it. |
| Choosing what data crosses a boundary | Plain DTO shaped for the inner ring. Never entities, never framework row/request objects. |
| Something is hard to unit test | Suspect an architectural boundary; split via Humble Object (dumb untestable shell + testable core). |
| Where does SQL/ORM/HTTP-client code go | Interface adapters / gateway implementations. Use cases see only intent-named gateway interfaces. |
| Full boundary too expensive but might be needed | Partial boundary: same-component paired interfaces > one-way Strategy > Facade. Monitor for erosion. |
| When to materialize a boundary | At the inflection point: when the friction cost of NOT having it starts exceeding the cost of building it. Watch continuously; don't decide once up front. |
| Where to put DI container, config, wiring, literals | Main (composition root) only. Multiple Mains for multiple configurations. |
| Team proposes microservices "for decoupling" | Check data coupling and cross-cutting features first. Services ≠ architecture; boundaries must run through service internals as components. |
| New feature cuts across many services/modules | Implement as a new component (new deployable unit of derived classes) extending abstract bases — OCP — rather than editing every service. |
| Tests keep breaking on refactors | Structural coupling. Introduce a testing API that hides application structure; stop mirroring class structure in tests; stop testing rules through the UI. |
| Code depends on vendor SDK / platform / OS specifics | Wrap behind HAL/PAL/OSAL-style abstraction owned by the software side; quarantine vendor-isms in few files; verify off-target testability. |
| Thousands of platform `#ifdef`s | Replace with HAL interfaces + link-time or runtime binding. |
| Any design question about volatility | First rule: do not depend on anything volatile (UI, schema, framework, hardware, OS). Point dependencies at stability. |

---

## 11. Anti-Pattern Index (symptom → diagnosis)

- **Inner code names outer things** (use case imports controller/DB/framework type) → Dependency Rule violation; introduce inward-owned interface.
- **Entity or DB row passed across a boundary** → hidden coupling of inner ring to outer format; replace with plain DTO shaped for the inner ring.
- **View contains formatting/logic** → missing Humble Object split; move all decisions/formatting into presenter, leave view as a data mover.
- **"Independent" services all change for one feature** → functional decomposition hit by cross-cutting concern; restructure internals into OCP components.
- **Partial boundary silently grew reverse dependencies** → boundary erosion (FitNesse web/wiki case); either re-enforce or consciously retire the boundary.
- **1000 tests break on a UI tweak; team refuses changes** → fragile-test problem making the system rigid; build a structure-hiding testing API.
- **Test suite mirrors production class structure 1:1** → structural coupling; blocks production code from generalizing.
- **Code only testable on target hardware/env** → hardware/platform coupling; introduce HAL + off-target test seams.
- **Vendor keywords/registers/SDK types throughout the code** → it's no longer portable source; quarantine behind PAL, use standard types.
- **Message/protocol handler in the same file as UART/transport driver** → software demoted to firmware; separate policy from I/O mechanism.
- **`#ifdef PLATFORM` repeated en masse** → DRY violation; push platform variance into HAL implementations.
- **DI container referenced deep in business code** → wiring leak; container usage belongs exclusively to Main.
- **The old codebase is the only "spec" of business behavior** (engineers read tangled legacy code to answer rule questions) → total policy/detail entanglement; the end state this whole chunk exists to prevent.

