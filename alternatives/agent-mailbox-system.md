---
related_principles: [19]
last_reviewed: 2026-07-22
---

# Agent Mailbox System: File-based Inter-Agent Communication

Date: 2026-04-12 (extended 2026-04-14 with classical mail semantics: threading, sent folder, delivery receipts, filter rules)

> **Relates to [principle 19 - Inter-Agent Communication](../principles/19-inter-agent-communication.md)** which covers the architectural rationale (why mail-style over ad-hoc, two coordination axes, when not to use a mailbox). This file is the implementation playbook.

## Problem

Multiple Claude Code sessions working on the same project need to communicate: ask questions, report decisions, notify about completed tasks. Git push/pull is too slow for real-time communication.

## Solution: SMB-based File Mailbox

```
.claude/mailbox/
  reviewer/       <- inbox for agent "reviewer"
  builder/     <- inbox for agent "builder"
  ops/    <- inbox for agent "ops"
  all/       <- broadcast (all agents read)
```

Each message = markdown file with frontmatter:
```markdown
---
from: builder
to: reviewer
priority: normal
status: unread
date: 2026-04-11 14:46
topic: cmake libsodium question
---

Message body here.
```

## Delivery: Instant via SMB

If agents work on the same filesystem (SMB share, NFS, or same machine):
- Agent A writes file to `mailbox/B/` -> Agent B sees it instantly
- No git push/pull needed
- No daemon/server needed

For remote agents: use git push + hooks, or SMB over Tailscale/VPN.

## Auto-check via Hooks

```json
{
  "hooks": {
    "SessionStart": [{"hook_command": "python .claude/scripts/check_mail.py"}],
    "UserPromptSubmit": [{"hook_command": "python .claude/scripts/check_mail.py"}],
    "PreToolUse": [{"hook_command": "python .claude/scripts/check_mail_throttled.py"}]
  }
}
```

- **SessionStart**: full inbox check, show all unread
- **UserPromptSubmit**: check before each user message
- **PreToolUse (throttled)**: check every 2 min during autonomous work

Throttled version uses a timestamp file to avoid checking on every tool call.

## CLI

```bash
# Send
python mail.py send --from builder --to reviewer --topic "question" --body "text"

# Check inbox
python mail.py check --who reviewer --unread-only

# Broadcast
python mail.py broadcast --from reviewer --topic "architecture decision" --body "text"

# Summary
python mail.py summary
```

## Key Finding

UserPromptSubmit hook = best trigger. Agent sees new mail before processing user's next message. For long autonomous tasks, throttled PreToolUse every 2 min catches urgent messages.

## Real-world Usage

Field-tested on a multi-agent project with 3 named agent roles (planner, executor, reviewer):
- Planner sends task lists to executor via mailbox
- Executor reports completed tasks back
- Broadcast for architecture decisions that affect all agents
- Instant delivery via SMB share over Tailscale (no broker, no daemon)

## Files

- `mail.py` - CLI (send/check/reply/broadcast/summary)
- `check_mail.py` - full inbox check for SessionStart/UserPromptSubmit hooks
- `check_mail_throttled.py` - throttled check for PreToolUse hook
- `agent-mailbox.md` - rule for agents explaining the system

---

## Classical mail extensions (added 2026-04-14)

The original mailbox implementation covered basic send/receive/broadcast. Production use surfaced three gaps that classical email solved decades ago: threading, sender audit trails, and delivery confirmation. Adding them costs almost nothing and eliminates whole classes of confusion.

### Threading via `in_reply_to` + `message_id`

**Problem:** a multi-turn exchange between agents becomes a scatter of unrelated files. "Is this reply to the 14:30 question or the 15:02 question?" - you can't tell without reading bodies.

**Fix:** every message carries a unique `message_id`; replies carry `in_reply_to` referencing the parent.

```markdown
---
from: builder
to: reviewer
subject: "Re: cmake libsodium question"
message_id: 20260414-153100-builder-r1
in_reply_to: 20260414-143000-reviewer-001
references: [20260414-143000-reviewer-001]  # full thread chain for deep replies
---
```

Reader tools (or a simple `mail.py thread <message_id>`) follow `in_reply_to` chains to reconstruct conversations. `references` carries the full ancestry for messages buried 5+ replies deep.

