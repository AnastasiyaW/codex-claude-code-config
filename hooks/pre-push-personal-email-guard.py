#!/usr/bin/env python3
"""pre-push: refuse to publish commits authored with a personal email address.

Why this exists
---------------
Commit metadata in a public repository is readable by anyone through the API,
without cloning: an address plus proven activity is a ready-made phishing target.
GitHub's own "Block command line pushes that expose my email" is a per-account web
setting that no script can enable, and it only covers GitHub. This is the local
equivalent and it applies to every remote.

Where the addresses come from
-----------------------------
Not from here. A guard that hard-codes the names it defends against carries them
into the public tree itself — the failure this repository already hit once, when
the public-repo scanner shipped with real hostnames baked into its own patterns.

So the list is loaded, in order:
  1. CLAUDE_PERSONAL_EMAILS=<path>          - explicit override, one token per line
  2. ~/.claude/claude-code-private/routing.json -> privacy_markers
     (already declared the single source of truth for private names; do not start
     a second list beside it - one invariant in two places drifts, and the half
     that drifts is the half nobody re-reads)
  3. ~/.claude/private-hooks/personal-emails.txt - plain fallback for a machine
     with no private config repo
With no list the check is INACTIVE and says so on every run. A scanner reporting
a clean pass for a check it never performed is the exact silent success this file
exists to prevent.

A `@users.noreply.github.com` address is never personal and is always allowed —
it must be checked first, because such an address embeds the account login and a
login is itself a privacy marker.

Behaviour
---------
  * fail OPEN on internal error - a bug here must never wedge every push
  * fail CLOSED on a real match - that is the whole point
  * chains to the repository's own .git/hooks/pre-push, because a global
    core.hooksPath otherwise silently disables project hooks

Override:  CLAUDE_ALLOW_PERSONAL_EMAIL=1 git push ...
Self-test: python pre-push-personal-email-guard.py --self-test
"""
import json
import os
import re
import subprocess
import sys

ZERO = "0" * 40
NOREPLY = re.compile(r"@users\.noreply\.github\.com$", re.I)

PRIVATE_ROUTING = os.path.expanduser("~/.claude/claude-code-private/routing.json")
FALLBACK_FILE = os.environ.get(
    "CLAUDE_PERSONAL_EMAILS",
    os.path.expanduser("~/.claude/private-hooks/personal-emails.txt"),
)


