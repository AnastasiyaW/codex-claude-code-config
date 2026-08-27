#!/usr/bin/env python3
"""PreToolUse: a mass send that records no message id is a mailing nobody can recall.

Watches Bash/PowerShell for a script that sends Telegram messages to many people -
inline heredoc, or a file piped in with `cat`. Blocks it when the script never
captures `message_id` from the send response.

Why this exists, precisely. On 2026-08-14 a 176-person mailing went out through an
ad-hoc script whose send function was:

    with urllib.request.urlopen(req, timeout=30) as r:
        return 200, ""          # the body, and with it message_id, thrown away

Two hours later it had to be retracted. It could not be, from what we had recorded:
the chat ids were logged and the message ids were not. It was recovered only because
this bot's private-chat message ids happen to come from ONE sequence shared across
every chat, so the block could be reconstructed by arithmetic. That is luck. The next
bot need not behave that way, and the same script would then be unrecallable.

So the rule is not "do not send" - it is "if you send to many people, keep the
receipt". A send whose response is captured can be deleted, edited, audited and
counted; one whose response is discarded can only be regretted.

Deletion and editing are never blocked: retraction must stay easier than sending.

Bypass: `# claude-bypass: mass-send` in the command, or CLAUDE_ALLOW_MASS_SEND=1.
Self-test: python telegram-mass-send-guard.py --self-test
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    allow,
    block,
    bypass,
    read_event,
)

BYPASS_KEY = "mass-send"
BYPASS_ENV = "CLAUDE_ALLOW_MASS_SEND"

# Sending, as opposed to reading or retracting.
SEND_CALL = re.compile(
    r"\b(sendMessage|sendPhoto|sendDocument|sendMediaGroup|copyMessage"
    r"|send_message|send_photo|send_document|answer_photo)\b"
)
# The receipt. Any of these means the response was looked at rather than dropped.
RECORDS_ID = re.compile(
    r"\bmessage_id\b|\bmessageId\b|\btelegram_message_id\b|BroadcastRecipient"
)
# Reaching more than one person: a loop over recipients, or a literal roster.
LOOPS_RECIPIENTS = re.compile(
    r"\bfor\s+\w+\s+in\b|\.map\(|foreach|ForEach-Object", re.IGNORECASE
)
CHAT_ID_LITERAL = re.compile(r"\b\d{6,12}\b")
MANY_LITERAL_IDS = 5

# Nothing here is a send; a script that only retracts or reads must never be held up.
RETRACTION_ONLY = re.compile(
    r"\b(deleteMessage|deleteMessages|editMessageText|editMessageCaption"
    r"|setMessageReaction|getUpdates|getChat)\b"
)


def _heredoc_bodies(command: str) -> list[str]:
    """Every heredoc body in the command, which is where an inline script lives."""
    bodies = []
    for match in re.finditer(r"<<-?\s*'?\"?([A-Za-z_][A-Za-z_0-9]*)'?\"?\s*\n", command):
        marker = match.group(1)
        rest = command[match.end():]
        end = re.search(rf"^\s*{re.escape(marker)}\s*$", rest, re.MULTILINE)
        bodies.append(rest[: end.start()] if end else rest)
    return bodies


def _piped_files(command: str, cwd: str | None) -> list[str]:
    """Contents of files fed into the command with `cat`/`Get-Content`.

    The mailing that caused this was `cat script.py | ssh ... python -`, so the
    text that matters is not in the command at all.
    """
    out = []
    for match in re.finditer(
        r"(?:\bcat\b|\bGet-Content\b)\s+(?:-Raw\s+)?[\"']?([^\s\"'|;&]+)", command
    ):
        raw = match.group(1)
        for candidate in ({Path(raw), Path(cwd or ".") / raw} if cwd else {Path(raw)}):
            try:
                if candidate.is_file() and candidate.stat().st_size < 2_000_000:
                    out.append(candidate.read_text(encoding="utf-8", errors="replace"))
                    break
            except OSError:
                continue
    return out


def _verdict(text: str) -> str | None:
    """Return a reason to block, or None to allow."""
    if not SEND_CALL.search(text):
        return None
    if RECORDS_ID.search(text):
        return None
    reaches_many = bool(LOOPS_RECIPIENTS.search(text)) or (
        len(set(CHAT_ID_LITERAL.findall(text))) >= MANY_LITERAL_IDS
    )
    if not reaches_many:
        return None
    if RETRACTION_ONLY.search(text) and not SEND_CALL.search(text):
        return None
    return (
        "This sends Telegram messages to many recipients and never reads "
        "message_id back from the response.\n\n"
        "A mailing whose message ids were not recorded cannot be retracted, edited "
        "or audited afterwards. That is not hypothetical: on 2026-08-14 a 176-person "
        "mailing was sent this way, had to be recalled two hours later, and was only "
        "recoverable because that bot's private-chat message ids happen to share one "
        "global sequence. Do not rely on that again.\n\n"
        "Do one of these instead:\n"
        "  - send through the bot's own broadcast machinery, which persists "
        "broadcast_recipients.telegram_message_id and can delete by it;\n"
        "  - or, if it must be ad-hoc, capture the response and log "
        "(chat_id, message_id) per recipient before moving on.\n\n"
        "See docs/people-mailings-and-money.md in the bot repo.\n"
        f"Deliberate one-off: add `# claude-bypass: {BYPASS_KEY}` with a reason, "
        f"or set {BYPASS_ENV}=1."
    )


def main() -> None:
    event = read_event()
    tool = event.get("tool_name") or ""
    if tool not in {"Bash", "PowerShell"}:
        allow()
    payload = event.get("tool_input") or {}
    command = payload.get("command") or ""
    if not command:
        allow()
    if bypass(command, BYPASS_KEY, BYPASS_ENV):
        allow()

    cwd = event.get("cwd")
    for text in [command, *_heredoc_bodies(command), *_piped_files(command, cwd)]:
        reason = _verdict(text)
        if reason:
            block(reason)
    allow()


def _self_test() -> int:
    losing = """
