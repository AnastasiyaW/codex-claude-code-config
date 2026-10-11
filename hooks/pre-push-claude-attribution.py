#!/usr/bin/env python3
"""git pre-push hook: block any push that carries Claude/Anthropic
attribution in the commit messages being uploaded.

Why this exists
---------------
The PreToolUse `claude-attribution-guard.py` hook catches `git commit`
and `gh pr create` calls inside a Claude Code session, but it cannot
see:

  - Commits made from a plain terminal without Claude Code
  - Commits made by other tools (IDE git integrations, GUI clients,
    `git commit --amend` outside a session)
  - Commits authored before this rule was adopted that are now being
    pushed for the first time

This hook runs at the git layer and inspects every commit in the push
range (`<remote_sha>..<local_sha>`) for forbidden attribution patterns.
It is the final gate before the commits reach the remote.

Installation
------------
1. Place this file at a stable path, e.g. `~/.claude/scripts/`.
2. Create a wrapper at `~/.claude/scripts/git-hooks/pre-push`:

       #!/bin/bash
       set -e
       STDIN_DATA="$(cat)"
       echo "$STDIN_DATA" | python ~/.claude/scripts/pre-push-claude-attribution.py

   `chmod +x ~/.claude/scripts/git-hooks/pre-push`

3. Register globally:

       git config --global core.hooksPath ~/.claude/scripts/git-hooks

Now every `git push` from this machine passes through the scan.

Stdin format
------------
git supplies one or more lines:

    <local_ref> <local_sha> <remote_ref> <remote_sha>

For each line the script enumerates commits in
`(remote_sha..local_sha]` and looks for attribution patterns in commit
message bodies.

Exit codes
----------
    0 — no attribution found, push allowed
    1 — at least one commit has attribution, push BLOCKED

Bypass
------
Env var only (in-command bypass markers don't apply at git level):

    CLAUDE_ALLOW_PUSH_ATTRIBUTION=1 git push ...

Related
-------
- `claude-attribution-guard.py` — PreToolUse companion that catches
  commits before they happen.
- `rules/no-claude-attribution.md` — full policy and rationale.
- `rules/safety-billing.md` — HERMES.md / ANTHROPIC_API_KEY context.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ATTRIBUTION_PATTERNS = [
    r"Co-Authored-By:\s*Claude\b",
    r"Co-Authored-By:\s*[Aa]nthropic\b",
    r"\bnoreply@anthropic\.com\b",
    r"🤖\s+Generated\s+with\s+(\[?Claude\s+Code\]?|claude\.ai)",
    r"Generated\s+with\s+claude\.ai/code",
    r"Generated\s+with\s+Anthropic",
    r"Authored\s+by\s+Claude\b",
    r"Made\s+with\s+Claude\b",
]

NULL_SHA = "0" * 40


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def commits_in_range(remote_sha: str, local_sha: str) -> list[tuple[str, str]]:
    """Return [(sha, full_message_body), ...] for commits in remote..local.

    For a brand-new branch (remote_sha is all zeros) we list commits
    reachable from local_sha that are not on any other remote, capped at
    200 so we never scan the full history of a fresh fork.
    """
    if remote_sha == NULL_SHA:
        revs_cmd = [
            "git", "log",
            "--not", "--remotes",
            "--pretty=format:%H%x1f%B%x1e",
            local_sha,
            "-200",
        ]
    else:
        # only what the server does not have yet: after `git merge origin/main` the range also holds main's
        # commits, already pushed by someone else and not this push's to fix (Iliukhina, Vikunja 969 c2702)
        revs_cmd = [
            "git", "log",
            "--pretty=format:%H%x1f%B%x1e",
            f"{remote_sha}..{local_sha}",
            "--not", "--remotes",
        ]

    r = run(revs_cmd)
    if r.returncode != 0:
        print(
            f"[pre-push-attribution] WARN: git log failed: {r.stderr.strip()}",
            file=sys.stderr,
        )
        return []

    out = []
    for entry in r.stdout.split("\x1e"):
        entry = entry.strip("\n ")
        if not entry or "\x1f" not in entry:
            continue
        sha, body = entry.split("\x1f", 1)
        out.append((sha.strip(), body.strip()))
    return out


def find_attribution_in_body(body: str) -> str | None:
    for pat in ATTRIBUTION_PATTERNS:
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def main() -> int:
    if os.environ.get("CLAUDE_ALLOW_PUSH_ATTRIBUTION", "").lower() in {
        "1", "true", "yes", "on"
    }:
        return 0

    offenders: list[tuple[str, str, str, str]] = []  # ref, sha, hit, subject

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        local_ref, local_sha, _remote_ref, remote_sha = parts[:4]

        # Deletion push: nothing to scan
        if local_sha == NULL_SHA:
            continue

        for sha, body in commits_in_range(remote_sha, local_sha):
            hit = find_attribution_in_body(body)
            if hit:
                subject = body.splitlines()[0][:80] if body else ""
                offenders.append((local_ref, sha, hit, subject))

    if not offenders:
        return 0

    eprint = lambda s="": print(s, file=sys.stderr)
    eprint("")
    eprint("=" * 72)
    eprint("PUSH BLOCKED — Claude/Anthropic attribution detected in commit messages")
    eprint("=" * 72)
    eprint("")
    eprint("Policy: rules/no-claude-attribution.md forbids")
    eprint("  Co-Authored-By: Claude / 🤖 Generated with Claude Code / similar")
    eprint("in commits to:")
    eprint("  1. Avoid harness-detection regex surface (Issue #53262 HERMES.md class)")
    eprint("  2. Keep git blame and audit logs clean")
    eprint("  3. Avoid leaking AI-tool usage into shared/public history")
    eprint("")
    eprint("Offending commits:")
    seen = set()
    for ref, sha, hit, subject in offenders[:20]:
        key = (sha, hit)
        if key in seen:
            continue
        seen.add(key)
        eprint(f"  {sha[:10]}  match={hit!r}")
        if subject:
            eprint(f"             subject: {subject}")
    if len(offenders) > 20:
        eprint(f"  ... and {len(offenders) - 20} more")
    eprint("")
    eprint("How to proceed:")
    eprint("  - For a small number of new commits: rebase interactively")
    eprint("      git rebase -i <base>  # mark commits 'reword' and drop the footer")
    eprint("  - For bulk cleanup of past history: run history-rewrite tooling")
    eprint("    such as `git-filter-repo --message-callback ...` (destructive,")
    eprint("    make a backup branch first).")
    eprint("  - For an explicit user-approved exception (rare):")
    eprint("      CLAUDE_ALLOW_PUSH_ATTRIBUTION=1 git push ...")
    eprint("")
    return 1


if __name__ == "__main__":
    sys.exit(main())
