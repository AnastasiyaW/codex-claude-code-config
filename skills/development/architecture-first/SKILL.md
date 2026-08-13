---
name: architecture-first
description: >
  Decide the shape BEFORE the first file, and keep the boundaries honest afterwards:
  what the modules are, which way dependencies point, where state is owned, and what
  each module is allowed to know. Merges the layering rules (dependency rule, SOLID,
  component cohesion, Humble Object, entities vs use cases, frameworks-and-DB-as-details)
  with domain boundaries (ubiquitous language, bounded contexts, aggregates, domain
  events, repositories). Use when starting a project, service, site, API or new
  subsystem; when adding a feature that does not obviously belong to an existing module;
  when asked "where should this live", "how do we structure this", "what are the
  modules"; when writing an ARCHITECTURE.md or an ADR; when a dependency points the
  wrong way or a circular import appears. Do NOT use for a one-file script or a
  throwaway experiment, for a bug fix inside an existing seam, for word-level naming and
  function shape (use code-complexity), for splitting a module that is ALREADY too large
  (use refactoring-safely), or for capacity, storage and scaling decisions (use
  system-and-data-design). This decides where code LIVES; it is not a licence to add
  layers the project has not earned.
---

# Architecture first — the shape before the first file

Most bad structure is not a bad decision. It is an absent one: code goes where the
smallest diff puts it, and the smallest diff is always "next to the last thing". This
skill exists to make the layout an explicit, cheap, early decision.

## Scope guard — read first

Match the ceremony to the problem. Over-applying this is its own failure mode.

| Situation | What this skill asks of you |
|---|---|
| Script, spike, one file, throwaway | Nothing. Skip. |
| One module, <500 lines, one reason to change | Name the module and its one job. Stop. |
| Service / site / API, several concerns | The full pre-code checklist below. |
| Multiple teams or deployables, shared domain | Checklist + bounded-context map + one ADR per boundary |
| Multi-stage work or external release prerequisite | Checklist + a small stage map before the first implementation boundary |

## The one law

**Dependencies point inward, toward policy.** Business rules must not import the web
framework, the ORM, the queue, or the file layout. The reverse is required.

Violating it silently is the failure — a violation that is written down, with the reason
and the cost, is a decision. A violation nobody named is erosion.

Practical test: *could this module be exercised by a test with no network, no database
and no framework?* If not, something outer leaked inward.

## Pre-code checklist — before the first file

1. **Name the modules by reason to change**, not by technical layer. `queue`, `billing`,
   `catalog` — not `controllers`, `models`, `utils`. A module that changes for two
   unrelated reasons is two modules.
2. **Say what each module owns.** Especially state: every piece of mutable state has
   exactly one owning module, and everyone else asks that module. Module-level mutable
   state shared across features is the coupling that later makes a split expensive.
3. **Draw the dependency arrows.** Any cycle is a design bug, not a build inconvenience.
   Any arrow from domain to framework is inverted — fix it with an interface owned by
   the inner side.
4. **Establish the ubiquitous language.** One term, one meaning, in code and in speech.
   If the same word means different things in two places, you have found a bounded
   context boundary — draw it there.
5. **Define the aggregates.** What must be consistent in one step, and what may lag.
   Transaction boundaries follow this, not the other way round.
6. **Write one vertical slice end-to-end** — UI to store to test — before broadening.
   A slice that works proves the seams; six half-built layers prove nothing.
7. **Record it.** One page: modules, ownership, data flow, external systems. Plus one
   short ADR per decision that was genuinely a choice (context, options, decision,
   consequences). Both live in git, next to the code.
8. **Name the promotion boundaries.** When one verified result becomes the input to
   another stage, name its contract, inputs, output, and invalidation keys before
   implementation. A missing signer, VM, account, or remote service is a future
   `BLOCKED` stage, not a reason to keep reopening already-proven code.

## Stage contracts - when proof becomes an input

For multi-stage work, architecture includes delivery boundaries as well as module
boundaries. Keep these states separate:

- `VERIFIED`: the scoped behavior passed at one exact revision.
- `SEALED`: the verified scope has an immutable receipt and may be consumed by a
  following stage.
- `BLOCKED`: a named external prerequisite is absent; upstream proof remains valid.
- `SUPERSEDED`: a contract, source, or input digest changed, so a successor must be
  verified instead of editing history.

The stage map is deliberately smaller than a release plan. For each boundary, name
the owning scope, frozen contract, inputs, output, and what invalidates it. Use the
machine-readable ledger only when there is a real hand-off between stages:
`../proof-verify/references/proven-stage-contracts.md`. Do not add it to a one-file
change merely because the word "stage" exists.

## Review checklist — once code exists

- Does any inner module import an outer one? Name it or fix it.
- Is there module-level mutable state touched by more than one feature?
- Does one file hold routes/handlers for more than one reason to change?
- Are there two names for the same concept, or one name for two?
- Can each module's tests run without the framework?
- Does the ARCHITECTURE.md still describe what is actually there?

## Fast decision table

| Question | Default answer |
|---|---|
| Layer folders or feature folders? | Feature (vertical slices). Layer folders scatter one change across four directories. |
| Where does validation live? | Input shape at the edge; business rules inside. Never only at the edge. |
| Interface for a single implementation? | No — until a second caller or a test double actually needs it. |
| Microservices? | Not yet. Modular monolith with real boundaries first; extract when a module needs its own deploy or scaling. |
| Where does the ORM model live? | Outer. The domain object is not the row. |
| Shared "utils" module? | A smell. Utils is where things go when nobody decided; name the reason instead. |

## References — load on demand

- `references/clean-architecture/boundaries-and-layers.md` — boundaries, Humble Object
- `references/clean-architecture/solid-and-components.md` — SOLID applied correctly, REP/CCP/CRP, ADP/SDP/SAP
- `references/clean-architecture/details-and-code-organization.md` — DB/web/frameworks as details
- `references/clean-architecture/python-implementation.md` — entities, use cases, repositories, wiring
- `references/domain-driven-design/bounded-contexts.md` — context mapping
- `references/domain-driven-design/ubiquitous-language.md` — one term, one meaning
- `references/domain-driven-design/building-blocks.md` — entities, value objects, aggregates
- `references/domain-driven-design/domain-events.md`, `repositories-factories.md`, `strategic-design.md`
- `*-original.md` — the source skills' own framework prose, kept verbatim

## Gotchas

- **"We'll structure it later."** Later costs more per caller, and callers only grow. The
  cheapest moment is before the first file; the second cheapest is now.
- **Ceremony as architecture.** Four layers around a CRUD endpoint is not architecture,
  it is cost. The scope guard above exists to stop this.
- **Folders instead of boundaries.** Moving files without changing who imports whom
  changes nothing. The arrows are the architecture; folders only display it.
- **The domain importing the framework "just for a type".** That is the whole violation,
  arriving politely.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Circular import | Two modules both own part of one concept | Extract the shared concept into a third module both depend on |
| One change touches six files across four folders | Layer folders, not feature folders | Re-cut by feature; keep the change local |
| Tests need a live database to assert a rule | Rule lives outside the domain | Move the rule inward, inject the store |
| Nobody can say which module owns X | Nobody decided | Decide now, write it in ARCHITECTURE.md, move the state |
