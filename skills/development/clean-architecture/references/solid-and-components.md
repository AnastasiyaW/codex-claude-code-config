# Clean Architecture — Distilled Chunk 1 (Foreword–Ch. 7: Foundations, Paradigms, SRP)

Operational knowledge for a coding agent. Paraphrased concepts from the opening chapters of
Robert C. Martin's *Clean Architecture*: what architecture is, the two values of software,
the three programming paradigms as constraints, and the Single Responsibility Principle.

---

## 1. What Architecture Is (and Is Not)

### Core definitions

- **Architecture = design.** There is no meaningful boundary between "high-level architecture"
  and "low-level design." A system's shape is one continuous fabric of decisions at every level
  of detail; the fine-grained decisions support the coarse ones and vice versa. Treat a module's
  internal layout and the system's component topology as parts of the same discipline.
- **The goal of architecture is to minimize the human effort needed to build and maintain the
  system over its lifetime.** Not elegance, not diagrams, not pattern count. The single quality
  metric: how much work does it take to satisfy the next change request, and does that cost stay
  flat across releases?
- **Importance is measured by cost of change.** A decision is "architectural" to the degree that
  changing it later would be expensive. Cheap-to-reverse decisions are not architecture and
  should not be treated with architectural ceremony.
- **Diagrams are not architecture.** Boxes-and-arrows are one selective view (what to include,
  what to hide, what to emphasize). Never mistake a visualization for the actual structure, which
  lives in the code and its dependency graph.
- **Architecture is a hypothesis, validated by implementation and measurement** — not a fixed
  artifact decided up front. Good architecture preserves the natural softness/changeability of
  software as a first-class system property and treats development as continuous discovery under
  incomplete knowledge.

### Actionable rules

- **Do** judge any design decision by its effect on future change cost, not on how impressive
  it looks.
- **Do** keep effort proportional to the *scope* of a requested change, never to its *shape*.
  If small requests keep costing a lot because they "don't fit the system's shape," the
  architecture is failing — make the structure more shape-agnostic.
- **Never** rely on rigidity for "stability" — rejecting changes because they're expensive is an
  architecture failure mode, not discipline.
- **Never** pile on speculative generality (extra parameters, hooks "for later," dead code paths)
  to prepare for imagined futures. That path bloats maintenance cost with accidental complexity.
- **Prefer** structures that keep options open over structures that bet hard on one predicted
  future; you cannot reliably predict which changes will come.

### Failure modes (symptoms)

| Failure mode | Symptoms |
|---|---|
| Rigid/authoritarian architecture | Changes rejected as "too expensive"; developers work around the architecture; morale sinks |
| Speculative generality | Unused config knobs, dead code, endless parameters, maintenance budget eaten by complexity nobody asked for |
| Diagram-driven architecture | Pretty slides that don't match the actual code dependency graph; decisions made on the picture, not the code |

---

## 2. The Economics of Mess (Why Structure Pays)

### Core principle

- **Making a mess is always slower than staying clean — on every time scale.** The belief
  "we'll ship dirty now and clean up later" is the industry's most common self-deception:
  market pressure never relents, so "later" never arrives, and the mess compounds.
- **The productivity death spiral:** as coupling and disorder grow, each release costs more per
  line of change; developer effort shifts from building features to shuffling the mess around;
  productivity asymptotically approaches zero even though everyone works hard. Headcount grows,
  output doesn't. Cost per line of code can grow ~40x across releases.
- **A ground-up rewrite driven by the same overconfidence reproduces the same mess.** The
  impulse that says "we'll do it right this time" is the same impulse that created the mess.
- Evidence point cited: in a repeated small-task experiment, working test-first (TDD) was ~10%
  faster than working without tests; even the *worst* disciplined day beat the *best*
  undisciplined day. Discipline is not a tax — it's the fast path.

### Actionable rules

- **Do** keep the code clean as you go; treat cleanliness as the speed strategy, not its enemy.
- **Never** justify a hack with "we'll clean it up after launch" — plan the clean version now
  or explicitly ticket the debt with a concrete follow-up.
- **Never** propose a full rewrite as the escape hatch from a mess; incremental structural
  repair under discipline beats re-running the race with the same habits.
- **Do** take architecture quality seriously from the *start* of a system; retrofitting is what
  the death-spiral graphs describe.

### Decision heuristic

- When tempted to trade structure for speed: the trade is illusory beyond the immediate commit.
  Choose the disciplined path unless the code is genuinely throwaway (and be honest about
  whether it actually is).

---

## 3. The Two Values of Software (Behavior vs. Structure)

### Core principle

- Every software system delivers two distinct values:
  1. **Behavior** — it does what stakeholders need right now (requirements, features, bug fixes).
  2. **Structure** — it stays *soft*: easy to change as needs evolve. This is the "soft" in
     software; the entire point of software over hardware is changeability.
- **Structure is the greater value.** Proof by extremes:
  - A program that works perfectly but cannot be changed becomes useless the moment
    requirements change (and they will).
  - A program that doesn't work but is easy to change can be made to work — and kept working
    forever.
