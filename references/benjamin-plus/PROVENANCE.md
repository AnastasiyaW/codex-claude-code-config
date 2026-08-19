# benjamin-plus — provenance and why it is wired this way

Upstream: https://github.com/JetBrains/benjamin-plus-skill — MIT, © 2026
benjamin-plus contributors. CODEOWNER `@DenisSergeevitch`, the same author as the
`agents-best-practices` skill this machine already uses.

Fetched 2026-08-19 at commit `532771be5687566b12a9f62e17fbe7ad3591518c`.

## What is vendored here

| file | sha256 (LF bytes) | source |
|---|---|---|
| `injected-instruction.md` | `be51fa14d9437840e7282d768f75e1938adb21286e9ef2eb167337daf418b275` | upstream, byte-identical |
| `RULESET.md` | `a8a8871804f1890c75b15a11d769028ab5d22b2ab8941f9b3f9b24c9539cb58c` | upstream, byte-identical (kept for the skill-form text and its front-matter) |
| `LICENSE` | MIT | upstream |
| `local-precedence.md` | — | **ours**, not upstream |

Both upstream hashes match the manifest in upstream's own `SHA256SUMS.txt`.
Verify after any update:

```bash
python -c "import hashlib,io;print(hashlib.sha256(io.open('injected-instruction.md','rb').read().replace(b'\r\n',b'\n')).hexdigest())"
```

The CRLF strip is not cosmetic: `core.autocrlf=true` on this machine rewrites
line endings on checkout, and every text file in the clone failed its checksum
until the bytes were normalised back to LF.

## Why injected, not installed as a skill

Upstream measured both delivery methods head to head on Java SWE-bench
(Codex CLI, 225 instances × 3 replicas): hook-injected was the only arm
significantly cheaper (−4.4 % cost [−7.5, −1.5], p = 0.003, solve rate
unchanged); the same text as a discoverable skill folder saved nothing
(−0.5 %, n.s.) because agents spent a median 3 steps finding `SKILL.md`, with
73 % path misses.

So there is deliberately **no** `benjamin-plus` folder in `~/.agents/skills` or
`~/.claude/skills`. Creating one would add discovery cost and, by upstream's own
measurement, return nothing.

## What the numbers are, and what they are not

Headline (upstream, 80 paired SkillsBench tasks, Claude Code 2.1.201 in Docker,
Sonnet 5, low effort, Wilcoxon on paired deltas): cost −17.9 % median (p = 0.005),
total tokens −21.9 % (p = 0.001), turns −20.0 % (p = 0.001), wall-clock −15.6 %
(p = 0.018). Quality: 7 better / 5 worse / 68 tie, sign p = 0.77.

Read with the caveats upstream states plainly:

- **The quality result is not an equivalence test.** 80 pairs rules out large
  effects, not small ones.
- **The saving scales with how bloated the baseline runs.** The same skill
  measured −10.0 % (p = 0.169, not significant) a day earlier against a leaner
  control; between the two days the control drifted +10.5 % while the treated arm
  stayed flat. It behaves as a variance clamp on session cost.
- **Medians, not totals.** A tail of hard tasks gives part of the aggregate back.
- **Our sessions are not their benchmark.** SkillsBench runs a near-default
  Claude Code. This machine injects a large always-on rule set at SessionStart
  already, so the measured percentages are an upstream figure, not a prediction
  for here. The honest local claim is "the mechanics are sound and cost 745
  tokens a session to try", not "expect −18 %".

## The collision, and how it is resolved

Rule 4's tail ("no victory laps", "close with at most two lines") and the closing
paragraph ("never build a verification harness, test suite, or checker the task
didn't ask for") pull against this machine's canon:
`finish-the-task` P2/P3, `quality-over-tokens-independent-verify`,
`quality-code` ("нетривиальная логика оставляет ОДНУ запускаемую проверку"), and
`green-suite-proves-imagined-shapes`.

Upstream is not wrong on its own terms — its lab notes record that quality guards
generated verification whales which erased the savings, and the winning version
deleted more rules than it added. But that trade was optimised for a benchmark
scored per task, not for work that ships and has to be lived with.

Rather than edit upstream's text (which would fork it and break future updates),
`local-precedence.md` is appended after it and states which side yields where.
The injection order matters: the precedence block is last, so it reads as the
governing clause.

## Update procedure

```bash
git clone --depth 1 https://github.com/JetBrains/benjamin-plus-skill <tmp>
# re-verify SHA256SUMS.txt against LF-normalised bytes, then copy in,
# then re-read local-precedence.md against the new wording — a rule that
# changed may need the precedence clause changed with it.
```

Wired by `hooks/benjamin-plus-inject.py` (SessionStart, matcher
`startup|resume|clear|compact` — the four events that otherwise wipe injected
context). Opt out with `CLAUDE_SKIP_BENJAMIN=1` or `touch .claude/.skip-benjamin`.
Codex reads the same two files through a marked block in `~/.codex/AGENTS.md`.
