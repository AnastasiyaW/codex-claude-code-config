# Rules

Drop-in rules for `~/.claude/rules/` (global) or `.claude/rules/` (project). A file
without frontmatter is loaded into every session.

## On-demand rules

Four rules carry this frontmatter:

```yaml
---
paths:
  - "**/__rule_on_demand__/**"
---
```

`paths:` makes Claude Code load a rule only when a matching file is in play, and this
glob matches nothing. The rule is therefore never auto-loaded: it is read when an
always-loaded index tells the agent to read it, for the topic it covers. That keeps
situational rules out of the always-on context.

| Rule | Read it when |
|---|---|
| [`safety-billing.md`](safety-billing.md) | launching Claude Code, spending subscription or API credit, `HERMES.md` or `ANTHROPIC_*` in the environment |
| [`verify-at-consumer.md`](verify-at-consumer.md) | a webhook, queue, API/RPC or any producer-to-consumer contract |
| [`system-verification-independent.md`](system-verification-independent.md) | a watchdog, monitor, kill switch or anything with an external effect |
| [`rlm-context-as-program.md`](rlm-context-as-program.md) | logs, JSONL, transcripts or another artifact larger than the context window |

**If you copy them without an index**, they will never load. Either add an
always-loaded index file with a table like the one above (the agent reads the rule it
names), or delete the `paths:` frontmatter to make the rule always-on.
