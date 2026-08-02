# Nine skills, one skeleton, and nobody reaching for them

A repository can contain the right knowledge and still never apply it. This is a note
about how that happened here, what the shape of the failure was, and what actually
fixed it — because "the agent should have known better" is not a fix, and it was not
true either.

## The symptom

A working site's backend had grown to one module of 8,823 lines: 190 route handlers,
336 top-level definitions, one class, a 488-line function, and 13 module-level mutable
objects — six of them hand-rolled locks — shared by everything in the file.

Nobody wrote that on purpose. It arrived through edits that were each individually the
smallest correct change.

## The first thing that was not the cause

The obvious diagnosis is a missing skill. It was wrong: there were nine architecture
skills sitting in the catalogue, covering layering, domain modelling, complexity,
refactoring, data systems and the pragmatic meta-rules.

The measured situation was this:

| | Count |
|---|---|
| Architecture skills present | 9 |
| Reachable from the keyword router | **1** — the one arguing for *less* code |
| Skills claiming "AUTO-APPLY on ANY coding process" in their own description | 1 |
| Mechanisms that made that claim true | **0** |

A skill's description is read by a model deciding what to load. Writing AUTO-APPLY in it
is a request, not a wire. Nothing enforced it, and under task pressure a request loses
to the task.

## The direction nobody chose

The harness had exactly one permanent pressure on the shape of code: an advisory that
fires on sizeable additions and asks *"is this the smallest solution?"*. It is a good
advisory. It had no counterpart.

One-sided pressure has a direction, and here is the mechanism:

> Adding a 40-line handler to an 8,000-line module is a **smaller diff** than creating a
> module, wiring a router, and moving three helpers across.

So the minimal-diff heuristic, applied honestly once per session, is a ratchet toward
monoliths. Every individual application of it is defensible. The cumulative question —
*does this file still have one reason to change?* — was asked by nothing and no one.

The fix is not to argue for bigger diffs. It is a second advisory that fires on the
shape of the **whole file** after an edit, never on the size of the edit, because the
size of the edit is exactly what looks fine every single time.

Both stay advisory. A blocking shape gate would fight task completion the same way a
blocking minimalism gate would, and blanket prompt pressure measurably costs completion
rates. Two opposing advisories with the judgement left in the middle is the honest
arrangement.

## Why nine skills behaved like none

Eight of the nine shared one skeleton — *Core Principle, Scoring, Framework,* six
numbered sections — because each was a distillation of one book: Martin, Ousterhout,
Evans, Fowler, Kleppmann, Hunt & Thomas.

That organising principle is invisible in use. Nobody has ever thought *"I need the
Ousterhout view of this."* People think *"I am starting something"*, *"will this hold
under load"*, *"this function is unreadable"*, *"this file is too big now."*

The consequence was measurable as competition. Across the nine descriptions, five
competed for the word *design*, four for *architecture*, four for *refactoring*, four
for *quality*. A model choosing among them has no discriminating signal, so it reaches
for whichever the prompt's surface wording happens to favour — or, more often, for none.

## Regrouping by the moment, not the author

Four skills, cut by *when you need them*:

| Skill | The moment |
|---|---|
| `architecture-first` | Before the first file: what the modules are, which way dependencies point, who owns which state |
| `system-and-data-design` | Will it hold, and where does data live: estimate first, then storage engines, replication, partitioning, consistency |
| `code-complexity` | While a unit is being written: deep modules, information hiding, honest names, error paths that do not swallow |
| `refactoring-safely` | When it is already too big: characterization tests first, one transformation per commit |

The merge criterion was topical coherence, **not** vocabulary overlap. Two bodies of
knowledge with little shared vocabulary can still be one decision — layering and domain
modelling read very differently and answer the same question: *what are the modules?*
Merging by overlap would have kept them apart and merged the wrong things.

### What it cost and what it bought

The merge is at the **entry point only**. Every reference file of every original is
carried into its merged skill, namespaced by origin, and each original entry document is
kept verbatim alongside. Verified file by file before anything was removed.

| | Before | After |
|---|---:|---:|
| Entry text loaded when a trigger fires | ~20,900 words across 9 competing descriptions | **4,386** across 4 that do not overlap |
| Depth, loaded on demand | 133,290 words | **133,290** — unchanged |

Denser inside, fewer to choose between, nothing lost. The router now discriminates by
moment; 19 cases through the real hook confirm each phrasing reaches exactly one of the
four, with a negative control that must route nowhere.

## The three lessons worth taking elsewhere

**A claim in a description is not a mechanism.** If a document says it applies
automatically, something outside the document has to make that true. Otherwise it is a
statement of intent competing with a task, and the task wins.

**Check the direction of your advisories, not just their correctness.** Every guardrail
here was individually right. Their *sum* had a direction nobody had chosen, and the
direction was visible only in the accumulated artefact, months later.

**Organise knowledge by the moment of use.** Filing by source is natural for whoever
writes the collection and useless for whoever needs it. The test is whether someone in
the middle of a decision can name which entry they want — if they have to read four to
find out, the filing is wrong regardless of how good the contents are.
