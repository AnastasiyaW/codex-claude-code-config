---
name: refactoring-safely
description: >
  Change the structure of code that already exists without changing what it does:
  smells as triggers, the named transformations (extract/inline, move feature, organise
  data, simplify conditionals), and above all the workflow that makes it safe —
  characterization tests first, one transformation at a time, green between every step.
  Use when a file or function is already too large; when asked to "split this module",
  "extract this", "break up main.py", "clean up this legacy code", "reduce coupling
  here"; when a shape advisory fires on a grown file; or before any restructuring of
  code that has users. Do NOT use to decide the target layout of a NEW project (use
  architecture-first), for unit-level naming and function quality in code you are
  writing fresh (use code-complexity), for capacity or storage decisions (use
  system-and-data-design), or to strip over-engineering on request (use lean-code). This
  is the transformation with a net; deciding WHERE things should end up is a different
  question, and doing both at once is how refactors lose behaviour.
---

# Refactoring safely — changing shape without changing behaviour

Refactoring is a behaviour-preserving transformation. If behaviour changed, that was not
a refactor, it was a rewrite with optimistic branding — and the reason large restructures
fail is almost always that the two were done in one step.

## The rule that makes the rest work

**Never restructure and change behaviour in the same commit.** Alternate deliberately:
refactor (green → green, no behaviour change), then change behaviour (with a new test).
When both happen at once, a failing test cannot tell you which half broke it.

## Before touching anything: the net

Legacy code is code without tests, regardless of age. So:

1. **Characterization tests first.** Not tests of what it *should* do — tests of what it
   *does*, including behaviour you consider wrong. Their job is to detect change, not to
   judge it. Wrong-but-tested behaviour gets fixed later, on purpose, in its own commit.
2. **Cover the seams you are about to cut**, not the whole file. Coverage of the region
   under the knife is what matters.
3. **Confirm they fail when you break something.** A characterization test that passes
   against deliberately broken code is worse than none — run that check once.
4. **Know how to revert.** Small commits, one transformation each.

## Smells, and what each one actually indicates

| Smell | Underlying problem | Transformation |
|---|---|---|
| Long function | Several jobs in one scope | Extract function, split by level of abstraction |
| Large module | Several reasons to change in one file | Move features into modules that own their state |
| Long parameter list | A missing object, or a hidden mode flag | Introduce parameter object; split by behaviour |
| Feature envy | Method uses another object's data more than its own | Move method to where the data lives |
| Shotgun surgery | One decision spread across files | Gather it into one owner |
| Divergent change | One file changing for unrelated reasons | Split by reason to change |
| Primitive obsession | A concept represented as a string or dict everywhere | Introduce a type; put its rules with it |
| Duplicated *decision* | One rule expressed in several places | Extract and give it one home |

Duplicated *text* expressing unrelated decisions is not a smell. Merging it couples
things that had no reason to change together.

## The sequence for a large module

Order matters more than technique, and this order is what keeps each step small:

1. **Constants and pure helpers out first.** They have no state and no dependents to
   break, and they are what every future slice would otherwise import from the old file.
2. **Then the state nobody else touches.** Background machinery, caches and locks used
   by one area move with that area, taking their invariants along.
3. **Then whole vertical slices** — one feature's handlers plus the state it owns. A
   slice that takes its own state with it is a clean cut; a slice that leaves state
   behind produces "modules" that still need the old file.
4. **The long tail last.** Single functions with no clear home go where they are used,
   or into one honestly-named remainder. Splitting them first is motion without benefit.
5. **Delete the old path only after the new one carries traffic**, and only once.

At each step: green before, green after, one commit.

## Concurrency: the part that bites

Hand-rolled locks and module-level mutable state do not survive naive moves. Before
moving anything guarded:

- Write down the invariant the lock protects, in words, before the move.
- Move the state and its lock together, into the module that owns them. State in one
  module and its lock in another is a bug waiting for load.
- If two areas share one lock, that is the coupling — resolve it before splitting, not
  during.

## References — load on demand

- `references/refactoring-patterns/smell-catalog.md` — the full catalogue with triggers
- `references/refactoring-patterns/refactoring-workflow.md` — safe workflow and rollback
- `references/refactoring-patterns/composing-methods.md` — extract, inline, replace temp
- `references/refactoring-patterns/moving-features.md` — move method/field, hide delegate
- `references/refactoring-patterns/organizing-data.md` — replace primitive, encapsulate
- `references/refactoring-patterns/simplifying-conditionals.md` — guard clauses, polymorphism
- `*-original.md` — the source skill's own framework prose, kept verbatim

## Gotchas

- **The big-bang restructure.** A branch that reorganises everything cannot be reviewed,
  cannot be bisected, and conflicts with every parallel session. Small steps on main
  beat a heroic branch, every time.
- **Refactoring under a shared file.** If other sessions or teammates are editing the
  same file right now, the cut is a coordinated operation, not a background tidy. Check
  first; conflicts here lose work rather than just time.
- **"Modular" that still imports the old module.** If every new module imports the file
  you split, you moved text, not boundaries. Constants and shared state first — that is
  what step 1 and 2 are for.
- **Renaming during a move.** Move, commit, then rename. A diff that does both is
  unreviewable and hides accidental behaviour changes.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Tests broke and you cannot tell why | Behaviour change smuggled into a structural commit | Revert; redo as two commits |
| Extracted function needs six parameters | The cut is in the wrong place | Cut along the data, not along the line count |
| Circular import after the split | Two new modules both own part of one concept | Extract the shared concept into a third |
| Race appears only after the move | State and its lock ended up in different modules | Move them together; re-state the invariant |