- "Impossible to change" in practice means "cost of change exceeds its benefit" — many real
  systems reach this state for whole features or configurations.

### Eisenhower matrix applied

- Behavior is **urgent** but not always important. Structure is **important** but rarely urgent.
- Correct priority order: (1) urgent+important, (2) important+not-urgent, (3) urgent+not-important,
  (4) neither. Architecture sits in slots 1–2; behavior occupies 1 and 3.
- **The classic management error:** promoting urgent-but-unimportant behavior work (slot 3) into
  slot 1, letting architecture starve indefinitely.

### Actionable rules

- **Do** weigh every "just make it work" request against the structural damage it causes;
  fight for structure as part of the job, not as a favor.
- **Do** treat the development team as a stakeholder whose stake is the system's changeability —
  advocating for structure is a responsibility, not obstruction.
- **Never** let feature urgency permanently defer structural work; if structure always loses the
  scheduling fight, change cost will climb until change becomes effectively impossible.
- **Heuristic:** if a stakeholder says "working now matters more than flexibility later," note
  that the same stakeholder will not accept "this change costs too much" later. Optimize for the
  request stream, not the single request.

---

## 4. Paradigms Are Constraints (Overview)

### Core principle

- A **paradigm** is a discipline about *what code structures to use and when*, independent of
  language. Exactly three exist, all discovered 1958–1968, and each **removes** a capability
  rather than adding one:
  1. **Structured programming** — removes unrestricted *direct* transfer of control (`goto`).
  2. **Object-oriented programming** — disciplines *indirect* transfer of control
     (raw function pointers → safe polymorphism).
  3. **Functional programming** — restricts *assignment* (mutation of state).
- Expect no fourth paradigm: there's nothing significant left to take away. All programs are
  still built from sequence, selection, iteration, and indirection.
- **Architectural mapping** — each paradigm serves one of the three big architectural concerns:
  - Polymorphism (OO) → the mechanism for crossing **architectural boundaries**.
  - Functional discipline → controls **data location and access order**.
  - Structured programming → the **algorithmic substrate of modules**.

### Agent takeaway

- **Do** treat paradigms as constraint systems to apply where each pays off, not tribal
  identities. In one codebase you will use structured decomposition inside functions, polymorphic
  interfaces at module boundaries, and immutability around concurrency.

---

## 5. Structured Programming (Provability & Decomposition)

### Core principles

- Unrestricted `goto` prevents recursive decomposition of a program into small provable units;
  the "benign" control patterns (sequence, if/else selection, while-loop iteration) are exactly
  the minimal set sufficient to express any program *and* the set that keeps modules decomposable
  and analyzable.
- **Functional decomposition:** any large problem can be recursively split into small functions
  built only from those three structures. This is what makes divide-and-conquer reasoning about
  code possible at all.
- **Software correctness works like science, not math.** You cannot prove a program correct;
  you can only fail to prove it wrong. *Tests show the presence of bugs, never their absence.*
  After sufficient failed falsification attempts, we deem code "correct enough."
- Crucially, **falsification only applies to testable (provable-shaped) units.** A tangle that
  can't be decomposed can't be meaningfully tested — no quantity of tests makes an untestable
  blob trustworthy.

### Actionable rules

- **Do** decompose all logic into small, independently exercisable functions with single entry
  and comprehensible control flow.
- **Do** design modules, components, and services so their incorrectness would be *easy to
  demonstrate* — i.e., testable by construction. "Hard to write a test for" is an architecture
  smell, not a testing-tools problem.
- **Never** write control flow that defeats decomposition (spaghetti jumps, deeply intertwined
  state machines with no seams) — you forfeit the ability to establish confidence via tests.
- **Prefer** structured constructs over clever jump-like tricks; even where a language allows
  restricted `goto`-ish forms (labeled break, exceptions), keep them scoped and rare.

### Decision heuristic

- At every scale (function → module → service), ask: *"could a test falsify this unit's
  behavior?"* If not, restructure until the answer is yes. This is the same constraint-based
  thinking as structured programming, applied at architecture level.

---

## 6. Object-Orientation = Safe Polymorphism = Dependency Control

### Core principles

