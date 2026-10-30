# Token overspend: what we found and the interim measures

Status: interim, 2026-10-30. Each measure below names the official fix that
retires it. When that fix ships, the measure is removed from this repository.

## What we found

Measured on one Windows workstation that runs this harness, 2026-10-30:

1. **Every fresh general-purpose subagent reloads the whole user context.** Its
   first request carried the full `CLAUDE.md` plus every rule file without
   `paths:`: about 270 KB here. That request cost 99-164 thousand tokens, mostly
   cache writes. An `Explore` agent, which skips `CLAUDE.md`, cost about 39
   thousand. Nine Haiku agents started together wrote about 950 thousand tokens
   before doing any work.
2. **A one-hour subagent cache costs more on short agents.** With
   `subagentPromptCacheTtl: "1h"` the start-up block is written at 2x the input
   price instead of 1.25x for the 5-minute TTL. One hour pays off only for an
   agent that idles longer than 5 minutes between requests.
3. **Background agents in auto mode woke the main conversation.** An agent that
   waited on its own shell started a new main-conversation turn on every wake,
   and each turn re-sent the whole conversation. Claude Code 2.1.311 fixes this
   (changelog: "Fixed background agents in auto mode that wait on their own shells
   starting a new main conversation turn on every wake").
4. **Agent status summaries.** Background agents request a short status summary
   about every 30 seconds. An Anthropic engineer put the typical cost at about 2%
   (public discussion, October 2026). Third-party scripts that patch Claude Code
   timers to switch this off are not adopted here: they depend on internals,
   break agent status, and stop matching after an update.

Background for the size of the problem: Anthropic reports that multi-agent runs
use about 15 times the tokens of a chat
(https://www.anthropic.com/engineering/multi-agent-research-system), and issue
https://github.com/anthropics/claude-code/issues/106025 shows 98% of a long run's
tokens as re-sent context.

## Interim measures

| Measure | Where | Retire when |
|---|---|---|
| Benjamin-Plus habits injected at session start | plugin `hooks/benjamin-plus-inject.py` | Claude Code ships equivalent built-in guidance, or a measured A/B shows no saving |
| RTK compresses Bash output | plugin `hooks/rtk-plugin-hook.py`, [rtk-integration.md](rtk-integration.md) | Claude Code compresses tool output natively |
| Update Claude Code to 2.1.311 or later | each machine | already official; this row goes once every machine runs it |
| Do not install agent-summary patches | this note | Claude Code offers a setting for agent summaries |

The 7-day minimum release age (`min-release-age=7` in `~/.npmrc`) still applies
to Claude Code: 2.1.311 becomes installable on 2026-11-02. Keep the gate; a week
of waiting is the supply-chain defence.

## What to do now

1. Update the plugin: `claude plugin marketplace update team-harness`, then
   `claude plugin update harness@team-harness`, then `/reload-plugins`.
2. Install RTK on Windows by [rtk-integration.md](rtk-integration.md) and put the
   verified `rtk.exe` on `PATH`. Without it the RTK hook does nothing.
3. From 2026-11-02, update Claude Code to 2.1.311 or later.
4. For search and reading, use the `Explore` agent: it does not load `CLAUDE.md`.