import urllib.request
for chat_id in people:
    req = urllib.request.Request(f"https://api.telegram.org/bot{T}/sendMessage", data=d)
    with urllib.request.urlopen(req) as r:
        return 200, ""
"""
    keeping = """
for chat_id in people:
    with urllib.request.urlopen(req) as r:
        body = json.loads(r.read())
    log.write(f"{chat_id} {body['result']['message_id']}\\n")
"""
    retracting = """
for chat, mid in recorded:
    call("deleteMessage", chat_id=chat, message_id=mid)
"""
    one_off = """
call("sendMessage", chat_id=185120390, text="ping")
"""
    roster = """
for x in [316474758, 946837418, 650714652, 5149623226, 212524760, 198955373]:
    call("sendMessage", chat_id=x, text=greeting)
"""
    cases = [
        ("mass send that drops the receipt", losing, True),
        ("mass send that keeps the receipt", keeping, False),
        ("retraction only", retracting, False),
        ("single message", one_off, False),
        ("literal roster, no receipt", roster, True),
        ("unrelated script", "print('hello')", False),
    ]
    failures = 0
    for name, text, should_block in cases:
        blocked = _verdict(text) is not None
        ok = blocked == should_block
        failures += 0 if ok else 1
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: blocked={blocked}")

    heredocs = _heredoc_bodies("ssh host 'python -' <<'PYEOF'\n" + losing + "\nPYEOF\n")
    ok = len(heredocs) == 1 and _verdict(heredocs[0]) is not None
    failures += 0 if ok else 1
    print(f"  [{'ok' if ok else 'FAIL'}] heredoc body is inspected")

    print("self-test:", "PASS" if failures == 0 else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    main()
