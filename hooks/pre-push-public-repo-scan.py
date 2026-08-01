#!/usr/bin/env python3
"""Pre-push guard: two-agent independent secret/PII scan for PUBLIC repos only.

Private repos are skipped. For public repos, TWO independent agents evaluate
the push diff. Both must approve. Either raising an alarm blocks the push.

Agent A — Regex scanner (deterministic, fast, well-known patterns)
Agent B — Claude semantic reviewer (novel patterns, context-aware, PII)

Independence: different failure modes → union covers what each alone misses.
Regex catches obfuscated known formats; LLM catches novel formats + PII.

Invoked by git pre-push hook (core.hooksPath → ~/.claude/scripts/git-hooks/).

Exit codes:
    0  — both agents approve, push allowed
    1  — at least one agent raised alarm, push BLOCKED
    2  — cannot determine repo visibility or other tooling error (fail-closed)
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass


# =============================================================================
# Helpers
# =============================================================================

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    # Explicit UTF-8 + errors=replace: Windows text=True defaults to cp1252,
    # which crashes on non-ASCII bytes in git diff output (Cyrillic, emoji, etc).
    # See skill cyrillic-api-posting for the rule this enforces.
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def get_remote_url(remote: str) -> str | None:
    r = run(["git", "config", "--get", f"remote.{remote}.url"])
    return r.stdout.strip() or None


def parse_github_slug(url: str) -> tuple[str, str] | None:
    """Return (owner, repo) for github.com URLs, or None."""
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not m:
        return None
    return m.group(1), m.group(2)


def repo_is_public(owner: str, repo: str) -> bool | None:
    """Return True/False for public/private. None if gh unavailable."""
    r = run(["gh", "api", f"repos/{owner}/{repo}", "--jq", ".private"])
    if r.returncode != 0:
        return None
    return r.stdout.strip() == "false"


def get_push_diff(remote_ref: str, local_sha: str) -> str:
    """Return diff between remote HEAD and local HEAD."""
    # If remote ref not known (new branch), diff against empty tree
    if remote_ref == "0" * 40 or not remote_ref:
        base = run(["git", "hash-object", "-t", "tree", "/dev/null"]).stdout.strip()
        if not base:
            base = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git empty tree
    else:
        base = remote_ref
    r = run(["git", "diff", f"{base}..{local_sha}"])
    return r.stdout


# =============================================================================
# Agent A — Regex scanner
# =============================================================================

SECRET_PATTERNS = {
    "aws_access_key_id_assign": r"AWS_ACCESS_KEY_ID\s*=\s*([A-Z0-9]{20})",
    "aws_secret_assign": r"AWS_SECRET_ACCESS_KEY\s*=\s*[\"']?([A-Za-z0-9+/]{35,50})[\"']?",
    "aws_akia": r"\b(AKIA[0-9A-Z]{16})\b",
    "github_pat": r"\b(ghp_[A-Za-z0-9]{36,})\b",
    "github_fine_grained": r"\b(github_pat_[A-Za-z0-9_]{80,})\b",
    "stripe_live": r"\b(sk_live_[0-9a-zA-Z]{24,})\b",
    "stripe_test": r"\b(sk_test_[0-9a-zA-Z]{24,})\b",
    "slack_webhook": r"(hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[a-zA-Z0-9]{20,})",
    "slack_token": r"\b(xox[bpar]-[A-Za-z0-9-]{10,})\b",
    "google_api": r"\b(AIza[0-9A-Za-z_\-]{35})\b",
    "cf_tunnel_token": r"\b(eyJhIj[A-Za-z0-9+/=_-]{80,})\b",
    "anthropic_key": r"\b(sk-ant-[A-Za-z0-9\-_]{32,})\b",
    "openai_key": r"\b(sk-(?:proj-)?[A-Za-z0-9]{32,})\b",
    "private_key_block": r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    "generic_long_bearer": r"(?i)\bbearer\s+([A-Za-z0-9._\-=]{40,})",
}

# Your own host names, internal script names and similar identifiers cannot live in
# this file: it is itself published to a public repository, and a scanner that carries
# the list of names it defends is a leak with extra steps. This is not hypothetical --
# an earlier revision hardcoded them, and the scanner blocked its own publication.
#
# So the names are loaded from a local file that is never committed. One token per line,
# `#` for comments. Regex metacharacters are escaped, so plain names are safe to write.
#   default path : ~/.claude/private-hooks/public-scan-private-names.txt
#   override     : CLAUDE_PUBLIC_SCAN_NAMES=<path>
# With no such file the two name-based checks are simply inactive, and the scanner says
# so rather than reporting a clean scan it did not perform.
# If a private config repo is present it already declares this list as its single
# source of truth, and `privacy_markers` there is read by its own split guard. Use
# it rather than starting a second list: one invariant kept in two places drifts,
# and the half that drifts is the half nobody re-reads.
PRIVATE_ROUTING = os.path.expanduser("~/.claude/claude-code-private/routing.json")
PRIVATE_NAMES_FILE = os.environ.get(
    "CLAUDE_PUBLIC_SCAN_NAMES",
    os.path.expanduser("~/.claude/private-hooks/public-scan-private-names.txt"),
)


def _load_private_names() -> list[str]:
    if "CLAUDE_PUBLIC_SCAN_NAMES" not in os.environ:
        try:
            with open(PRIVATE_ROUTING, encoding="utf-8-sig") as fh:
                markers = json.load(fh).get("privacy_markers") or []
            if markers:
                # already regexes by contract in that file
                return [str(m) for m in markers]
        except (OSError, ValueError):
            pass
    try:
        with open(PRIVATE_NAMES_FILE, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        # `re:` prefix passes the rest through as a regex, for families like a
        # numbered host series. Everything else is a literal name and gets escaped,
        # so a dot in a filename cannot quietly become "any character".
        out.append(ln[3:].strip() if ln.startswith("re:") else re.escape(ln))
    return out


# Personal data patterns (for public repos)
PII_PATTERNS = {
    "ssh_private_paths": r"(~/\.ssh/id_[a-z0-9_]+(?!\.pub))",
    "home_user_path": r"(/home/[a-z0-9_-]+/|C:\\Users\\[a-zA-Z0-9_-]+\\|/Users/[a-zA-Z0-9_-]+/)",
    "ssh_ports_internal": r"\bssh\s+.*-p\s+(2222|4000[0-7])\b",
}

_PRIVATE_NAMES = _load_private_names()
if _PRIVATE_NAMES:
    PII_PATTERNS["private_names"] = r"\b(" + "|".join(_PRIVATE_NAMES) + r")\b"


@dataclass
class Finding:
    file_hint: str
    line: int
    pattern: str
    preview: str
    kind: str  # "secret" or "pii"


def agent_a_regex(diff: str) -> list[Finding]:
    """Scan added lines (+) for credential/PII patterns."""
    findings: list[Finding] = []
    current_file = "?"
    line_no = 0
    for line in diff.splitlines():
        # Track current file
        m = re.match(r"^\+\+\+ b/(.+)", line)
        if m:
            current_file = m.group(1)
            line_no = 0
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
        if m:
            line_no = int(m.group(1)) - 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            line_no += 1
            added = line[1:]
            for name, pat in SECRET_PATTERNS.items():
                m2 = re.search(pat, added)
                if m2:
                    val = m2.group(1) if m2.groups() else m2.group(0)
                    findings.append(Finding(
                        file_hint=current_file, line=line_no, pattern=name,
                        preview=val[:6] + "..." if len(val) > 6 else val,
                        kind="secret",
                    ))
            for name, pat in PII_PATTERNS.items():
                m2 = re.search(pat, added)
                if m2:
                    findings.append(Finding(
                        file_hint=current_file, line=line_no, pattern=f"pii:{name}",
                        preview=(m2.group(0))[:40],
                        kind="pii",
                    ))
        elif line.startswith(" ") or line.startswith("-"):
            line_no += 0 if line.startswith("-") else 1
    return findings


# =============================================================================
# Agent B — Claude semantic reviewer (non-blocking fallback to regex-only if unavailable)
# =============================================================================

AGENT_B_PROMPT = """You are a security-review agent. Your task: given a git diff being pushed to a PUBLIC repository, answer whether it is safe to push.

