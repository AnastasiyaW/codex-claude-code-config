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


def matched_marker(addr, patterns):
    """Return the private-name marker this address matches, or None.

    Deliberately reports WHICH marker matched rather than asserting "personal".
    The shared list mixes people with infrastructure, so a service address like
    ci@<private-host> matches too. Blocking it is right - that name does not
    belong in public commit metadata either - but calling it a personal address
    sends the reader to change user.email where there is nothing to change.
    """
    if not addr or NOREPLY.search(addr):
        return None                       # a noreply address is never personal
    for p in patterns:
        if re.search(p, addr, re.I):
            return p
    return None


def is_personal(addr, patterns):
    return matched_marker(addr, patterns) is not None


class GitFailed(Exception):
    """git refused to answer. Never treat that as 'nothing found'."""


def run(args, required=False):
    """Run git. With required=True a non-zero exit raises instead of yielding ''.

    `git log <base>..<tip>` exits 128 when <base> is not present locally - the
    remote was rewritten and the object was never fetched. Discarding that code
    turns 'I could not look' into 'I looked and it was clean', and the push that
    follows is a --force: the guard would fall silent exactly while history is
    being rewritten, which is when a personal address resurfaces.
    """
    p = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if required and p.returncode != 0:
        raise GitFailed(f"{' '.join(args[:3])}... exit {p.returncode}: "
                        f"{(p.stderr or '').strip()[:160]}")
    return p.stdout


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
        for entry in run(["git", "log"] + args, required=True).splitlines():
            bits = entry.split("\x1f")
            if len(bits) < 3:
                continue
            for addr in (bits[1], bits[2]):
                hit = matched_marker(addr, patterns)
                if hit:
                    # a set: author and committer are usually the same person,
                    # and counting one commit twice misstates the blast radius
                    rec = offenders.setdefault(addr, {"shas": set(), "marker": hit})
                    rec["shas"].add(bits[0][:8])
    return offenders, source


def self_test():
    # Synthetic fixtures only. Real personal markers are loaded from the
    # private routing file at runtime and must not be copied into this public
    # guard's test corpus.
    #
    # This is not a style preference, it is the incident that produced the rule.
    # The first version of this file (1b4c51f, 2026-08-03) used a real address as
    # its fixture, so the guard that refuses to publish a personal email published
    # one -- in its own test. Two days earlier the public-repo scanner had done the
    # identical thing with host names and blocked its own push. Same shape twice:
    # a guard carries an example of what it defends against, and the example is the
    # leak.
    #
    # The addresses below end in `.invalid`, which RFC 2606 reserves precisely so a
    # test can name an address that can never belong to anyone. Reach for that, not
    # for a real one that happens to be in front of you. Nothing here needs to be a
    # working address: the check is a pattern match, and a pattern match cannot tell.
    #
    # The fixture was corrected quietly inside an unrelated commit, which is why this
    # comment exists at all -- a fix nobody can find is a fix that gets undone.
    pats = [r"private\.example", r"ACCOUNT_MARKER", r"test\.handle", r"\btestuser\b"]
    cases = [
        ("123456+ACCOUNT_MARKER@users.noreply.github.com", False,
         "noreply wins over a login that is itself a marker"),
        ("987654+other_account@users.noreply.github.com", False, "noreply, other account"),
        ("private.example@me.invalid", True, "personal address by marker"),
        ("test.handle@gmail.invalid", True, "personal address by marker"),
        ("PRIVATE.EXAMPLE@ME.INVALID", True, "case-insensitive"),
        ("testuser@example.invalid", True, "bare word marker"),
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

    bad += range_tests()
    total = len(cases) + RANGE_CASES
    print(f"\n{total - bad}/{total} passed")
    if not load_patterns()[0]:
        print("note: no name list on this machine - the guard would run INACTIVE here")
    return 1 if bad else 0


RANGE_CASES = 4


def range_tests():
    """Exercise commits_being_added on a real repository.

    This is the function that bit twice - once walking the whole history on a
    new branch, once counting author and committer as two commits - so it gets
    the only tests that can catch a regression: real refs, real ranges.
    """
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="pushguard-")
    bad = 0
    try:
        def git(*a, **kw):
            return subprocess.run(["git", "-C", tmp] + list(a), capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", **kw)

        git("init", "-q", "-b", "main")
        git("config", "user.name", "T")
        git("config", "user.email", "t@example.com")
        shas = []
        for i in range(3):
            with open(os.path.join(tmp, f"f{i}"), "w", encoding="utf-8") as fh:
                fh.write(str(i))
            git("add", "-A")
            git("commit", "-q", "-m", f"c{i}")
            shas.append(git("rev-parse", "HEAD").stdout.strip())
        # a "remote" that already has the first commit
        git("update-ref", "refs/remotes/origin/main", shas[0])

        def count(local, remote):
            args = commits_being_added(local, remote, "origin")
            out = subprocess.run(["git", "-C", tmp, "log"] + args, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
            return len([x for x in out.stdout.splitlines() if x.strip()]), out.returncode

        checks = [
            ("existing branch: only the new commits",
             count(shas[2], shas[0])[0], 2),
            ("new branch: excludes what the remote already has, not the whole history",
             count(shas[2], ZERO)[0], 2),
            ("new branch with nothing new: empty range, no false alarm",
             count(shas[0], ZERO)[0], 0),
        ]
        for why, got, want in checks:
            ok = got == want
            bad += not ok
            print(f"  {'ok  ' if ok else 'FAIL'}  range: {why} (got {got}, want {want})")

        # a base the repository does not have must raise, never return empty
        try:
            run(["git", "-C", tmp, "log", "--format=%H", f"{'0'*39}1..{shas[2]}"],
                required=True)
            ok = False
        except GitFailed:
            ok = True
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  range: missing base raises instead of "
              f"reporting a clean range")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


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

    try:
        offenders, _ = collect(payload, argv[0] if argv else None)
    except GitFailed as exc:
        # fail CLOSED: an unanswerable range is exactly the rewritten-history
        # case, and that is when an address resurfaces
        sys.stderr.write(
            f"\n[pre-push] BLOCKED: could not read the pushed range - {exc}\n\n"
            "This usually means the remote was rewritten and its base object was\n"
            "never fetched. The check could not run, so the push is refused rather\n"
            "than passed: 'I could not look' is not 'I looked and it was clean'.\n\n"
            "  git fetch <remote>      # then push again\n"
            "\nDeliberate override:  CLAUDE_ALLOW_PERSONAL_EMAIL=1 git push ...\n\n")
        return 1

    if offenders:
        sys.stderr.write(
            "\n[pre-push] BLOCKED: these commit addresses match private-name markers.\n\n"
            "Commit metadata in a public repo is readable by anyone through the API:\n"
            "an address plus proven activity is a ready-made phishing target.\n\n")
        for addr, rec in offenders.items():
            ordered = sorted(rec["shas"])
            sample = ", ".join(ordered[:5]) + (" ..." if len(ordered) > 5 else "")
            sys.stderr.write(f"  {addr}  ->  {len(ordered)} commit(s): {sample}\n")
            sys.stderr.write(f"      matched marker: {rec['marker']}\n")
        sys.stderr.write(
            f"\n  (markers loaded from {source})\n"
            "\n  The list mixes people with infrastructure. If the address above is a\n"
            "  person, rewrite the authorship. If it is a service or host name, that\n"
            "  name does not belong in public commit metadata either - change the\n"
            "  address the automation commits under.\n"
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
