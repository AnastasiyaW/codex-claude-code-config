---
name: humanize-english
description: |
  Edit English drafts for clear, natural language while preserving facts, uncertainty,
  technical meaning, citations and genre. Use when: humanize this text, remove AI-style
  filler, improve English prose, or edit an English article before publication.
  Not an authorship detector or a promise to bypass one. For Russian use
  humanize-russian; for thesis/evidence and structure use article-structure-review.
metadata:
  version: "2.0.0"
  reviewed: "2026-09-06"
---

# Clear, Natural English Editing

Improve the reader's understanding, not a detector score. A good reference can
have repeated terminology, regular tables, definitions and no anecdote.
Keep the user's intended voice and the destination's format.

## Facts Are Not Style Material

- Preserve supplied numbers, units, dates, versions, names, citations, negation,
  uncertainty and claim scope. Do not silently update a historical date.
- Never invent a count, quote, interview, personal experience, experiment,
  failure, comparison or source to make prose more vivid.
- Add specificity only when the supporting evidence supplies it. If no
  measurement exists, retain uncertainty or remove an unsupported claim.
  An unsupplied number is not an improvement over a vague quantity.
- Label illustrative scenarios as hypothetical. Do not present them as a real
  case study or treat their invented values as proof of a product claim.
- Preserve identifiers, executable code and technical obligations. Words such
  as may, must, can and will are not interchangeable style alternatives.
- Reuse provided facts without asking the user to repeat them. Research a
  material factual gap when research is in scope; otherwise identify the gap
  without manufacturing an answer or blocking supported edits.

## Match the Genre

| Genre | Useful editing | Avoid forcing |
|---|---|---|
| technical reference | exact terms, clear conditions, scannable structure | slang, story openings, rhetorical questions, sales CTA |
| explanation/tutorial | prerequisites and action/result sequence | an untested command described as verified |
| analysis | separate observation, inference and limits | stronger causal claims than the evidence supports |
| personal narrative | the author's supplied experiences and voice | invented first-person testimony |
| marketing | a supported benefit and relevant next action | fabricated testimonials, percentages or guarantees |

Contractions, fragments, humour, analogies and direct address are options, not
quotas. Use them when they fit the audience and improve comprehension.
Parallel lists and consistent terminology can be desirable in documentation.

## Editing Procedure

1. Identify the reader's task, genre, source material and protected facts from
   the existing request and draft. Do not add an unnecessary intake questionnaire.
2. Remove empty intensifiers and duplicated ideas. Use direct verbs when meaning
   is preserved; keep connectors that express real causality or contrast.
3. Clarify who acts, on what, under which conditions and with what result.
   Do not supply a result that the source does not establish.
4. Fix awkward rhythm where it hinders reading. Do not maximize variation,
   enforce a paragraph pattern or replace terms to appear less predictable.
5. Compare input and output for semantic changes. Check quantities with their
   units, denominator, time frame and uncertainty, not just the numeral.
6. Return the edited text and any necessary factual caveat. Once the edit is
   sufficient, continue the remaining requested publication workflow rather
   than starting another stylistic pass automatically.

## Examples: Same Facts, Clearer Prose

| Supplied text | Faithful edit |
|---|---|
| In order to load the file, the user must select Open. | To load the file, select Open. |
| The tool may reduce processing time; no benchmark is available. | The tool may save processing time, but no benchmark is available. |
| Some testers reported failures. The sample size was not recorded. | Some testers reported failures; the sample size was not recorded. |
| On 2026-09-01, 12 of 40 runs failed with version 2.1. | With version 2.1, 12 of 40 runs failed on 2026-09-01. |

These are editing fixtures, not results from a deployed product. Unknown sample
size stays unknown; a date, denominator and version do not disappear for fluency.

## Verification

- Every changed factual assertion still maps to the supplied material or a
  source actually checked for this task.
- Conditions, uncertainty, negatives, numbers, units, dates, versions and code
  are preserved unless an evidence-backed factual correction was requested.
- The result helps its intended reader without an unrequested genre change.
- No invented testimony or detector-evasion claim was added.

A no-change verdict is valid for an already clear passage. Do not add numbers,
questions, opinions, deliberate errors or fake admissions to satisfy a score.

## Gotchas

- **Detector score as evidence:** it establishes neither authorship nor factual
  accuracy. Do not promise an undetectable edit.
- **Replacing every vague quantity:** guessing a plausible percentage fabricates
  evidence when the sample size is unknown.
- **Forced informality:** slang can make a reference harder to understand,
  particularly for readers using English as an additional language.
- **Synonym churn:** repeating a technical term is safer than creating a false
  distinction through alternate names.
- **Example contamination:** a skill example is not an event that happened to
  the user or author.

## Troubleshooting

| Symptom | Check | Correction |
|---|---|---|
| polished but unsupported claim | source scope and conditions | restore supported meaning or remove the claim |
| bureaucratic phrasing | action and actor | use a direct sentence without changing obligations |
| repetitive text | repeated meaning versus necessary terms | cut redundancy, keep precise terminology |
| reference sounds like an advertisement | requested genre | remove promotion and invented narrative |
| detector flags the passage | actual writing and detector limitations | repair evidenced defects, not a guessed authorship score |

## Sources and Maintenance

Reviewed 2026-09-06. Owner: the existing writing-skill maintainers. Change through
canonical Git, focused before/after fixtures, independent review and the supported
installer; retain the prior revision and installation backup for rollback.
Refresh sources when guidance changes or a factual/genre regression is observed,
not by automatically rewriting working prose on a schedule.

- [Developer documentation voice and tone](https://developers.google.com/style/tone),
  updated 2026-05-27: clarity and audience matter more than forced informality.
- [GPT detectors are biased against non-native English writers](https://arxiv.org/abs/2304.02819),
  revised 2023-07-10: limitations of the evaluated detectors, not a test of every
  current detector or a guarantee about any individual passage.
- [Excess vocabulary in biomedical publications](https://arxiv.org/abs/2406.07016),
  revised 2025-07-03: corpus-level biomedical analysis, not an individual-author
  test or a prescriptive word blacklist.
