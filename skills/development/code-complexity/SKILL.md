---
name: code-complexity
description: >
  Keep each unit comprehensible while the code grows: deep modules over shallow ones,
  information hiding, honest names, small functions with one job, error handling that
  does not lose the error, DRY and orthogonality, design by contract, and not leaving
  broken windows. Merges module-complexity management with naming/function/error-handling
  discipline and the pragmatic meta-rules. Use when writing or reviewing a function,
  class or module; when an interface feels wide, a class feels shallow, or a change in
  one place forces edits in three; when the user says "this is hard to follow", "clean
  this up", "review this code", "is this a good abstraction", "too many parameters",
  "pass-through method", "duplicated logic", or asks about naming, comments, error
  handling or unit tests. Do NOT use to decide where a new module LIVES or which modules
  exist (use architecture-first), to plan capacity or storage (use system-and-data-design),
  to execute a named transformation on a file that is already too large (use
  refactoring-safely), or to strip over-engineering on request (use lean-code). This
  makes a unit comprehensible; it does not draw the system's boundaries.
---

# Code complexity — keeping a unit comprehensible

Complexity is not how clever the code is. It is how much you must hold in your head to
change one line safely. It accumulates by increments that each look acceptable, which is
why it is never one bad commit's fault and always everyone's problem.

## The two symptoms worth memorising

**Change amplification** — one decision, many edits. If changing a timeout means editing
five files, that decision was not encapsulated anywhere.

**Cognitive load** — how much you must know to be safe. A function that is correct only
if you know that the caller already took a lock has exported its complexity to everyone
who reads it.

Both are properties of the *interface*, not the implementation. Which gives the rule:

## Deep over shallow

A module's value is `functionality it provides ÷ interface you must learn`. Deep = small
interface, substantial behaviour behind it. Shallow = large interface, little behind it.

- A pass-through method that only calls one other method with the same arguments is
  negative value: it adds an interface without adding behaviour.
- "One class per concept, many tiny classes" is not automatically good. Many shallow
  classes cost more total interface than a few deep ones.
- The right question is never "is this class small?" but "how much do I need to know to
  use it?"

## Information hiding — and its inverse

Every design decision that might change should be known to exactly one module. The
inverse — **information leakage** — is when a decision shows up in two places: a file
format known to both the reader and the writer, a status string parsed by three modules,
a lock the caller has to remember.

Test: *if this decision changed, how many files would I edit?* More than one is leakage.

## Names, functions, errors — the unit level

- **Names**: a name that needs a comment to explain it is the wrong name. If you cannot
  name it, you do not yet know what it does — that is information, not a naming problem.
- **Functions**: one job, one level of abstraction, few parameters. Three or more
  booleans in a signature is a sign that several functions are hiding in one.
- **Comments**: comment the *why* and the constraint, never the *what*. A comment that
  restates the code rots the moment the code changes. A comment that records a ceiling
  or a reason is the most durable thing in the file.
- **Errors**: define them out of existence where you can (an operation that cannot fail
  needs no error path); where you cannot, fail loudly and early. Silently swallowing is
  the failure that looks like success — the most expensive kind.
- **Tests**: one assertion of behaviour per test, named for the behaviour. A test that
  needs a comment to say what it proves is not proving it clearly.

## The pragmatic meta-rules

- **DRY is about knowledge, not text.** Two identical lines expressing two unrelated
  decisions are not duplication. One decision expressed in two places is, even if the
  code looks different.
- **Orthogonality**: changing one thing should not move another. If it does, they are
  coupled through something you have not named.
- **Design by contract**: state preconditions and invariants, and assert them. An
  assertion is executable documentation that cannot rot.
- **Broken windows**: one tolerated mess licenses the next. Fix it while it is one.
- **Tracer bullets**: build one thin end-to-end path first, then widen. It proves the
  seams; a stack of half-built layers proves nothing.
- **Reversibility**: prefer decisions that can be undone. There are fewer final answers
  than the design meeting suggests.

## Review pass — in this order

1. Does any interface require knowledge it did not give you? (leakage)
2. Would a change to one decision edit more than one file? (amplification)
3. Any pass-through methods, or classes whose interface is most of their content?
4. Any name that needs its comment?
5. Any error path that continues on failure without saying so?
6. Any duplicated *decision* — not duplicated text?

## References — load on demand

- `references/software-design-philosophy/deep-modules.md`, `information-hiding.md`,
  `complexity-symptoms.md`, `general-vs-special.md`, `strategic-programming.md`,
  `comments-as-design.md`
- `references/clean-code/naming-conventions.md`, `functions-and-methods.md`,
  `error-handling.md`, `testing-principles.md`, `comments-formatting.md`,
  `code-smells.md`
- `references/pragmatic-programmer/dry-orthogonality.md`, `contracts-assertions.md`,
  `tracer-bullets.md`, `reversibility.md`, `broken-windows.md`,
  `estimation-portfolio.md`
- `*-original.md` — the source skills' own framework prose, kept verbatim

## Gotchas

- **Small is not simple.** Splitting a deep module into six shallow ones raises total
  interface and lowers comprehensibility while looking like progress.
- **Abstraction without a second caller.** An interface with one implementation and no
  test double is a guess about the future priced as complexity today.
- **DRY applied to text.** Merging two coincidentally-identical blocks couples two things
  that had no reason to change together, and the next change breaks one of them.
- **"Clean" as a rewrite.** Restructuring without a behaviour test is not cleaning, it is
  gambling — see refactoring-safely for the transformation with a net.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Everyone keeps re-reading the same function to use it | Shallow interface, deep obligations | Move the obligation inside; make the caller's job smaller |
| A bug fix in one module breaks another | Leaked decision or hidden coupling | Find the shared knowledge, give it one owner |
| Tests pass and production fails | An error path that continues silently | Make it loud; assert the precondition |
| Signature grew a fourth boolean | Several functions in a trench coat | Split by behaviour, not by parameter |
