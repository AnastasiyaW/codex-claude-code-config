---
related_principles: [16, 18]
last_reviewed: 2026-07-22
---

# Session Handoff: Seamless Transitions Between Sessions

## Problem

Every new Claude Code session starts with a blank conversation. The model has CLAUDE.md, memory files, and the codebase -- but no idea what you were doing 5 minutes ago. You waste 5-15 minutes re-explaining context, the model re-discovers things you already told it, and sometimes repeats approaches that already failed.

The gap between "close session" and "open session" is where context dies.

## Quick Comparison

| Aspect | A: HANDOFF.md (Manual) | B: Stop Hook (Auto) | C: Session Journal | D: ContextHarness | E: Memory Only |
|--------|----------------------|---------------------|-------------------|-------------------|----------------|
| **Setup cost** | Zero | 10 min (hook config) | Medium (skill) | High (framework) | Zero |
| **Context quality** | High (human-curated) | Medium (auto-generated) | Medium (accumulates noise) | High (structured) | Low (fragments) |
| **Effort per session** | 2-5 min at end | Zero | Zero | Near-zero | Near-zero |
| **Failed approaches** | If you remember to add | If prompted | Logged automatically | Tracked | Lost |
| **Multi-day continuity** | Good | Good | Excellent | Excellent | Poor |
| **Multi-task switching** | Manual | One task at a time | Per-task files | Built-in switching | Shared pool |
| **Token cost on resume** | 500-2000 tokens | 500-2000 tokens | 2000-5000 tokens | 1000-3000 tokens | ~200 tokens |
| **Risk of stale context** | Low (explicit dates) | Low (auto-dated) | Medium (old entries accumulate) | Low (per-task) | High |
| **Best for** | Most workflows | Forgetful users | Long-running projects | Multi-feature work | Simple tasks |

---

## A: HANDOFF.md (Manual Prompt)

