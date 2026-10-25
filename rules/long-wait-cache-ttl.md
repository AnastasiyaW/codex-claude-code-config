# Long waits: at most 50 minutes, then go and check

Owner directive (2026-10-25): never wait longer than 50 minutes on background work, and
give subagents a 1-hour prompt cache instead of 5 minutes.

## Why 50 minutes
With `promptCacheTtl: "1h"` the main conversation's prompt cache lives for 1 hour. That is the
default only on a subscription within plan usage; with API keys, cloud providers or usage credits
the default is 5 minutes, so set it explicitly (code.claude.com/docs/en/prompt-caching, "Cache
lifetime"). A turn that
arrives more than an hour after the previous one re-reads the whole context uncached and burns
usage. 50 minutes leaves a 10-minute margin. Waiting past the hour is spending, not patience.

## Rule
- Waiting on long background work (CI queue, pipeline tests, training, uploads, remote runs):
  one wait is **at most 50 minutes** (≤ 3000 s). `ScheduleWakeup`: `delaySeconds` ≤ 3000.
  `Monitor` or a background command that notifies on exit: add a fallback wakeup ≤ 3000 s in
  case the notification never comes.
- On waking, **check live state**, do not just extend the wait: job status, log tail, step or
  checkpoint number, CI queue position. No progress since the last check means the job is
  probably stuck (silence is not health): diagnose it instead of waiting another 50 minutes.
  This catches hung CI as a side effect.
- Short polling (seconds) is still forbidden: every check is a turn over the whole context.
  Within the 50 minutes, match the wait to the real duration (CI takes ~8 min → one check at ~8 min).

## Subagents
In `~/.claude/settings.json`:

```json
"promptCacheTtl": "1h",
"subagentPromptCacheTtl": "1h"
```

Outside the main conversation (subagents, workflows, background work) the default TTL is 5
minutes (prompt-caching docs). Owner's observation: sessions that spawn dozens of agents
exhausted usage on repeated cache writes.
Source: code.claude.com/docs/en/env-vars (`CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` /
`subagentPromptCacheTtl`, Claude Code ≥ 2.1.242; the environment variable wins over the setting,
and `FORCE_PROMPT_CACHING_5M=1` overrides both). Cost: the API bills 1-hour cache writes at a
higher rate than 5-minute ones; it pays off when an agent pauses longer than 5 minutes between
requests.

Remote runs with their own `CLAUDE_CONFIG_DIR` do not see these settings: put the TTL and the
50-minute rule into the brief.