- The classic OO trinity is weaker than advertised:
  - **Encapsulation** is not OO-specific (C headers/implementation files did it perfectly;
    C++/Java/C# actually *weakened* it by exposing member declarations). Real encapsulation
    ultimately relies on programmer discipline.
  - **Inheritance** is a convenience wrapper over an old trick (struct-superset masquerading);
    OO made it safer and enabled multiple inheritance, but it's not the essence.
  - **Polymorphism** is the real prize. Function pointers always allowed it, but raw pointers
    are dangerous convention-bound machinery; OO languages made polymorphism **safe, convenient,
    and trivial to use** — and that changed everything.
- **The plugin architecture insight:** with polymorphism, callers depend only on an interface;
  concrete implementations become interchangeable plugins (the way OS device drivers make
  programs device-independent). Adding a new implementation requires no change — not even
  recompilation — of the calling policy code.
- **Dependency Inversion:** without polymorphism, source-code dependencies are forced to follow
  the flow of control (caller must reference callee's module). An interface inserted at a call
  site *reverses* the source dependency against the control flow. Therefore **the architect has
  absolute control over the direction of every source-code dependency**, independent of who
  calls whom.
- Consequence: you can make the database and the UI depend on the business rules rather than
  the reverse. Business rules then compile into a component with zero references to UI/DB.
  That yields **independent deployability** (redeploy only the changed component) and
  **independent developability** (separate teams own separate components).

### Actionable rules

- **Do** route every dependency that crosses an important boundary through an interface owned
  by the higher-level (policy) side.
- **Do** structure I/O, storage, UI, and other low-level details as plugins to the business
  logic — the core must compile without them.
- **Never** let high-level policy code `import`/`#include` low-level detail modules directly;
  that welds the dependency graph to the call graph and forfeits deployment/development
  independence.
- **Never** justify a design as "OO" by pointing at classes and inheritance; the architecturally
  relevant question is only: *which way do the source dependencies point?*
- **Prefer** interface-inversion over direct calls **when** the callee is a detail likely to
  change, be swapped, or be deployed separately; skip the ceremony for stable, local,
  same-level helpers.

### Failure modes (symptoms)

| Failure mode | Symptoms |
|---|---|
| Dependencies follow control flow everywhere | Business logic imports DB/UI/framework modules; changing a detail forces recompiling/redeploying the core |
| Fake encapsulation reliance | Callers exploit visible internals ("we know the private field is there"); renaming a private member forces client recompiles |
| Inheritance as the main reuse tool | Deep hierarchies for code sharing rather than substitutability; fragile-base-class churn |

---

## 7. Functional Programming, Immutability & Concurrency

### Core principles

- Functional discipline restricts **assignment**: values, once bound, are not mutated.
- **Why architects must care:** every race condition, deadlock, and concurrent-update bug is
  caused by *mutable* state. No mutable variables → that whole bug class cannot exist. In a
  multi-core/multi-thread world, immutability is a direct robustness lever.
- Full immutability is achievable only with unbounded memory/CPU; real systems make
  **compromises**:
  1. **Segregate mutability.** Split the system into immutable (purely functional) components
     and a minimal set of components that hold mutable state. Guard the mutable ones with
     transactional mechanisms (e.g., atomic compare-and-swap / transactional memory).
     Push as much code as possible into the immutable side.
  2. **Event sourcing.** Store the *transactions* (facts/events), not the mutable state; compute
     state on demand by folding over events (optionally from periodic snapshots, e.g. nightly).
     Nothing is ever updated or deleted — CRUD degenerates to CR — so concurrent-update problems
     vanish by construction. Version control systems are the proof this model works at scale.
- Caveat: simple atomic primitives protect a single variable; with **multiple interdependent
  mutable variables** they don't prevent races/deadlocks — use stronger coordination there.

### Actionable rules

- **Do** default to immutable data structures and pure functions; introduce mutation only where
  measured resource constraints demand it.
- **Do** quarantine unavoidable mutable state in small, explicitly-marked components, protected
  by transactional/atomic mechanisms — never scattered through the codebase.
- **Prefer** append-only event/transaction logs over in-place updates **when** audit history,
  concurrency safety, or reproducibility matter and storage is affordable; derive current state
  by replay + snapshots.
- **Never** share mutable variables across threads without a protection discipline; and never
  assume single-variable atomics compose safely across several interdependent variables.

### Decision heuristic

- Concurrency bug appears (race, deadlock, torn update)? First question: *which mutable state
  is shared, and can it be made immutable or event-sourced?* Removing mutation beats adding
  locks.

---

## 8. SOLID: Purpose and Scope (Orientation)

- SOLID principles govern the **mid-level**: how functions and data are grouped into
  modules/classes and how those groupings interconnect. "Class" here just means a cohesive
  grouping of functions + data — the principles apply in non-OO code too.
- Their goal: mid-level structures that (a) tolerate change, (b) are easy to understand,
  (c) can serve as reusable components across systems.
- Clean bricks aren't enough: **good modules can still be assembled into a terrible system** —
  component-level and architecture-level principles must sit above SOLID.
- One-line summaries (each expanded in later chunks):
  - **SRP** — each module answers to exactly one actor (one reason to change).
  - **OCP** — change behavior by adding code, not by modifying existing code.
  - **LSP** — interchangeable parts must honor a substitution contract.
  - **ISP** — don't depend on things you don't use.
  - **DIP** — high-level policy never depends on low-level detail; details depend on policy.

---

## 9. Single Responsibility Principle (SRP) — In Depth

### Correct definition (commonly misunderstood)

- SRP does **not** mean "a module does one thing." (That's a *different*, valid rule: *a
  function* should do one thing — used when splitting big functions. It is not SRP.)
- SRP: **a module should have one, and only one, reason to change** — refined to: **a module
  should be responsible to one, and only one, actor**, where an *actor* is a group of
  stakeholders/users who request changes for the same reason.
- "Module" ≈ a source file, or any cohesive grouping of functions and data. *Cohesion* is
  precisely the force that binds code serving a single actor.
- SRP is the module-level face of a scale-invariant idea: at component level it becomes the
  Common Closure Principle; at architecture level it drives boundary placement along axes of
  change.

### Violation symptom 1 — accidental duplication coupling actors

- Canonical example: an `Employee` class with `calculatePay()` (owned by finance),
  `reportHours()` (owned by HR), and `save()` (owned by DBAs). Three actors, one module.
- The disaster pattern: two actor-facing methods secretly share a helper (e.g., a
  regular-hours algorithm). Actor A requests a change to "their" calculation; a developer edits
  the shared helper, tests only A's path, ships. Actor B's numbers silently go wrong —
  discovered later at high cost.
- **Rule:** code that different actors depend on must be separated. Sharing code across actor
  boundaries to "avoid duplication" is *false* deduplication when the two uses can evolve
  apart — divergence pressure will hit eventually.

### Violation symptom 2 — merge collisions

- A file serving multiple actors gets edited concurrently by different people/teams for
  unrelated reasons → merges, and every merge carries risk to *all* actors involved.
- Frequent merge conflicts in one file are a mechanical, observable signal of SRP violation:
  the file has more than one reason to change.

### Solutions

- All fixes come down to **moving functions into separate classes/modules per actor**:
  1. **Separate data from functions:** a plain data structure (e.g., `EmployeeData`) shared by
     several single-actor classes (PayCalculator, HourReporter, EmployeeSaver) that don't know
     about each other.
  2. **Facade:** if juggling several classes annoys callers, add a thin facade that instantiates
     and delegates — keeping the actor-separated implementations behind it.
  3. **Policy-keeps-the-data variant:** keep the most important business methods with the data
     in the original class and have it act as facade over the lesser, extracted concerns.
- Don't fear "classes with one public function" — real actor-facing responsibilities typically
  grow families of private helpers inside their module; the module becomes the scope that hides
  that family.

### Actionable rules

- **Do** identify, for every module, *who* (which actor/stakeholder group) drives its changes.
  If the honest answer lists two+ actors, split the module along those lines.
- **Do** separate persistence code, reporting/formatting code, and business-calculation code —
  these almost always answer to different actors (DBAs, ops/HR/consumers, domain owners).
- **Never** merge two similar-looking algorithms into one shared function when they serve
  different actors — tolerate the apparent duplication or split along the actor boundary first.
- **Never** ignore recurring merge conflicts in a hotspot file; treat them as an SRP alarm and
  decompose the file.
- **Prefer** a facade over forcing clients to know several actor-specific classes **when**
  ergonomic single-entry access matters; the facade must stay thin (construction + delegation
  only).

### Decision heuristics

- *"Would change requests to this code ever come from different departments/roles/systems for
  different reasons?"* → different actors → separate modules.
- *"If I change this shared helper for requester X, could any other consumer's semantics
  silently break?"* → the helper spans actors → duplicate or split it.
- Apparent code duplication is only true duplication if all copies must change **together,
  for the same reason**. Same-shape-today but different-evolution is not duplication — keep
  them apart.

---

## 10. Cross-Cutting Agent Checklist (from this chunk)

When writing or reviewing code, verify:

1. **Change-cost lens:** does this decision keep the next change cheap? Is effort proportional
   to change scope, not shape?
2. **No "clean up later":** the disciplined version is written now, or the debt is an explicit,
   tracked ticket — never an implicit promise.
3. **Structure ≥ behavior:** feature pressure did not silently cannibalize changeability.
4. **Testability by construction:** every unit is decomposed such that a test could falsify it;
   "untestable" triggers restructuring, not test-skipping.
5. **Dependency direction audit:** all source dependencies across significant boundaries point
   from details toward policy (via interfaces); business core compiles without UI/DB/frameworks.
6. **Plugin-ability:** could the DB/UI/transport be swapped by adding a new implementation
   without touching (or recompiling) core logic?
7. **Mutation audit:** mutable shared state is minimized, quarantined, and guarded
   (atomic/transactional); concurrency issues are addressed by removing mutation first.
8. **Actor audit (SRP):** each module answers to exactly one actor; no shared helpers straddle
   actor boundaries; persistence/reporting/business logic live apart.
9. **Merge-conflict hotspots** are treated as SRP violations and decomposed.
10. **No rewrite reflex:** structural problems are repaired incrementally with discipline rather
    than by "starting over."

# Clean Architecture — Distilled Chunk 2 (Chapters 8–14)

Operational knowledge for a coding agent. Covers: OCP, LSP, ISP, DIP (the tail of SOLID),
what a component is, component cohesion principles (REP, CCP, CRP), and component coupling
principles (ADP, SDP, SAP) with the stability/abstractness metrics.

---

## 1. Open-Closed Principle (OCP)

**Definition.** A software entity should allow its behavior to be extended without editing
its existing source. If a routine requirement extension forces widespread edits to existing
code, the design has failed at its main job.

**Mechanism.** OCP is achieved by combining two other principles:
- Separate things that change for different reasons (SRP) — e.g., computing report data
  vs. rendering it for the web vs. rendering it for print are distinct responsibilities.
- Point dependencies so that the code you want to shield never references the code likely
  to change (DIP).

**The protection hierarchy.** Components form levels of importance. Business-rule logic
(interactors/use cases) sits at the top; controllers below it; presenters below controllers;
views at the bottom. The rule for direction:

> If component A must be protected from changes in component B, then B must depend on A —
> never the reverse.

Higher-level policy is protected from lower-level detail by making all source dependencies
point upward (toward policy).

**Agent rules:**
- When adding a new output format / delivery channel / variant of behavior, add new code
  (new class, new implementation of an existing interface) rather than editing the shared
  computation. If you must edit shared code to add a variant, flag the design as an OCP
  violation and consider extracting an interface first.
- Insert interfaces deliberately to *invert* dependency arrows that would otherwise flow
  from high-level policy to low-level detail (e.g., a gateway interface owned by the
  business logic, implemented by the database layer).
- Also add interfaces for **information hiding**: shield callers from transitive knowledge
  of internals they don't use. A controller should see a use-case boundary interface, not
  the interactor's concrete entities.
- Diagram sanity check: in a well-formed design, dependency arrows between components cross
  each boundary in only one direction.

**Failure symptom.** "Small new requirement → cascade of edits across many modules" — the
canonical sign OCP is being violated.

---

## 2. Liskov Substitution Principle (LSP)

**Definition.** S is a subtype of T only if any program written against T behaves correctly
when handed an instance of S instead — with no special-casing. Substitutability is defined
by *behavior the client relies on*, not by the type hierarchy compiling.

**Classic violation: square/rectangle.** A Square subclassing Rectangle breaks clients that
assume width and height are independently settable (`setW(5); setH(2); assert area==10`
fails). If the client needs `if (isActuallySquare)` checks, the types are not substitutable
and the inheritance is wrong.

**LSP scales to architecture.** It applies to anything with a shared interface: Java-style
interfaces, duck-typed classes sharing method signatures, or a fleet of REST services that
must all honor a common endpoint contract. One service that slightly deviates from the
agreed contract (e.g., renames a field `destination` → `dest`) forces the caller to grow
special-case dispatch logic. Special cases metastasize: each new deviant partner adds
another branch, or forces building a whole configuration-driven mechanism that would never
have been needed if all implementations were truly interchangeable.

**Agent rules:**
- Never create a subtype (or interface implementation, or API implementation) that weakens,
  reinterprets, or narrows the contract clients depend on. Match preconditions/
  postconditions/invariants, not just method signatures.
- Never handle interface-implementation differences with `if (impl is X)` / string-matching
  on identity (`url.startsWith("acme.com")`). That hardcodes a partner name into policy
  code — brittle, and a security/maintenance hazard. If deviations are unavoidable, isolate
  them behind a data-driven adapter/config table at the boundary, keeping core logic uniform.
- When designing inheritance, ask: "could a client written purely against the base type be
  surprised by this subtype?" If yes, use composition or a different abstraction.
- Treat external services implementing "your" interface as LSP subjects: enforce the
  contract (validation, conformance tests), don't absorb deviations into core code.

**Failure symptom.** Type-checks/special-case branches in client code keyed on which
implementation it got; a growing translation mechanism compensating for non-conforming
implementations.

---

## 3. Interface Segregation Principle (ISP)

**Definition.** Don't force a client to depend on operations it never uses. Split fat
interfaces into role-specific ones so each client sees only what it needs.

**Why it matters mechanically.** In statically typed languages, a client of a fat class
gets recompiled/redeployed when *any* method of that class changes — including methods the
client never calls. Segregated interfaces (U1Ops with only op1, etc.) cut those false
dependencies. Dynamically typed languages dodge the compile-time coupling, which is partly
why they feel more flexible — but the deeper issue remains language-independent.

**Architectural generalization.** Depending on a module/framework/system that carries more
than you need is dangerous at every level. If system S uses framework F, and F is welded to
database D, then S transitively depends on all of D — including features neither S nor F
uses. Changes or bugs in those unused features can still force redeployment of, or inject
faults into, S.

**Agent rules:**
- Define interfaces per-client-role, not per-implementation. If three callers each use a
  disjoint subset of a class's methods, give each caller its own narrow interface.
- Before adding a dependency (library, framework, service), check what baggage it drags in
  transitively. Prefer dependencies that carry only what you use; wrap or isolate heavy
  ones behind your own thin interface.
- Avoid transitive dependencies on things not used directly — this is the same rule at the
  component scale (see CRP below).

**Failure symptom.** Rebuild/redeploy storms triggered by changes in methods nobody in the
affected module calls; a bug in an unused feature of a dependency breaking your system.

---

## 4. Dependency Inversion Principle (DIP)

**Definition.** The most flexible systems have source-code dependencies that point at
abstractions (interfaces, abstract classes), not at concrete, volatile implementations.

**Pragmatic scope — stability, not purity.** You cannot avoid depending on concretions
entirely (e.g., the platform's String class). The principle targets *volatile* concretions:
modules under active development that change often. Stable platform/OS foundations are
tolerated as dependencies precisely because they don't change.

**Why abstractions are the stable end.** Changing an interface forces changes in all its
implementations, but changing an implementation rarely forces interface changes. Interfaces
are therefore inherently less volatile — good architects actively fight to keep interface
churn near zero, adding capability via new implementations instead.

**Concrete coding rules (verbatim intent, own words):**
1. **Don't reference volatile concrete classes.** Reference interfaces instead. This also
   pushes object creation toward the Abstract Factory pattern.
2. **Don't inherit from volatile concrete classes.** Inheritance is the strongest, most
   rigid source relationship — apply it with extra caution (in any typing discipline).
3. **Don't override concrete functions.** A concrete function carries its source
   dependencies with it; overriding inherits those dependencies rather than removing them.
   Make the function abstract and provide multiple implementations instead.
4. **Never mention the name of anything concrete and volatile** — the summary form of the
   whole principle.

**Factories and the architectural boundary.** Creating an object normally requires a source
dependency on its concrete class. To create volatile objects without that dependency:
depend on an abstract factory interface; a concrete factory (on the other side of the
boundary) instantiates the implementation and returns it typed as the interface. The system
divides into an abstract component (all high-level business rules) and concrete components
(implementation details). All source dependencies cross the boundary pointing toward the
abstract side — **opposite to the flow of control**. That reversal is what "inversion" means.

**The main component.** DIP violations can't be eliminated entirely — they get concentrated
into a small number of concrete components (typically `main`), which instantiates factories/
implementations and hands them to the abstract side (e.g., via a globally accessible
factory reference). Keep the dirt in one place, isolated from the rest of the system.

**Agent rules:**
- When high-level logic needs a low-level service (DB, network, filesystem), define the
  interface *on the high-level side* and implement it on the low-level side.
- Route creation of volatile objects through factories/DI wiring living in the concrete
  outer layer (main/composition root); never `new` a volatile concrete class inside
  business logic.
- Judge a dependency by volatility, not concreteness alone: stdlib and frozen platform APIs
  are fine to use directly; the teammate's actively-churning module is not.

**Failure symptom.** Business-rule code with imports of concrete infrastructure classes;
control flow and dependency arrows pointing the same direction across every boundary.

---

## 5. Components — the Unit of Deployment

**Definition.** A component is the smallest independently deployable unit of a system:
jar, gem, DLL, or an equivalent bundle. Well-designed components remain independently
deployable and therefore independently developable, whether they end up statically linked
into one executable or loaded as runtime plugins.

**Historical takeaway (the only operationally relevant part).** Decades of evolution in
linking/loading (manual memory layout → relocatable code → linking loaders → separate
linkers → cheap fast hardware) ended at dynamically linked, runtime-pluggable components.
Plugin architecture is now the cheap default, not a heroic feat — so architectures should
exploit it: ship variability as plugins around a stable core.

**Agent rules:**
- Treat "can this be deployed on its own?" as the definition of component boundaries, not
  folder taxonomy.
- Preserve independent deployability when refactoring: don't fuse two components with a
  code-level dependency that forces them to ship together, unless deliberately merging them.

---

## 6. Component Cohesion — Which Classes Go in Which Component

Three principles govern grouping; they pull in different directions.

### 6.1 REP — Reuse/Release Equivalence Principle
**"The unit of reuse is the unit of release."** People only reuse components that go
through a release process with version numbers and release notes, because consumers need
to know when a new version lands, what changed, and whether to adopt it. Consequences:
- Classes/modules grouped in a component must form a cohesive, purposeful whole — a
  releasable "theme," not a grab-bag.
- Everything in a component is released, versioned, and documented **together**; that
  joint release must make sense to both author and consumers.
- The principle is loose ("makes sense") but violations are conspicuous: users notice a
  random-assortment component immediately.

### 6.2 CCP — Common Closure Principle
**Group classes that change for the same reasons at the same times; separate classes that
change at different times for different reasons.** This is SRP restated for components.
Rationale:
- For most applications, maintainability outranks reusability. When a change comes, it's
  far better for it to land entirely inside one component (one rebuild, one redeploy, no
  re-validation of untouched components) than to be sprinkled across many.
- CCP is the component-level face of OCP "closure": since 100% closure is impossible,
  close components strategically against the *kinds* of change experience says are likely,
  and co-locate classes closed against the same kind of change.

Shared formula for SRP + CCP: **gather what changes together for the same reason; separate
what changes at different times for different reasons.**

### 6.3 CRP — Common Reuse Principle
**Don't force a component's users to depend on things they don't need.** Classes that are
reused together (a collection class and its iterators) belong in the same component; classes
without tight mutual coupling do **not** belong together. Rationale: depending on one class
in a component means depending on the whole component — every release of it triggers
recompile/retest/redeploy of dependents even if the used class is untouched. So a
component's classes should be inseparable: it should be impossible to depend on "half" of
it. CRP is ISP generalized to components. Joint slogan:

> **Don't depend on anything you don't use.**

### 6.4 The tension triangle
REP and CCP are *inclusive* (push components bigger); CRP is *exclusive* (pushes them
smaller). There is no static right answer:
- **Early project life:** favor CCP (developability) over REP — ease of change beats
  reusability; only reuse is sacrificed.
- **As the project matures and gets consumed by others:** the balance slides toward
  REP/CRP (reusability, minimal dependency baggage).
- Component partitioning is expected to **change over time** with the project's focus —
  a grouping that's right today may be wrong in a year. It reflects how the project is
  built and consumed, more than what the code does.

**Agent rules:**
- When deciding where a new class lives: first ask "what else changes when this changes?"
  (CCP), then "who reuses this, and would they be forced to drag along unrelated stuff?"
  (CRP), then "does the containing component still form a sensible release unit?" (REP).
- Don't split components for reuse purity in a young single-team app; don't keep a
  kitchen-sink component in a library others consume.
- If a routine change consistently touches N components, the partitioning violates CCP —
  consider merging or re-slicing.
- If consumers of your component keep getting rebuilt over changes to classes they never
  touch, split it (CRP).

---

## 7. Component Coupling — How Components May Depend on Each Other

### 7.1 ADP — Acyclic Dependencies Principle
**No cycles in the component dependency graph. The graph must be a DAG.**

**Problem it solves — "morning-after syndrome."** Multiple developers touching shared code
find their working build broken overnight by someone else's change. Weekly-integration
buildups don't scale: integration cost grows with project size until it swallows the
schedule and destroys feedback speed.

**The working model.** Split the system into independently releasable components. Each
team releases versioned snapshots; consumers adopt a new version when they choose. No team
is at another's mercy; integration happens in small increments. This *only* works if the
dependency structure has no cycles.

**Why cycles hurt (symptoms):**
- Components in a cycle effectively fuse into one giant component: their teams must all
  use the same versions of each other's work, morning-after syndrome returns.
- Unit-testing one component in the cycle requires building/integrating all of them —
  "why do I need forty libraries to test one class?" usually means a hidden cycle.
- There is no correct build order for a cyclic graph.
- Release effort compounds sharply with the number of entangled modules.

**Breaking a cycle — two mechanisms:**
1. **DIP:** define an interface with the methods the depending class needs, place the
   interface in the *depended-upon-turned-dependent* component, implement it in the other.
   The offending arrow flips and the cycle breaks.
2. **Extract a new component:** move the classes both sides need into a fresh component
   both depend on.

**Structure "jitters":** cycle-breaking makes the component graph grow and mutate as
requirements evolve. Monitor for new cycles continuously; expect the graph to change.

**Top-down design is impossible for component structure.** The component graph is a map
of *buildability and maintainability*, not of function. It cannot be designed before code
exists, because early on there's nothing to build or maintain and nothing is known about
change-coincidence or reuse. It grows with the system: first SRP/CCP grouping to contain
change ripple, later CRP for reuse, then ADP repairs as cycles appear. Don't attempt to
freeze a component decomposition on day one — it will be wrong and probably cyclic.

**Agent rules:**
- Before adding a dependency between components/packages/modules, check whether it creates
  a cycle (follow the arrows). If it would, break it with DIP or by extracting a shared
  component — never ship the cycle.
- Treat "testing X requires building half the system" as a cycle smell worth diagnosing.
- Expect and allow the module graph to be refactored as the system grows; it's a living
  artifact.

### 7.2 SDP — Stable Dependencies Principle
**Depend in the direction of stability.** A component designed to be easy to change must
not be depended upon by a component that's hard to change — otherwise the "flexible"
component becomes hard to change too, without a single line of its code changing.

**Stability defined.** Stability ≈ effort required to change, not frequency of change.
The dominant driver: incoming dependencies. A component many others depend on is stable
(responsible: changes require coordinating all dependents); a component depending on many
others but with no dependents is unstable (irresponsible and dependent: pressure to change
flows in from every dependency, and nothing restrains it).

**Metrics:**
- `Fan-in` — count of classes outside the component that depend on classes inside it.
- `Fan-out` — count of classes inside that depend on classes outside.
- **Instability `I = Fan-out / (Fan-in + Fan-out)`**, range [0,1].
  `I = 0` → maximally stable (depended-upon, depends on nothing).
  `I = 1` → maximally unstable (depends outward, nothing depends on it).
- SDP formally: **I must decrease along every dependency arrow** (a component's I should
  exceed the I of everything it depends on).

**Not everything should be stable** — a system of only I=0 components is unchangeable.
Healthy designs put volatile components "on top," depending downward on stable ones. Any
dependency arrow pointing from a stable component toward a flexible one is a violation;
fix it by DIP: extract an interface component (which will be maximally stable, I=0) that
both the stable consumer and the flexible implementation depend on.

**Abstract (interface-only) components** — components containing nothing but interfaces —
are normal, necessary in statically typed languages, and ideal dependency targets. (Dynamic
languages skip them because inversion needs no declared interfaces there.)

### 7.3 SAP — Stable Abstractions Principle
**A component should be as abstract as it is stable.** Stable components should consist of
interfaces/abstract classes so they can be extended without modification (OCP applied to
the stability problem); unstable components should be concrete, since their instability
makes their code freely editable. SDP + SAP together = DIP at component granularity:
dependencies point toward stability, stability implies abstractness, therefore dependencies
point toward abstractness. Unlike class-level DIP (binary abstract-or-not), components can
be *partially* abstract/stable.

**Abstractness metric:**
- `A = Na / Nc` — abstract classes + interfaces over total classes, range [0,1].

**The Main Sequence.** Plot components on (I, A). Ideal corners: (0,1) stable+abstract and
(1,0) unstable+concrete. Two exclusion zones:
- **Zone of Pain — near (0,0):** stable and concrete. Rigid: can't be extended (not
  abstract), hard to change (heavily depended-upon). Classic residents: database schemas
  (volatile + concrete + massively depended-upon → schema migrations are painful) and
  widely-used concrete utility libraries. Note: *non-volatile* things near (0,0) (frozen
  platform classes) are harmless — pain scales with volatility.
- **Zone of Uselessness — near (1,1):** maximally abstract with no dependents. Dead
  weight: leftover abstract classes nobody ever implemented.
- The **Main Sequence** is the line from (0,1) to (1,0) — positions maximally distant from
  both bad zones. A component on it is exactly as abstract as its stability warrants.

**Distance metric:**
- `D = |A + I − 1|`, range [0,1]. D=0 → on the Main Sequence; D→1 → deep in a bad zone.
- Use D per component to flag candidates for restructuring; use mean/variance of D across
  the codebase as a design health statistic with control limits; track D of a component
  over releases to catch creeping bad dependencies (a rising D trend = investigate).
- Metrics are heuristics against an arbitrary standard, not gospel — use them to direct
  attention, not to auto-pass/fail designs.

**Agent rules:**
- Put high-level policies/business rules in stable (low-I), abstract (high-A) components;
  keep volatile detail code in unstable, concrete components that depend on the stable core.
- Check every new inter-component dependency: does I decrease along the arrow? If a
  widely-depended-upon module starts importing a volatile helper, that's an SDP violation —
  invert it with an interface.
- If you find a heavily-depended-upon concrete component that keeps needing changes (Zone
  of Pain), prioritize extracting abstractions from it.
- Delete or implement orphaned abstractions with no dependents (Zone of Uselessness).
- When auditing a codebase's architecture, computing Fan-in/Fan-out/I/A/D per package is a
  cheap mechanical first pass to locate structural hotspots.

---

## 8. Cross-Cutting Decision Heuristics (chunk summary)

| Situation | Apply |
|---|---|
| New behavioral variant of an existing feature | OCP: add code via new implementation of an interface; don't edit shared policy |
| Choosing what may depend on what | "B depends on A" iff A must be shielded from B's changes; dependencies point toward higher-level policy, stability, and abstractness |
| Designing a subtype / API implementation | LSP: client written against the base must never need to know which one it got; no identity-based special cases in clients |
| Client uses a small slice of a big module | ISP: give it a narrow role interface; don't depend on unused baggage (transitively too) |
| High-level code needs low-level service | DIP: interface owned by the high level, implemented by the low level; construct via factory in the composition root |
| Volatile vs. stable concrete dependency | Depend freely on frozen platform concretions; never on actively-changing concrete modules |
| Grouping classes into packages/components | Early: CCP (co-change) dominates. Mature/shared: shift toward CRP (no unused baggage) + REP (sensible release unit). Revisit over time |
| A change keeps touching many components | CCP violation → re-slice so that one reason-to-change lives in one component |
| Dependents rebuilt by changes to classes they don't use | CRP violation → split the component |
| Found/creating a dependency cycle | ADP: break with DIP interface or extracted shared component; never leave a cycle |
| "Testing one class needs the whole world" | Suspect a dependency cycle; map the graph |
| Stable module depends on flexible one | SDP violation → extract interface component both depend on |
| Heavily-used + concrete + frequently changing module | Zone of Pain → extract abstractions to decouple dependents |
| Abstract interfaces nobody implements/uses | Zone of Uselessness → delete |
| Wanting a mechanical architecture audit | Compute I, A, D per component; flag high D and rising-D trends |
| Tempted to design the full module decomposition up front | Don't — component structure evolves with the code; it maps buildability, not features |