def load_patterns():
    """Return (patterns, source). Empty list means: check is inactive."""
    if "CLAUDE_PERSONAL_EMAILS" not in os.environ:
        try:
            with open(PRIVATE_ROUTING, encoding="utf-8-sig") as fh:
                markers = json.load(fh).get("privacy_markers") or []
            if markers:
                return [str(m) for m in markers], PRIVATE_ROUTING
        except (OSError, ValueError):
            pass
    try:
        with open(FALLBACK_FILE, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return [], None
    out = []
    for ln in lines:
        ln = ln.split("#", 1)[0].strip()
        if ln:
            out.append(re.escape(ln))
    return out, FALLBACK_FILE


def is_personal(addr, patterns):
    if not addr or NOREPLY.search(addr):
        return False                      # a noreply address is never personal
    return any(re.search(p, addr, re.I) for p in patterns)


def run(args):
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def chain_local_hook(argv, payload):
    git_dir = run(["git", "rev-parse", "--git-dir"]).strip()
    if not git_dir:
        return 0
    local = os.path.join(git_dir, "hooks", "pre-push")
    if not os.path.isfile(local):
        return 0
    try:
        return subprocess.run(["sh", local] + argv, input=payload, text=True,
                              encoding="utf-8", errors="replace").returncode
    except OSError:
        return 0


def commits_being_added(local_sha, remote_sha, remote_name):
    """Only the commits this push actually introduces.

    A brand-new branch reports remote_sha as zeroes. Reading that as "everything
    reachable from local_sha" walks the entire history and blames the push for
    every address any contributor ever used - 392 commits on this repository the
    first time it ran. Exclude what the remote already has instead.
    """
    if remote_sha != ZERO:
        return ["--format=%H%x1f%ae%x1f%ce", f"{remote_sha}..{local_sha}"]
    return ["--format=%H%x1f%ae%x1f%ce", local_sha,
            "--not", f"--remotes={remote_name or 'origin'}"]


def collect(payload, remote_name=None):
    """sha -> offending addresses, for every commit this push introduces."""
    patterns, source = load_patterns()
    if not patterns:
        return {}, None
    offenders = {}
    for line in payload.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if local_sha == ZERO:
            continue                                   # branch deletion
        args = commits_being_added(local_sha, remote_sha, remote_name)
        for entry in run(["git", "log"] + args).splitlines():
            bits = entry.split("\x1f")
            if len(bits) < 3:
                continue
            for addr in (bits[1], bits[2]):
                if is_personal(addr, patterns):
                    # a set: author and committer are usually the same person,
                    # and counting one commit twice misstates the blast radius
                    offenders.setdefault(addr, set()).add(bits[0][:8])
    return offenders, source


def self_test():
    pats = [r"black\.design", r"Anastasiya1551", r"navok\.1\.3", r"\bnastya\b"]
    cases = [
        ("165185905+Anastasiya1551@users.noreply.github.com", False,
         "noreply wins over a login that is itself a marker"),
        ("92753226+happy_in_happy@users.noreply.github.com", False, "noreply, other account"),
        ("black.design@me.com", True, "personal address by marker"),
        ("navok.1.3@gmail.com", True, "personal address by marker"),
        ("BLACK.DESIGN@ME.COM", True, "case-insensitive"),
        ("nastya@example.com", True, "bare word marker"),
        ("ci-bot@example.com", False, "unrelated address passes"),
        ("", False, "empty address is not a match"),
        ("noreply@github.com", False, "github noreply without the user prefix"),
    ]
    bad = 0
    for addr, want, why in cases:
        got = is_personal(addr, pats)
        ok = got == want
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {addr or '(empty)':52} {why}")
    print(f"\n{len(cases) - bad}/{len(cases)} passed")
    if not load_patterns()[0]:
        print("note: no name list on this machine - the guard would run INACTIVE here")
    return 1 if bad else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()

    argv, payload = sys.argv[1:], sys.stdin.read()
    if os.environ.get("CLAUDE_ALLOW_PERSONAL_EMAIL") == "1":
        return chain_local_hook(argv, payload)

    patterns, source = load_patterns()
    if not patterns:
        sys.stderr.write(
            "[pre-push] personal-email check INACTIVE: no name list found.\n"
            f"           looked at {PRIVATE_ROUTING}\n"
            f"           and       {FALLBACK_FILE}\n"
            "           This push was NOT checked for personal addresses.\n")
        return chain_local_hook(argv, payload)

    offenders, _ = collect(payload, argv[0] if argv else None)
    if offenders:
        sys.stderr.write(
            "\n[pre-push] BLOCKED: these commits carry a personal email address.\n\n"
            "Commit metadata in a public repo is readable by anyone through the API:\n"
            "an address plus proven activity is a ready-made phishing target.\n\n")
        for addr, shas in offenders.items():
            ordered = sorted(shas)
            sample = ", ".join(ordered[:5]) + (" ..." if len(ordered) > 5 else "")
            sys.stderr.write(f"  {addr}  ->  {len(ordered)} commit(s): {sample}\n")
        sys.stderr.write(
            f"\n  (names loaded from {source})\n"
            "\nFix:\n"
            "  git config --global user.email \"<id>+<login>@users.noreply.github.com\""
            "   # id: gh api users/<login> --jq .id\n"
            "  git rebase <base> --exec 'git commit --amend --no-edit --reset-author'\n"
            "  git commit --amend --reset-author        # last commit only\n"
            "\nDeliberate override:  CLAUDE_ALLOW_PERSONAL_EMAIL=1 git push ...\n\n")
        return 1

    return chain_local_hook(argv, payload)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                      # fail OPEN, loudly
        sys.stderr.write(f"[pre-push] guard error, allowing push: {exc}\n")
        sys.exit(0)
