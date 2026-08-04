# The form was available, so it was taken for the content

A day of harness work produced one failure shape in six different materials, including
three times inside the tool built to catch it. This note records the shape, what the
field already calls it, and what closed each instance — because naming it was the part
that kept not working.

## The shape

> A form is available, and its availability is taken for the presence of content.

Concretely, the three that showed up first:

- **an empty answer that does not raise.** A check that matched nothing prints "clean",
  and the reader cannot tell that from a check that matched everything and found nothing
  wrong.
- **a repeat that never pins its input.** The loop looks controlled — same command, same
  target, three times — while the variable underneath moved, so none of the runs is
  evidence about the others.
- **a retelling that reads as a measurement.** Another agent's report becomes "verified"
  by being passed along, unless someone says which of the two it is.

Different materials, one mechanism: in each case the *shape* of a result was present and
was accepted in place of the result.

## It has a name, and three established answers

Worth looking up before building, which is not what happened first.

**Formal verification calls it vacuity.** A property passes vacuously when its
precondition never occurred. The canonical example from the IBM Haifa work is our exact
shape: *"every request is eventually followed by a grant"* holds trivially in a system
where requests are never sent. Their answer is not a stronger assertion but a demand for
an **interesting witness** — show a run in which the precondition actually held.

**pytest gives "no tests collected" its own exit code**, rather than folding it into
success, on the stated ground that a project must decide that policy deliberately instead
of hiding a collection mistake.

**ESLint made an unmatched glob fatal in v5.** The rationale is the same and blunter: if
your pattern matched no files, the likely cause is a wrong path or a typo, and reporting
success for it hides the mistake behind a green line. The permissive behaviour exists —
as a named flag you have to ask for.

**Mutation testing** answers "does this check have content" not by reading the check but
by breaking the subject on purpose and seeing whether the check notices. A surviving
mutant is a test with the form of a test and none of its content.

Four independent fields, one conclusion: **empty is its own outcome, and a pass must be
able to point at what it was based on.**

## What closed each instance

**Empty answers.** A reporting helper that cannot render a pass on zero input — empty
exits with its own code, distinct from a finding's, because a real finding and a
misconfigured checker need different responses and collapsing them is how a broken path
gets "fixed" by deleting whatever it could not find. Then a probe that runs every checker
twice, against an empty tree and a populated copy, and requires the two answers to differ.
One probe tests vacuity; two test for a witness.

**Unpinned repeats.** A guard that remembers attempts: advisory on the third failed
attempt at one target, blocking on the fourth, cleared by any read since the last failure.
The block is lifted by exactly the action that would have solved it three attempts
earlier, which is why blocking here does not fight completion — interrupting the loop *is*
the way forward. The key is deliberately coarse, because changing one flag is what the
loop consists of.

**Retellings.** A high-risk change with green tests now also needs one recorded
independent review. More tests of our own kind is not a deeper check: a suite that never
exercised the boundary you moved passes exactly as green after you move it. What was
missing is independence, not volume. Evidence is keyed to a hash of the changed paths, so
it cannot be earned once and coasted on.

## The instructive part: the fix had the defect, three times

This is the half worth keeping, because it is the part that repeats.

**The probe printed PASS with half its candidates untested.** Eight of sixteen took no
root argument, so they could not be aimed at an empty tree — and "untested" was counted
as fine. The exact defect, one level up, inside the checker for that defect. Untestable is
now its own outcome, and *incomplete is not pass*.

**It judged by words.** It looked for "clean" in the output and for a phrase admitting
emptiness. A checker whose count sits one level deeper, or which words its emptiness
differently, walked straight through. The verdict is now the exit code — structural, and
impossible to phrase around. That reclassified six checkers from clean to vacuous where
the text version had reported zero.

**Its envelope-stripper threw away the payload.** Two probe trees have different paths, so
a checker that merely echoes its root produces two different strings while having looked
at nothing — the wrapper counted as the answer. The comparison now strips the envelope
first. But the first cut of that normalised digits along with paths, which discarded the
count: `found 0 items` and `found 7 items` compared equal, so a checker reporting nothing
looked exactly like one reporting seven. The same defect, applied to the other half of the
string, inside the fix for it.

Each was caught the same way, and not by reading the diff: by running the thing on a real
input and looking at what came back. The third was caught only because the helper was
tested directly rather than inferred from an unchanged total — an unchanged number means
either "nothing to reclassify" or "the check did not run", and those are not the same.

## Two corrections that cost more than the bugs

**Two categories, not one.** After switching to exit codes, six checkers were flagged.
Four of the six were wrong: a generator or a cleaner has no pass/fail contract, so
"exit 0, nothing to do" is correct for them. A report that is wrong about most of what it
says trains its reader to skip it — the same failure arriving as noise instead of silence.
Producers got their own finding, and it is a real one: writing an artifact from an empty
input. A catalogue built from nothing is not an empty catalogue, it is a lie with a
filename.

**Do not invent a rule the field does not share.** The obvious next step was "a generator
must never write empty output". That is not a general practice — CMake keeps empty outputs
so N-to-M mappings stay consistent, and PostgreSQL's generators deliberately avoid
rewriting unchanged files. So the rule was scoped to the case actually supported: zero
inputs means you were aimed at the wrong tree, which is precisely ESLint's rationale, with
the same named opt-out.

## What generalises

- **Empty is an outcome, not a success.** Give it its own exit code and decide the policy
  on purpose.
- **A pass should carry what it was based on.** Not as documentation — as something the
  code cannot print without.
- **Check the checker on an input it should fail.** Presence of a guard is not evidence
  the guard fires; the only proof is a case where it does.
- **An unchanged number is not a result.** It means the check found nothing *or* did not
  run, and distinguishing those is the whole job.
