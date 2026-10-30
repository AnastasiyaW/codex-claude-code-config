# pult: a control strip for Claude Code

A Claude Code mod (plugin with a hooks module) that shows what the session is doing and how
much room is left, and writes a handoff before context is compacted.

Originally written for an internal setup; this is the generic subset.

The interface strings (band, pane, toasts, handoff prompt) are in Russian.

## What it shows

- **Progress band** above the prompt. The model reports progress with the `progress` tool
  (`mcp__pult__progress`): title, an N/M bar, "now", an optional nested sub-progress with
  percent, "next", and summary counters. The mod adds a short rule about the tool to the system
  prompt. When a turn grows to 4+ tool calls with no active progress, the model gets a one-time
  hint to call it. A finished task shows a check mark and is cleared by your next message.
- **"What's running now" band**: the current tool call with a timer (after 3 s; a pending
  permission prompt shows at once), the TodoWrite plan as `done/total · current item`, and
  running subagents with model and context size. Empty when nothing runs.
- **`/activity` pane**: running calls, calls waiting for permission, subagents (model, context,
  approximate spend), the plan, recent calls, context fill and the time of the last handoff.
- **Status line**: context fill, weekly and 5-hour account limits with reset time, number of
  running subagents with model and context.
- **Handoff nudge**: one toast and a warning line above the prompt when a limit window reaches
  `nudge_percent`, and one toast when context reaches `context_percent`.
- **"Compact or new chat" nudge**: from `new_chat_tokens` of main-chat context, a warning line
  above the prompt, and the model is asked once to offer the choice in its final answer
  (same task: `/compact`; new task: a new chat with a handoff).
- **Handoff before compaction**: before `/compact` and auto-compaction of the main chat, the
  model writes a handoff of the session from the cached transcript. Skipped if this session
  already has a handoff younger than 25 minutes. If the model cannot answer (for example, the
  transcript no longer fits), a draft is written from the last messages.
- **System notifications** (terminal only; the desktop app notifies by itself): a long turn
  ended, or a call is waiting for permission.

## Commands

| Command | What it does |
|---|---|
| `/save-handoff` | Write the handoff now, without a separate turn |
| `/handoff` | Put a "write a handoff" request into the prompt field |
| `/activity` | Open the Activity pane |

## Configuration (`/config`)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `status_line` | boolean | `true` | Limits, context and subagents in the status line |
| `handoff_nudge` | boolean | `true` | Limit/context nudges and the `/handoff` command |
| `nudge_percent` | number | `90` | Limit usage (week or 5 h) that triggers the nudge, % |
| `context_percent` | number | `80` | Context fill that triggers the one-time nudge, % |
| `new_chat_tokens` | number | `350000` | Main-chat context that triggers the compact/new-chat nudge; `0` disables it |
| `compact_handoff` | boolean | `true` | Handoff before compaction and the `/save-handoff` command |
| `progress_band` | boolean | `true` | The `progress` tool and its band |
| `activity_band` | boolean | `true` | The "what's running now" band |
| `activity_pane` | boolean | `true` | The `/activity` command and pane |
| `notify` | boolean | `true` | System notifications |
| `notify_minutes` | number | `3` | Turn length that counts as long, minutes |

## What it reads and writes

- Reads limits and context from the engine only: `$.session.usage()` after each turn and the
  `session.measure` event. Subagent context comes from each subagent response.
- Writes handoffs to `<project root>/.claude/handoffs/<project-slug>/YYYY-MM-DD_HH-MM_<session8>.md`
  and appends one line to `<project root>/.claude/handoffs/INDEX.md`. INDEX.md is rewritten only
  after a successful read, so a locked file never becomes an empty index.
- Writes only where the path really lands inside the project: if `.claude/handoffs` (or a folder
  above the file) is a link leading outside, nothing is written; if `INDEX.md` is itself a link,
  it is left alone.
- A handoff contains text from the conversation; a draft (when the model could not answer)
  quotes the last messages directly. If you paste secrets into chats, add `.claude/handoffs/`
  to `.gitignore` or check handoffs before committing.
- Makes no network calls. The handoff is one model request over the cached transcript;
  compaction waits for it.

## Loading

Requires Claude Code v2.1.280 or later. Point `CLAUDE_CODE_PLUGIN_DIRS` at the absolute path of
this folder (on Windows, separate several folders with `;`):

```sh
export CLAUDE_CODE_PLUGIN_DIRS=/path/to/mods/pult
```

```powershell
$env:CLAUDE_CODE_PLUGIN_DIRS = "D:\path\to\mods\pult"
```

Claude Code generates the engine types in `.claude-plugin/types/` when the mod loads; they are
not committed.

## Layout and checks

- `.claude-plugin/plugin.json`: manifest and settings
- `hooks/register.tsx`: the mod
- `types/index.d.ts`: types of its state
- `tests/`: pure functions, pane and band rendering, handoff before compaction and its failure paths

```sh
claude plugin validate .
claude plugin test .
```