BLOCK criteria (any one = unsafe):
- Any credential (API key, token, password, private key, service secret)
- Internal hostnames, SSH ports, script names that leak infrastructure topology
- Personal email addresses, phone numbers, addresses of real people
- Paths under /home/USER/, C:\\Users\\USER\\ revealing developer identity
- Database connection strings with passwords
- Cloud storage bucket names with access details
- Any value that looks like a random alphanumeric string ≥32 chars (likely token)
- Base64 blobs ≥100 chars (may encode secrets)

ALLOW criteria (all must hold):
- Only generic code, docs, config templates with placeholder values
- Environment variable NAMES (not values)
- References to services by domain (docs.example.com ok) without credentials

Respond with EXACTLY ONE LINE JSON: {"verdict": "SAFE" | "BLOCK", "reason": "brief one-line"}

Diff follows:
---
"""


def find_claude_cli() -> str | None:
    """Locate a runnable Claude Code CLI, whether or not it is on PATH.

    On Windows the desktop app keeps the CLI in a versioned, non-PATH dir
    (%APPDATA%/Claude/claude-code/<version>/claude.exe), which is why a bare
    `where claude` misses it and Agent B silently degraded. We resolve the real
    .exe (subprocess list-form cannot launch a .cmd shim) of the newest SEMANTIC
    version (dir mtimes are unreliable), then fall back to PATH / ~/.local/bin.
    """
    def _ver(path: str):
        name = os.path.basename(os.path.dirname(path))
        try:
            return tuple(int(x) for x in name.split("."))
        except ValueError:
            return (0,)

    appdata = os.environ.get("APPDATA")
    if appdata:
        cands = glob.glob(os.path.join(appdata, "Claude", "claude-code", "*", "claude.exe"))
        if cands:
            return max(cands, key=_ver)
    p = shutil.which("claude")
    if p and p.lower().endswith(".exe"):
        return p
    for c in (os.path.expanduser("~/.local/bin/claude.exe"),
              os.path.expanduser("~/.local/bin/claude")):
        if os.path.isfile(c):
            return c
    return p  # last resort (may be a .cmd shim; only usable where the shell runs it)


def agent_b_claude(diff: str) -> dict | None:
    """Invoke Claude subprocess for semantic review. Returns None if unavailable."""
    claude = find_claude_cli()
    if not claude:
        return None
    # Truncate very long diffs to avoid context blowup
    payload = diff if len(diff) < 120_000 else diff[:120_000] + "\n[... diff truncated for review ...]"
    prompt = AGENT_B_PROMPT + payload
    # Pipe prompt via stdin instead of argv: Windows command-line limit is
    # ~32K characters, so large diffs (200+ lines) overflow when passed as
    # `claude -p <prompt>`. Stdin avoids the limit entirely.
    r = run([claude, "-p", "--output-format", "text"], input=prompt, timeout=120)
    if r.returncode != 0:
        # Distinguish "found but errored" (e.g. not logged in) from "not found",
        # so the failure is legible instead of mislabeled as missing.
        first = (r.stdout or r.stderr or "").strip().splitlines()
        hint = first[0] if first else "unknown error"
        print(f"[pre-push] Agent B: claude CLI found ({claude}) but call failed: {hint}",
              file=sys.stderr)
        return None
    out = r.stdout.strip()
    # Extract JSON from response
    m = re.search(r'\{"verdict"\s*:\s*"(SAFE|BLOCK)"\s*,\s*"reason"\s*:\s*"([^"]+)"\}', out)
    if not m:
        return None
    return {"verdict": m.group(1), "reason": m.group(2)}


# =============================================================================
# Main
# =============================================================================

BYPASS_MARKER = "claude-bypass-prepush:"


def is_user_bypass() -> bool:
    """Allow bypass via commit message marker or env var."""
    if os.environ.get("CLAUDE_ALLOW_PUSH") == "1":
        return True
    # Check last commit message for bypass marker
    r = run(["git", "log", "-1", "--pretty=%B"])
    if BYPASS_MARKER in r.stdout:
        return True
    return False


def main() -> int:
    # stdin: <local_ref> <local_sha> <remote_ref> <remote_sha> (per line)
    remote_name = sys.argv[1] if len(sys.argv) > 1 else "origin"
    remote_url = sys.argv[2] if len(sys.argv) > 2 else (get_remote_url(remote_name) or "")

    slug = parse_github_slug(remote_url)
    if not slug:
        # Non-GitHub remote — skip (could extend later)
        return 0

    owner, repo = slug

    is_public = repo_is_public(owner, repo)
    if is_public is None:
        # gh unavailable/unauth -> can't confirm visibility. Policy: "just work,
        # but never leak to a possibly-public repo." Run the deterministic regex
        # scan and block ONLY on a real finding; allow clean pushes. No blanket
        # fail-closed (that would break private pushes), no LLM agent (visibility
        # unknown so we can't justify the cost/uncertainty).
        print(f"[pre-push] cannot confirm visibility of {owner}/{repo} (gh missing/unauth) - regex-scanning to be safe", file=sys.stderr)
        unknown_visibility = True
    elif not is_public:
        # Confirmed PRIVATE -> allow freely. Only PUBLIC repos are the hard line.
        return 0
    else:
        unknown_visibility = False
        print(f"[pre-push] {owner}/{repo} is PUBLIC - running 2-agent scan...", file=sys.stderr)

    # Say which checks are actually armed. A scan that reports clean while one of its
    # checks was never loaded is the silent-pass failure this whole guard exists against.
    if _PRIVATE_NAMES:
        source = (PRIVATE_NAMES_FILE if "CLAUDE_PUBLIC_SCAN_NAMES" in os.environ
                  else (PRIVATE_ROUTING if os.path.exists(PRIVATE_ROUTING)
                        else PRIVATE_NAMES_FILE))
        print(f"[pre-push] private-name check armed: {len(_PRIVATE_NAMES)} pattern(s) "
              f"from {source}", file=sys.stderr)
    else:
        print(f"[pre-push] NOTE: private-name check INACTIVE - no list at "
              f"{PRIVATE_NAMES_FILE}. Host and internal script names will not be "
              f"detected. Create the file (one name per line) to arm it.", file=sys.stderr)

    # Read stdin for push refs; find SHAs
    push_lines = sys.stdin.read().splitlines()
    if not push_lines:
        # Called manually without stdin — scan against origin/HEAD
        local_sha = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        remote_ref = run(["git", "rev-parse", f"{remote_name}/HEAD"]).stdout.strip() or ""
        diff = get_push_diff(remote_ref, local_sha)
    else:
        # Concatenate diffs of all pushed refs
        diffs = []
        for line in push_lines:
            parts = line.split()
            if len(parts) < 4:
                continue
            local_sha, remote_sha = parts[1], parts[3]
            if local_sha == "0" * 40:
                continue  # delete
            diffs.append(get_push_diff(remote_sha, local_sha))
        diff = "\n".join(diffs)

    if not diff.strip():
        print("[pre-push] empty diff — skipping", file=sys.stderr)
        return 0

    # --- Agent A ---
    a_findings = agent_a_regex(diff)
    if a_findings:
        print(f"\n[pre-push] ❌ Agent A (regex) BLOCKED — {len(a_findings)} finding(s):", file=sys.stderr)
        for f in a_findings[:20]:
            print(f"  [{f.kind:6s}] {f.pattern:28s} in {f.file_hint}:{f.line} → {f.preview}", file=sys.stderr)
        if is_user_bypass():
            print("[pre-push] ⚠️  bypass active — proceeding despite Agent A findings", file=sys.stderr)
        else:
            print("\n[pre-push] rotate leaked values, redact, retry.", file=sys.stderr)
            print("[pre-push] bypass (careful!): add 'claude-bypass-prepush: <reason>' to commit message", file=sys.stderr)
            return 1

    # Visibility unknown -> Agent A regex was the safety net; clean means allow.
    if unknown_visibility:
        print("[pre-push] regex scan clean (visibility unknown) - push allowed", file=sys.stderr)
        return 0

    # --- Agent B ---
    print(f"[pre-push] Agent A passed, invoking Agent B (Claude semantic)...", file=sys.stderr)
    b_result = agent_b_claude(diff)
    if b_result is None:
        print(f"[pre-push] ⚠️  Agent B unavailable (claude CLI missing or timeout). Falling back to Agent A only.", file=sys.stderr)
        print(f"[pre-push] ✅ push allowed (Agent A clean)", file=sys.stderr)
        return 0
    if b_result["verdict"] == "BLOCK":
        print(f"\n[pre-push] ❌ Agent B (Claude) BLOCKED — {b_result['reason']}", file=sys.stderr)
        if is_user_bypass():
            print("[pre-push] ⚠️  bypass active — proceeding despite Agent B finding", file=sys.stderr)
        else:
            return 1

    print(f"[pre-push] ✅ both agents passed — push allowed", file=sys.stderr)
    return 0


def self_test() -> int:
    """Prove the name check arms, escapes literals, and stays absent without a list.

    A guard installed from a repository has to be verifiable on the machine that
    installed it -- "the file is present" is not the same as "the check runs".
    """
    import tempfile

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    with tempfile.TemporaryDirectory() as td:
        listing = os.path.join(td, "names.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            fh.write("# comment\nexample-host\nrunner_tool.py\nre:node-\\d+\n\n")
        # The loader prefers the private routing file unless an explicit override is
        # set, so the override must be set here or this exercises the wrong branch --
        # which is exactly what the first version of this self-test did.
        global PRIVATE_NAMES_FILE
        saved = PRIVATE_NAMES_FILE
        saved_env = os.environ.get("CLAUDE_PUBLIC_SCAN_NAMES")
        try:
            os.environ["CLAUDE_PUBLIC_SCAN_NAMES"] = listing
            PRIVATE_NAMES_FILE = listing
            names = _load_private_names()
        finally:
            PRIVATE_NAMES_FILE = saved
            if saved_env is None:
                os.environ.pop("CLAUDE_PUBLIC_SCAN_NAMES", None)
            else:
                os.environ["CLAUDE_PUBLIC_SCAN_NAMES"] = saved_env

        print("parsing:")
        check("comments and blanks dropped", len(names), 3)
        pat = re.compile(r"\b(" + "|".join(names) + r")\b")
        print("matching:")
        check("plain name matches", bool(pat.search("ssh example-host uptime")), True)
        check("filename matches", bool(pat.search("./runner_tool.py")), True)
        check("re: family matches", bool(pat.search("node-42 is down")), True)
        check("dot is escaped, not any-char", bool(pat.search("runner_toolXpy")), False)
        check("unrelated text clean", bool(pat.search("nothing to see")), False)

        print("absent list:")
        saved_env = os.environ.get("CLAUDE_PUBLIC_SCAN_NAMES")
        try:
            missing = os.path.join(td, "does-not-exist.txt")
            os.environ["CLAUDE_PUBLIC_SCAN_NAMES"] = missing
            PRIVATE_NAMES_FILE = missing
            check("missing file yields no names", _load_private_names(), [])
        finally:
            PRIVATE_NAMES_FILE = saved
            if saved_env is None:
                os.environ.pop("CLAUDE_PUBLIC_SCAN_NAMES", None)
            else:
                os.environ["CLAUDE_PUBLIC_SCAN_NAMES"] = saved_env

        print("source preference:")
        if os.path.exists(PRIVATE_ROUTING):
            check("private routing wins when no override is set",
                  len(_load_private_names()) > 0, True)
        else:
            print("  [skip] no private routing file on this machine")

    print("baseline patterns present:")
    for name in ("ssh_private_paths", "home_user_path", "ssh_ports_internal"):
        check(name, name in PII_PATTERNS, True)

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[pre-push] internal error: {e}", file=sys.stderr)
        # Fail-closed on exception — safer to block than allow
        sys.exit(2)
