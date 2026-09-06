# Session Handoff - seamless transitions between sessions

Drop this file into `.claude/rules/session-handoff.md` (project-local) or
`~/.claude/rules/session-handoff.md` (global) to enable handoff triggers.

## Which mode do you need?

Two modes. Pick one based on how you work:

| Mode | When to use | Storage |
|---|---|---|
| **Single-file** (simpler) | One chat at a time, occasional session breaks | `.claude/HANDOFF.md` |
| **Multi-session** (safer for parallel chats) | Multiple Claude Code chats running simultaneously on the same project | `.claude/handoffs/<project-slug>/<unique>.md` + `INDEX.md` |

**Most users need single-file.** If you never run parallel chats, the simpler mode is enough - one file, overwrite-on-write, no coordination overhead.

**Switch to multi-session** only if you actually parallelize. Symptoms: you opened chat #2 while #1 was still running, and #2's handoff wiped #1's. Data loss from last-writer-wins is the trigger for moving up.

The format of a handoff file (what sections it has, what to include) is the same in both modes - see [Handoff file format](#handoff-file-format) below.

---

## Single-file protocol

**Storage:** one `.claude/HANDOFF.md`. Each session overwrites the previous one. Archive copies move to `.claude/handoff-history/` on read.

### Write on manual trigger

When the user sends: "prepare handoff", "save context for new chat", "write handoff", "handoff this session" (or equivalent) - immediately write `.claude/HANDOFF.md` following the format below. Then stop working.

### At session start

1. Check for `.claude/HANDOFF.md`
2. If it exists: read it as optional context. Do not summarize it or ask for a
   resume-vs-fresh choice before responding to the next explicit user request;
   that request is authoritative. Use the handoff silently only when it helps
   complete that request.
3. After incorporating: move to `.claude/handoff-history/YYYY-MM-DD-HHMM.md`
4. Keep last 10 archives, delete older

### At session end (sessions over 15 minutes)

If the user didn't explicitly trigger a handoff, write one anyway. Complements the optional Stop hook.

---

## Multi-session protocol

**Storage:** `.claude/handoffs/<project-slug>/` — one subdirectory per project, one file per chat, plus a single append-only `INDEX.md` at the handoffs root.

`<project-slug>` is the kebab-case name of the project actually worked on (not the cwd name). Reuse an existing subdirectory if one fits; create it if not. This keeps unrelated projects from interleaving when many sessions share one working directory (e.g. a hub directory): the SessionStart hook shows the latest handoff *per project* instead of the 3 newest overall, so a busy project cannot crowd out the one you came back for.

### Architectural principle: append-only, never overwrite

Multiple Claude Code chats can work in parallel in the same project. If all chats write to a single `.claude/HANDOFF.md`, last writer wins and earlier handoffs vanish. The multi-session pattern gives each chat its own file and nobody loses anything.

```
.claude/handoffs/
├── project-alpha/
│   ├── 2026-04-09_14-32_373d1618.md  ← chat 1
│   └── 2026-04-09_16-47_ab154a15.md  ← chat 3
├── project-beta/
│   └── 2026-04-09_15-01_b858f500.md  ← chat 2
└── INDEX.md                           ← append-only index of all handoffs
```

**Invariant:** no chat ever overwrites another chat's handoff. Each handoff has a unique filename following `YYYY-MM-DD_HH-MM_<session-short-id>.md` inside its project subdirectory. The timestamp in the **filename** is authoritative (mtime drifts when a handoff gets a later status update).

This is a direct application of [principle 18 - multi-session coordination](../principles/18-multi-session-coordination.md): handoffs are the **append-only** variant of shared state (conflict-free by construction).

### Manual trigger

When the user sends one of these phrases (or equivalent), immediately write a handoff file following the protocol below and stop working:

- "prepare handoff"
- "save context for new chat"
- "write handoff"
- "handoff this session"
- "we're closing, write handoff"
- "hand off this conversation"

### Write protocol

**Step 1.** Determine session ID and timestamp:
- Session ID: from session context if available, else generate short UUID (8 hex chars)
- Timestamp: current local time

**Step 2.** Ensure the project subdirectory exists (reuse an existing slug if one fits):
```bash
mkdir -p .claude/handoffs/<project-slug>
```

**Step 3.** Write the handoff file with a unique name (atomic via Write tool, not append-in-pieces):
```
.claude/handoffs/<project-slug>/YYYY-MM-DD_HH-MM_<session-short-id>.md
```

Where `<session-short-id>` is the first 8 chars of the session ID, or 8 random hex chars if the ID is unavailable.

Before writing, complete the closure audit in the handoff body. The handoff is
not valid without it. This is the guard against "handoff instead of finishing":
the agent must explicitly check the primary request and related/scope-adjacent
tasks before transferring context.

**Step 4.** Append one line to `.claude/handoffs/INDEX.md` (append, never overwrite):
```markdown
- 2026-04-09 14:32 | 373d1618 | project-alpha | Cleanup: drift validator + security case study | ACTIVE
```

If INDEX.md does not exist, create it with a header.

**Step 5.** Tell the user: "Handoff written to `.claude/handoffs/<filename>`. You can open a new chat now."

**Step 6.** Do NOT continue working. The user is closing the session.

### At session start

**Step 1.** Read `.claude/handoffs/INDEX.md` if it exists.

**Step 2.** If INDEX has handoffs from the last 24 hours:
1. Read the relevant handoff as optional context; do not list handoffs or ask
   the user to choose one before responding to their next explicit request.
2. The explicit request controls. Use a relevant handoff silently when it
   helps complete that request; leave unrelated handoffs untouched.
3. Surface a resume choice only when the user explicitly asks to resume or
   select a handoff, or when there is no current user request to answer.

**Step 3.** If the user says "resume <session>" or "continue the last one":
1. Read the corresponding handoff file in full
2. Update status in INDEX.md from `ACTIVE` to `RESUMED-by-<new-session-id>` (append new line, don't edit old one - see rules below)
3. Briefly summarize what was in the previous session
4. Continue work from there

**Step 4.** If the user starts a new task - don't touch old handoffs. They stay in INDEX as ACTIVE/CLOSED. The archive is cleaned separately.

### INDEX.md statuses

| Status | Meaning |
|---|---|
| `ACTIVE` | Handoff written, waiting to be resumed |
| `RESUMED-by-<session>` | Another session picked it up and continued |
| `CLOSED` | Work completed, handoff no longer needed |
| `ABANDONED` | Session no longer relevant (e.g. older than 7 days) |

Sessions mark their own handoffs `CLOSED` when work completes. Old `ACTIVE` handoffs (>7 days) can be manually marked `ABANDONED` or deleted.

### Archiving

Handoff files are **not** deleted automatically. They live in `.claude/handoffs/` as history.

For manual cleanup:
```bash
# Move handoffs older than 14 days to archive
mkdir -p .claude/handoffs/archive
find .claude/handoffs -name "*.md" -not -name "INDEX*" -mtime +14 -exec mv {} .claude/handoffs/archive/ \;
```

INDEX.md itself is not rewritten - it grows append-only. If it gets too long, manually move old entries to `INDEX-archive.md`.

### Rules against data loss (multi-session only)

1. **Never use `.claude/HANDOFF.md`** (singular file) in multi-session mode - it's the old model with race conditions
2. **Never delete another session's handoff** - even if it looks stale. Mark it `ABANDONED` if needed
3. **Never overwrite an existing handoff file** - if the name is taken, add `_2`, `_3`, etc.
4. **Writing is atomic.** Write the file as a whole via one Write tool call. Do not append in pieces (another chat could read a half-written file).
5. **INDEX.md is append-only.** If you need to update the status of an existing entry, append a new line below, do not edit the old one.

### Why manual triggers + rules (not just hooks)

A Stop hook can remind you to write a handoff for long sessions. But hooks in the current model don't receive session ID, so they can't generate the unique filename this protocol requires. The options are:
- Manual trigger (always works, relies on user or rule)
- Hook that forces writing to singular `.claude/HANDOFF.md` (old model, race-prone)

Until hooks expose session ID, manual triggers with rule-based reminders are the reliable path for multi-session. A Stop hook that **reminds** (doesn't auto-write) can coexist: it tells the user "write a handoff before closing" and the rule/model handles the actual write with unique naming.

---

## Handoff file format

Used by both modes. Structure is the same; only the storage location differs.

```markdown
# Session Handoff - YYYY-MM-DD HH:MM

**Session ID:** <full-or-short-session-id>  (multi-session mode only)
**Status:** ACTIVE | CLOSED | ABANDONED  (multi-session mode only)
**Working directory:** <absolute-path>
**Project:** <project-slug for long-running projects> (optional)

## Goal
[What we were trying to accomplish and why - 1-2 sentences]

## Done
- [Concrete results with absolute file paths]
- [Group by topic if session covered multiple areas]

## What did NOT work (and why)
- [Approach] - [specific reason, with error message if any]

## Current state
- Working: [what was verified and works]
- Broken: [what doesn't work, with specific errors]
- Blocked: [what is waiting on external dependencies]

## Key decisions
- [Decision] - because [reason]

## Next step
[One concrete action to begin the next session - not a list]

## Closure Audit
- Primary request status: COMPLETE | BLOCKED-<external-reason> | HANDOFF-NEAR-CONTEXT-LIMIT | USER-REDIRECTED
- Acceptance/checklist verified: [tests/checks/evidence, or exact blocker]
- Related/scope-adjacent tasks checked: [what adjacent work was checked]
- Unfinished related tasks: NONE | [durable tracker + reason: PROBLEMS.md / feature_list.json / issue / backlog / BLOCKED-*]
- Why not continuing now: NONE | [external blocker / context limit / user redirect]

## Background tasks (if any)
- [agent-id or task-id] - [what it does] - [status]
```

**Content rules:**
- Max 1500 tokens - this is a briefing, not a log
- Include real error messages, not descriptions
- "What did NOT work" is mandatory, even if everything succeeded
- "Closure Audit" is mandatory. Do not write a handoff until it says whether the
  primary request is complete, what related/scope-adjacent work was checked, and
  where any unfinished related task is durably tracked.
- File paths are absolute
- Do NOT include: tool call history, intermediate file reads, raw command output

## Connection to Project Chronicles

For long-running projects (spanning weeks/months with 3+ handoffs), handoffs alone don't tell the story of how a project evolved. **Project chronicles** solve this with a condensed timeline per project.

When writing a handoff for a long-running project:
1. Add `**Project:** <slug>` to the handoff header
2. After writing the handoff, append a 3-7 line entry to `.claude/chronicles/<slug>.md`
3. Chronicle entry = strategic digest (decisions, turns, results), NOT a handoff copy

When starting a session on a long-running project:
1. Read `.claude/chronicles/<slug>.md` for strategic context
2. Read the latest handoff for tactical context
3. Together they answer both "how did we get here?" and "what's next?"

See [principles/16-project-chronicles.md](../principles/16-project-chronicles.md) for the full pattern and [templates/chronicle.md](../templates/chronicle.md) for the file template.

## See also

- [principles/18-multi-session-coordination.md](../principles/18-multi-session-coordination.md) — the architectural principle the multi-session mode applies (append-only shared state)
- [alternatives/session-handoff.md](../alternatives/session-handoff.md) — comparison of 5 approaches (manual, hook, journal, framework, memory-only) with trade-offs
