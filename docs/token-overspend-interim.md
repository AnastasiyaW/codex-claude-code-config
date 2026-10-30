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

5. **The skill list has a ceiling, and moving skills out does not lower it.**
   The per-turn skill listing may use `skillListingBudgetFraction` of the context
   window; the default is `0.01`, 1% (settings reference,
   https://code.claude.com/docs/en/settings-reference). With a 1M window that is
   about 10 thousand tokens. A second workstation moved 41 SEO skills out of the
   list and the listing stayed at about 9.9 thousand: the remaining skills filled
   the same ceiling. Only a lower fraction saves.
6. **Rules without `paths:` load into every chat and every subagent.** The memory
   page: rules without `paths` "are loaded at launch with the same priority as
   `.claude/CLAUDE.md`" (https://code.claude.com/docs/en/memory). The second
   workstation kept 9 of 19 rules always loaded and made the rest load by
   keyword. Its estimate is about 30 thousand of 130 thousand tokens saved per new
   chat; this is a calculation, the measurement is still running.
7. **A linked session's report is a new turn of the main chat.** "When the
   receiving session is idle, Claude Code starts a new turn with the message"
   (https://code.claude.com/docs/en/cross-session-messaging). Like any turn, it
   sends the main conversation again (finding 3 above). When the main chat does not need the result, an
   ordinary new chat is cheaper than a linked one.

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
| Lower `skillListingBudgetFraction` below `0.01` (for example `0.005`); fewer skill descriptions stay visible, so check that the skills you rely on still trigger | `~/.claude/settings.json` | Claude Code lists skills on demand instead of every turn |
| Keep few rules without `paths:`; give the rest `paths:` and list them in one always-loaded index so the agent can open them by topic | `rules/` | Claude Code picks rules by relevance on its own; until then keep the index, because `paths:` loading has failed before ([#17204](https://github.com/anthropics/claude-code/issues/17204), [#22170](https://github.com/anthropics/claude-code/issues/22170), both closed) |
| Start an ordinary new chat for side work whose result the main chat does not need | habit | cross-session reports stop costing a main-chat turn |
| Offer "compact or new chat" at about 350 thousand tokens and write a handoff before compaction | mod [`mods/pult`](../mods/pult/README.md) | Claude Code offers the same prompt and keeps a handoff across compaction |

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
5. Count your rules without `paths:` (`grep -L "^paths:" ~/.claude/rules/*.md`)
   and keep only the ones every chat needs.
6. Optional: load the `pult` mod. Set the `CLAUDE_CODE_PLUGIN_DIRS` environment
   variable to the absolute path of `mods/pult` (Claude Code 2.1.280 or later) and
   open a new chat.