**Format for `message_id`:** `YYYYMMDD-HHMMSS-<sender>-<seq>`. Unique, sortable, human-readable. No UUIDs needed.

### Sent folder

**Problem:** after sending a message, the sender has no record of what was sent unless they manually saved a copy. When recipient asks "wait, what did you ask me to do?" - sender can't answer without checking the recipient's inbox (invasive) or re-reading their own prompt history (tedious).

**Fix:** send-time, write the message twice:
1. To `mailbox/<recipient>/inbox/<message_id>.md` (the actual delivery)
2. To `mailbox/<sender>/sent/<message_id>.md` (sender's audit copy)

Both files are identical. Sender can grep their own `sent/` folder, see their own threads, follow up on messages without read receipts.

### Delivery receipts

**Problem:** sender has no way to know if recipient saw the message. Waiting "did they see it yet?" loops burn tokens.

**Fix:** two-level confirmation, both optional.

**Level 1: status update on the original message.** When the recipient reads a message, they Edit the file to change `status: unread` → `status: read` and add `read_at: 2026-04-14T15:35:00`. Sender checks their `sent/` copy... wait, the sent copy is a separate file, updating the inbox one doesn't change it.

So for level 1 to work, the sender should read the *recipient's inbox* copy, not their `sent/` folder. Slightly invasive but standard file-read.

**Level 2: explicit receipt message.** When recipient reads a message marked `request_receipt: true`, they send back a minimal receipt:

```markdown
---
from: beta
to: alpha
subject: "Receipt: 20260414-143000-alpha-001"
message_id: 20260414-143500-beta-r
in_reply_to: 20260414-143000-alpha-001
is_receipt: true
---

Read 14:35. Ack.
```

Sender gets an inbox ping. No ambiguity.

**When to use which:** level 1 for fire-and-forget (sender occasionally checks status). Level 2 when sender is actively waiting and needs notification when recipient responds.

### Filter rules (optional)

**Problem:** when an agent has many senders, high-priority messages get buried behind routine ones.

**Fix:** `.claude/mailbox/<agent>/.filter.yaml` declares auto-triage rules:

```yaml
rules:
  - match:
      from: team-lead
    action:
      priority: high
      move_to: inbox/priority/
  - match:
      subject_contains: "URGENT"
    action:
      priority: urgent
      notify_user: true
  - match:
      from: notifications-bot
      older_than_days: 3
    action:
      archive: true
```

The inbox-check hook applies these rules on each scan. Simple enough for a 30-line Python script, powerful enough to prevent urgent messages from getting lost.

### Reply-to header

**Problem:** sometimes the logical reply target isn't the sender. Example: session-alpha sends a question on behalf of the user, and wants replies to go to session-user-proxy, not back to alpha.

**Fix:** a `reply_to` header that overrides `from` as the reply target.

```markdown
---
from: alpha
to: beta
reply_to: user-proxy
subject: "Question from the user"
---
```

Beta's reply goes to `user-proxy/inbox/`, not `alpha/inbox/`. Rare need, but when you need it, you really need it.

### Maintenance: archiving and inbox rot

Inboxes accumulate. A healthy mailbox needs periodic cleanup:

```bash
# Move messages older than 14 days to archive/
find .claude/mailbox -path "*/inbox/*" -name "*.md" -mtime +14 \
  -exec bash -c 'mv "$0" "${0/\/inbox\//\/archive\/}"' {} \;

# Delete receipts older than 30 days (they served their purpose)
find .claude/mailbox -path "*/receipts/*" -name "*.md" -mtime +30 -delete
```

Run weekly as a scheduled task or before session-end. Sent folders should also be rotated periodically.

### Rules against data loss (mailbox-specific)

1. **Never edit another agent's sent/ folder.** It's their audit trail. Status updates go on inbox copies only.
2. **Never delete an unread message.** Archive it if you're sure it's not needed; the sender may still be waiting for an acknowledgment.
3. **Writing is atomic.** Write the whole message file in one Write tool call. Don't append in pieces - the recipient's hook may read a half-written file.
4. **Unique message_id.** Two messages with the same ID create undefined behavior. Use the `YYYYMMDD-HHMMSS-<sender>-<seq>` format and increment `<seq>` within the same second if needed.
5. **Sender-scoped sequence for strict order.** If two messages must arrive in order, use sequential `<seq>` in the `message_id` and let the recipient sort by it.