**Source:** [claude-handoff plugin](https://github.com/willseltzer/claude-handoff), [JD Hodges](https://www.jdhodges.com/blog/ai-session-handoffs-keep-context-across-conversations/)

**Core idea:** Before ending a session, ask Claude to write a structured handoff document. Next session starts by reading it.

**The handoff file:**
```markdown
# Session Handoff - 2026-04-03

## Goal
What we're building/fixing and why.

## Done This Session
- Implemented X
- Fixed Y
- Tested Z -- passing

## What Did NOT Work (and why)
- Tried approach A -- failed because [specific reason]
- Library B has bug with [specific version]

## Current State
- Working: feature X, endpoint Y
- Broken: test Z fails with [error]
- Blocked: waiting for [dependency]

## Key Decisions
- Chose PostgreSQL over SQLite because [reason]
- Using strategy pattern for [component] because [reason]

## Next Steps
1. [Most important thing to do first]
2. [Second priority]
3. [If time allows]
```

**Commands (from claude-handoff plugin):**
- `/handoff:create` -- full context handoff with all sections
- `/handoff:quick` -- minimal handoff (state + next steps only)
- `/handoff:resume` -- read handoff and continue

**Key insight:** "What did NOT work" is the most valuable section. Without it, the next session will waste time rediscovering dead ends.

**Trigger-phrase variant (no plugin required):** Add a rule file listing natural-language trigger phrases. When the agent sees one of them, it writes HANDOFF.md and stops. This works out of the box with any Claude Code setup and is ideal for older sessions started before automation was configured.

```markdown
# .claude/rules/session-handoff.md

## Manual trigger

When the user sends one of these phrases, immediately write .claude/HANDOFF.md
and stop working:

- "prepare handoff"
- "save context for new chat"
- "write handoff"
- "handoff this session"

What to do:
1. Write .claude/HANDOFF.md with real session content (not a template)
2. Group by topic if the session covered multiple areas
3. Fill the "what did NOT work" section even if everything succeeded
4. Tell the user: "Handoff written to .claude/HANDOFF.md. You can open a new chat."
5. Do NOT continue working after writing the handoff.
```

This complements hook-based automation (approach B): the hook handles forgetful
users, the trigger phrase handles deliberate session closure.

**Pros:**
- [+] Zero setup -- just ask Claude to write it
- [+] Human can review and edit before next session
- [+] Highest signal-to-noise ratio (you control what goes in)
- [+] Works across different AI tools (Claude, Cursor, Copilot)
- [+] Doubles as project documentation

**Cons:**
- [-] Requires discipline -- you must remember to ask before closing
- [-] Quality depends on how much context is left in the window
- [-] Manual effort (2-5 minutes per session end)
- [-] Easy to forget when you're "just closing quickly"

**When to choose:** Default recommendation. Works for any project. Especially valuable when sessions are task-focused (one feature, one bug fix).

---

## B: Stop Hook (Automatic)

**Source:** [GitHub Issue #11455](https://github.com/anthropics/claude-code/issues/11455), community patterns

**Core idea:** A hook on the `Stop` event automatically generates HANDOFF.md. On session start, a `.claude/rules/` file tells Claude to check for it. Zero manual effort.

**Implementation:**

Step 1 -- Create the hook script:
```bash
#!/bin/bash
# .claude/scripts/write-handoff.sh
# Called automatically on session Stop

cat > .claude/HANDOFF.md << 'TEMPLATE'
# Auto-Handoff (update me)
Generated at: $(date -Iseconds)

## Session Summary
[Claude fills this in via the Stop hook prompt]

## State
[What's working, what's broken]

## Next Steps
[What to do next]
TEMPLATE
```

Step 2 -- Configure the hook in settings.json:
```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "echo 'Handoff reminder: consider writing .claude/HANDOFF.md'"
      }
    ]
  }
}
```

Step 3 -- Add a rule for session start (`.claude/rules/session-start.md`):
```markdown
# Session Continuity

At the start of every session, check if `.claude/HANDOFF.md` exists.
If it does:
1. Read it silently
2. Briefly tell the user what the last session was about
3. Ask if they want to continue from there or start fresh

After incorporating the handoff, archive it:
- Move to `.claude/handoff-history/YYYY-MM-DD-HHMM.md`
```

**Important limitation:** The `Stop` event hook runs a shell command, not a prompt. It cannot ask Claude to summarize the session. The hook can only remind/trigger -- the actual handoff writing must be done before the Stop event (via a prompt-based approach or a skill that writes the file).

**Practical variant -- prompt-based reminder:**

Instead of generating content in the hook, use a `.claude/rules/` file:
```markdown
# Session Handoff Rule

Before ending any session longer than 15 minutes:
1. Write `.claude/HANDOFF.md` with: what was done, what failed, current state, next steps
2. Keep it under 1500 tokens
3. Include actual error messages, not descriptions
```

**Pros:**
- [+] No manual effort once configured
- [+] Consistent format every time
- [+] Archive builds project history automatically
- [+] Rules-based approach is simple and reliable

**Cons:**
- [-] Auto-generated handoffs are noisier than manual ones
- [-] Cannot capture "what the human was thinking" -- only what Claude observed
- [-] Hook limitations (Stop hooks run shell commands, not prompts)
- [-] Rule-based approach depends on Claude following the rule consistently

**When to choose:** When you consistently forget to write handoffs manually. When sessions are predictable (same project, incremental work). When you want zero-friction continuity.

---

## C: Session Journal (Living Log)

**Source:** [JD Hodges HANDOVER.md pattern](https://www.jdhodges.com/blog/ai-session-handoffs-keep-context-across-conversations/)

**Core idea:** Instead of one-shot handoffs, maintain a running journal that accumulates entries over time. Each session adds a dated entry. The journal is the project's living memory.

**File structure:**
```markdown
# Project Journal

## 2026-04-03 (Session 3)
### What changed
- Refactored auth middleware to use JWT
- Added rate limiting (100 req/min)

### What was tested
- Auth flow: login -> token -> protected route (passing)
- Rate limit: 101st request returns 429 (passing)

### What didn't work
- Redis session store -- connection pooling issues under load
- Switched to in-memory with file backup

### Learnings
- Express rate-limit v7 changed API from v6 (breaking)
- JWT_SECRET must be at least 256 bits for HS256

### Open decisions
- [ ] Redis vs Memcached for production caching
- [ ] Rate limit per-user vs per-IP

---

## 2026-04-02 (Session 2)
...
```

**Two-file system:**
- **CLAUDE.md** -- permanent reference (architecture, configs, commands)
- **JOURNAL.md** (or HANDOVER.md) -- living log of sessions

**Pros:**
- [+] Builds cumulative project knowledge over weeks/months
- [+] "What didn't work" accumulates across sessions -- no approach is tried twice
- [+] Excellent for onboarding new team members or AI agents
- [+] Each entry is self-contained -- can skip to any date
- [+] Natural audit trail

**Cons:**
- [-] Grows large over time -- needs periodic pruning
- [-] Old entries may become stale (code changed since then)
- [-] More tokens consumed on session start (must read the whole journal or recent entries)
- [-] Noise accumulates -- not every session produces valuable learnings

**Pruning strategy:** Keep last 5-7 entries in the main file. Archive older entries to `.claude/journal-archive/`. The recent window provides continuity; the archive provides searchable history.

**When to choose:** Long-running projects (weeks to months). Projects where you alternate between different features/tasks. When you want to build institutional knowledge, not just session continuity.

---

## D: ContextHarness (Framework)

**Source:** [ContextHarness](https://co-labs-co.github.io/context-harness/)

**Core idea:** A full framework that maintains per-task SESSION.md files. Switching between tasks preserves and restores context automatically. Built for multi-feature parallel work.

**Key commands:**
- `/compact` -- save current session context to SESSION.md
- `/ctx [task]` -- switch to a different task context
- Session state auto-saves on compaction

**Pros:**
- [+] Multi-task switching without losing any context
- [+] Per-task isolation (auth work doesn't pollute API work context)
- [+] Automatic -- no manual handoff writing
- [+] Integrates with compaction naturally

**Cons:**
- [-] Framework dependency -- must install and configure
- [-] Learning curve for the command interface
- [-] Opinionated about file structure
- [-] Overkill for single-task workflows

**When to choose:** When you regularly switch between multiple features/tasks in the same project. When you need task-level isolation (not just session continuity).

---

## E: Memory Only (Baseline)

**Core idea:** Rely entirely on Claude Code's built-in memory system (auto-memory, CLAUDE.md, `.claude/rules/`). No explicit handoff mechanism.

**What memory captures:**
- User preferences and role (user memories)
- Feedback and corrections (feedback memories)
- Project decisions and state (project memories)
- External references (reference memories)

**What memory misses:**
- In-progress work state ("I was halfway through refactoring X")
- Failed approaches from the last session
- Specific error messages and their solutions
- The "thread" of work -- what led to what
- Urgency and priority ("this is blocking deploy")

**Pros:**
- [+] Zero effort -- happens automatically
- [+] Works across all projects without configuration
- [+] Good for capturing long-term patterns and preferences

**Cons:**
- [-] Too fragmented for session continuity -- memories are individual facts, not a coherent state
- [-] No "failed approaches" tracking
- [-] No task progress tracking
- [-] No sense of "where we left off"
- [-] Memories are generic, not session-specific

**When to choose:** Simple, short tasks where continuity doesn't matter. When memory alone provides enough context (e.g., you always work on the same simple project).

---

## F: Rollup Handoffs (Summary Pointers)

**Source:** Distilled from the `thread_summaries.covered_until_message_id` pattern in [PavelMuntyan/MF0-1984](https://github.com/PavelMuntyan/MF0-1984) (Pavel Muntyan's multi-provider memory app, 2026-04), adapted for file-based handoffs.

**Core idea:** On projects that accumulate 20+ handoffs, reading the full history becomes overhead. A **rollup handoff** is a specially-marked handoff that summarizes a span of prior handoffs and carries a pointer to where the summary ends. Old handoffs are not deleted — they get a backlink to the rollup that subsumed them. New sessions read: rollup + only handoffs dated after the rollup's boundary.

This is the handoff equivalent of a CHANGELOG that snapshots every N minor versions rather than keeping every commit message in scrollback.

**File convention:**

```
.claude/handoffs/
├── 2026-03-01_12-00_session-01_kickoff.md
├── 2026-03-02_14-30_session-02_auth-refactor.md
├── ...
├── 2026-03-15_18-00_session-12_ci-pipeline.md
├── 2026-03-16_09-00_rollup_march-weeks-1-3.md   ← rollup
├── 2026-03-17_10-15_session-13_post-rollup.md
└── INDEX.md
```

**Frontmatter on the rollup file:**

```yaml
---
type: rollup
session: rollup-march-w1-3
covers:
  - session-01_kickoff
  - session-02_auth-refactor
  - ...
  - session-12_ci-pipeline
through: 2026-03-15 18:00
author: reviewer
---

# Rollup — March weeks 1-3

## Strategic arc
Started kickoff → pivoted to auth refactor in week 1 after performance
findings → stabilized on JWT + Redis → week 3 finished the CI pipeline.

## Decisions that still apply
- JWT over session cookies (session-02) — [see handoff]
- In-memory fallback for Redis (session-04) — [see handoff]
- ...

## What did NOT work (do not retry)
- OAuth2 proxy (session-03) — auth library incompatibility, see handoff
- Redis Cluster (session-06) — operational complexity not justified
- ...

## Current state at rollup boundary
- Working: auth, CI, basic API
- Open: rate limiting design
- Next: pricing page
```

**Backlinks on the subsumed handoffs:**

Each old handoff gets one new frontmatter field appended:

```yaml
rolled_up_into: 2026-03-16_09-00_rollup_march-weeks-1-3
```

The body of the old handoff is NOT rewritten. The file stays exactly as it was; only the frontmatter gains the pointer.

**INDEX.md update:**

```markdown
2026-03-16 09:00 | ROLLUP | covers sessions 01-12, 2026-03-01 → 2026-03-15
2026-03-17 10:15 | CLOSED | session-13 | ...
```

**Session start protocol:**

1. Read INDEX.md
2. Find the most recent ROLLUP entry
3. Read the rollup handoff
4. Read any handoffs dated **after** the rollup's `through` field
5. Skip handoffs with `rolled_up_into` set (they are already summarized)

**Pros:**
- [+] Scales to projects with 50+ handoffs without overhead on session start
- [+] Old handoffs preserved for forensic / blame / "wait I wrote that?" lookup
- [+] `covers:` list is explicit — no guessing what the rollup subsumes
- [+] `through:` boundary means post-rollup sessions are clearly additive
- [+] Pairs naturally with [Principle 16 (Project Chronicles)](../principles/16-project-chronicles.md) — chronicle entries can cite the rollup as a source

**Cons:**
- [-] Manual process today — needs a CLI or script to generate rollups safely
- [-] The rollup author is another potential source of drift — a bad rollup is worse than no rollup
- [-] Multi-session teams need a convention for who writes the rollup (probably the session doing it gets locks on all subsumed handoffs)

**When to choose:** Long-running projects past 20 handoffs where startup context takes longer than the actual work. When multiple sessions share the same project and the raw handoff pile hurts onboarding. When you are already using approach A + C and want them to scale.

**Upgrade path from C (Session Journal):** A journal's "pruning" step can become a rollup: instead of archiving to `.claude/journal-archive/`, write a rollup handoff covering the pruned entries and keep the journal current. The rollup is the readable archive.

**Attribution to MF0-1984:** The `covered_until_message_id` column in their `thread_summaries` table is what made this pattern clean. Their version works inside a SQLite schema; we translate to markdown frontmatter + git. Same idea, different medium.

---

## Recommendation

**Default: A (Manual HANDOFF.md) + E (Memory)**

For most workflows, asking Claude to write a HANDOFF.md before closing the session is the best balance of effort and quality. Memory handles long-term context; HANDOFF.md handles session-to-session continuity.

**Upgrade path:**

1. **Start with A** -- manual handoffs. Get the habit of writing them.
2. **Add B (rules-based reminder)** -- a `.claude/rules/` file that reminds Claude to write HANDOFF.md before ending long sessions.
3. **If you work on multi-day projects, add C (journal)** -- accumulate learnings across sessions.
4. **If you juggle multiple features, consider D (ContextHarness)** -- task-level context switching.
5. **When your handoff pile passes ~20 entries on one project, add F (Rollup Handoffs)** -- summarize old history into one rollup, keep the raw files for forensic lookup.

**Anti-patterns to avoid:**
- Dumping raw conversation history into a file (noise overwhelms signal)
- Writing handoffs that describe what tools were called instead of what was learned
- Keeping stale handoffs that reference code that no longer exists
- Handoffs that say "everything works" without specifying what was tested
- Relying on `--continue` for continuity across days (session history bloats, context degrades)

**The golden rule:** A good handoff answers three questions in under 1500 tokens:
1. What is the current state? (working/broken/blocked)
2. What should I NOT try again? (failed approaches with reasons)
3. What is the single most important next step?
