# Output legibility: making agent output cheap to read

Agents now write more text than people can read. The bottleneck has moved from
producing output to understanding it. Andrej Karpathy's post of 2 October 2026
ranks four ways to make output easier to absorb. Each one is more effort than
the last:

1. **Text in ASD-STE100 style** (Simplified Technical English, the aerospace
   controlled language).
2. **A diagram** instead of prose.
3. **An HTML page** you can explore interactively.
4. **A custom explainer video.**

Treat this as a ladder: pick the lowest rung that makes the answer obvious. A
review comment usually needs rung 1. An architecture change usually needs rung 2.
A data-heavy comparison earns rung 3.

## Rung 1 without the licensed dictionary

The full standard has a controlled dictionary of about 900 approved words and
dozens of rules. That dictionary is copyrighted, so a public tool cannot ship
it, and models do not know it reliably. Asking for "strict STE100" yields
imitation, not conformance. The post itself suggests aiming for about 80%
adherence. Fact-checks also found that the popular one-page cheat sheet
misstates parts of the standard.

Keep the two rules that carry most of the value and need no dictionary:

- **One concept, one term.** If the project says `worker`, every sentence says
  `worker` — not `handler`, `executor` or `processor`. Synonyms for variety
  make a technical reader wonder whether these are different things.
- **Short sentences.** STE Issue 9 caps procedural sentences at 20 words and
  descriptive ones at 25. One instruction per step.

Do not apply rung 1 where it removes meaning. Reviews and design notes need the
*why*: risks, caveats, rejected alternatives. Short sentences are fine; deleting
the reasons is not.

A prompt line that works better than "write in STE100":

```text
Write in about 80% ASD-STE100 style: no preamble, sentences under 25 words, one
action per numbered step, and use only these terms for these concepts: <glossary>.
Keep the reasons and risks; put each on its own line.
```

## Make it a check, not a hope

A prompt drifts on the next call, and CI cannot fail a prompt. Give the project a
glossary file and check the output mechanically with
[`scripts/term_drift_check.py`](../scripts/term_drift_check.py):

```json
{
  "max_words": 25,
  "terms": {
    "воркер": ["обработчик*", "исполнител*"],
    "worker": ["handler*", "executor*"]
  }
}
```

`stem*` matches every inflection, which is why the check also works in Russian
and other inflected languages; STE itself is a standard for English.
Fenced code blocks, inline code, URLs and HTML comments are skipped. Indented
code blocks are still read as prose, so fence them. Table rows are checked for
terms but not for sentence length. An unclosed fence is a `2`, not a pass.

```bash
python scripts/term_drift_check.py --glossary .agent/glossary.json REPORT.md
python scripts/term_drift_check.py --self-test
```

Exit codes follow the three-state contract: `0` clean, `1` findings, `2` the check
was not performed. A `2` is never green. These inputs give `2`:

- a missing, invalid or no-op glossary, or unknown glossary keys;
- non-UTF-8 or empty input;
- an unclosed fence, or no prose left to check.

The self-test has must-fail and must-pass controls:

- must fail: an inflected synonym, an English synonym, a long sentence, a
  wrapped long sentence, a mismatched fence marker;
- must pass: the canonical term, code blocks, list items, a heading, a table row.

To mention a forbidden synonym on purpose, put it in backticks. Mutation check:
six deliberate breaks of the detection logic each turn the self-test red.

To enforce it in a project, run it in CI on generated docs or from a
project-level Stop hook on the agent's final message. Keep it advisory until the
glossary is stable, because a wrong glossary entry produces noise.

## Existing tools

For English conformance to the full standard, use a dedicated linter instead of
this checker: OneRead (`https://github.com/zorost/oneread`) or Stelint
(`https://pypi.org/project/stelint/`). Prompt-only skills, such as
`https://github.com/nuelcyoung/asd-ste100`, are useful for drafting but do not
enforce anything.

## Sources

- Karpathy's ranking and a fact-check of the cheat sheet:
  `https://max.nardit.com/articles/karpathy-understanding-llm-outputs`
- ASD-STE100 term checker and its dictionary licensing notes:
  `https://simplified-english.co.uk/`
