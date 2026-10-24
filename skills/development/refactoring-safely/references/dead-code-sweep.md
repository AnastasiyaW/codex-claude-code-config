# Dead-code and stale-flag sweep with an agent

A sweep deletes code, so a refactor's safety net does not help. Nothing fails when
unreachable code disappears. Nothing fails either when you are wrong about it
being unreachable. The evidence comes from production, not from the
diff.

Source: OpenAI, "Maintaining software with the GPT-6 family"
(`https://developers.openai.com/blog/maintaining-software-with-the-gpt-6-family`).
Five engineers working part-time for two weeks merged 1,400+ PRs and deleted
800k+ lines. One container image shrank 48%, and median CI time fell from about
10 to 4.5 minutes. The method below is that process restated as rules.

## 1. Audit first, read-only

The audit changes nothing: no live config, no flag service, no deploy. Its output
is a report. Each candidate gets:

| Evidence | What proves it |
|---|---|
| Not reached | Production profiling/telemetry, not only static search |
| Not referenced | Call sites, including indirect use: enums, wrappers, aliases, schemas, dynamically built names, other services |
| Flag state | The live flag/experiment config, not SDK fallbacks or local overrides |
| History | git log and open/overlapping PRs touching the same code |
| Owner | The team or person who reviews the removal |
| Value | Measured cost (CPU, CI time, image size) used for ranking |

The guide reports false negatives from static analysis alone. Our reading:
reflection and dynamically built names are the usual cause. Cheaper models miss indirect dependencies, such as a flag read through
another flag. If a candidate lacks production evidence, it stays a candidate.

## 2. Never delete these on the agent's word

- Killswitches, operational safeguards, and flags marked permanent.
- Anything with a plausible operational purpose. Send it to its owner.
- A removal whose added complexity outweighs what it saves.

## 3. One small draft PR per removal

- One cleanup per PR, with the evidence link (flag console, telemetry query) and
  the model's rationale in the description. The rationale is what makes review fast.
- Group candidates into workstreams by file or ownership so they run in parallel.
- Feed reviewer comments back into the next round's prompt.
- Grow scope gradually: one directory, then one project, then the codebase.
- Rank by measured cost (CPU, CI time), so the team reviews the biggest wins first.

## 4. Prompt shape (paraphrased)

1. **Scope:** the exact directories or projects.
2. **Goal:** find dead code / stale flags / finished experiments.
3. **Verification:** live config, git history, overlapping PRs, indirect references.
4. **Constraints:** preserve production behaviour, killswitches and safeguards;
   ignore SDK fallbacks and local overrides; read-only.
5. **Output:** a report with evidence, owners, call sites and cost — or one draft
   PR per cleanup.

A short prompt that worked for the strongest model was too vague for a weaker
one. Review the prompts when the model changes.

## In this configuration

- Deletion of code in git is reversible, so a merged draft PR is ordinary work.
  Deleting data, datasets or live config remains under the deletion rule.
- The finder does not certify its own removal; the owner or a fresh-context
  reviewer does.
- Test-suite speedups belong in the same sweep. The guide cut one suite from 593 s
  to 30 s by adding one missing mock, and kept all tests.
