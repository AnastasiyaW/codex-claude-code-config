#!/usr/bin/env python3
"""PostToolUse: verify destructive operations actually completed.

The fifth and final step of the user's workflow:
  1. Спросить дважды (require_human_confirmation)
  2. Сделать бэкап (pre_db_snapshot, pre_fs_snapshot, pre_cloud_snapshot)
  3. Удостовериться что бэкап валиден (verify in pre_*_snapshot hooks)
  4. Удалить (the actual command)
  5. **Проверить что реально удалили** ← this hook

Why this exists
===============
"Command exit 0" ≠ "thing is gone". Possible failure modes that look like
success:
  - rm on a path with permission denied for some files (some files remain)
  - docker rm on stopped container that's actually paused (no-op success)
  - kubectl delete with --grace-period=0 but resource finalizer hangs
  - DROP TABLE that hits a deferred constraint and rolls back silently
  - curl DELETE returning 200 but body says "scheduled, not yet processed"

This hook performs an after-the-fact existence check based on the command
shape. Cannot prevent (already executed), but logs verdict and emits warning
if target is still present — gives Claude a signal to NOT report "done"
when the proof says otherwise.

Verdict values logged to safety.log
====================================
  verified-deleted   — target confirmed gone
  still-present      — target still exists (loud WARN)
  could-not-verify   — recognized destructive intent but no verify strategy
  not-applicable     — non-destructive command (silent pass)

Output behavior
===============
This hook is a PostToolUse hook. It cannot block (the action already ran).
Output goes to stderr where it appears in the agent's tool result, prompting
attention to mismatched expectations.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import log, read_event  # noqa: E402


def warn(msg: str) -> None:
    sys.stderr.write(f"[verify_deleted] {msg}\n")


def info(msg: str) -> None:
    # Quiet output for verified-OK case — agents see it but it's not loud
    sys.stderr.write(f"[verify_deleted] {msg}\n")


# =============================================================================
# Per-command verify strategies
# Each takes the command string and returns (verdict, details).
# verdict ∈ {"verified-deleted", "still-present", "could-not-verify"}
# =============================================================================

def verify_rm(cmd: str) -> tuple[str, str]:
    """For rm/rmdir: each target should not exist anymore."""
    cmd_no_comments = re.sub(r"#[^\n]*", "", cmd)
    try:
        tokens = shlex.split(cmd_no_comments, posix=True)
    except ValueError:
        return "could-not-verify", "shlex parse failed"

    targets: list[str] = []
    rm_seen = False
    for tok in tokens:
        if tok in ("rm", "rmdir") or tok.endswith("/rm") or tok.endswith("/rmdir"):
            rm_seen = True
            continue
        if not rm_seen:
            continue
        if tok.startswith("-"):
            continue
        if tok in (";", "&&", "||", "|", "&"):
            rm_seen = False
            continue
        targets.append(tok)

    if not targets:
        return "could-not-verify", "no targets extracted"

    still_present = []
    for t in targets:
        # Skip glob patterns — can't reliably check
        if any(c in t for c in "*?["):
            continue
        # Skip env-var paths
        if "$" in t:
            continue
        p = Path(t).expanduser()
        if p.exists():
            still_present.append(str(p))

    if still_present:
        sample = ", ".join(still_present[:3])
        more = f" (+{len(still_present) - 3} more)" if len(still_present) > 3 else ""
        return "still-present", f"{sample}{more}"
    return "verified-deleted", f"{len(targets)} target(s) gone"


def verify_move(cmd: str) -> tuple[str, str]:
    """For move-style commands, verify the local source is gone."""
    cmd_no_comments = re.sub(r"#[^\n]*", "", cmd)
    try:
        tokens = shlex.split(cmd_no_comments, posix=True)
    except ValueError:
        return "could-not-verify", "shlex parse failed"

    source: str | None = None
    lowered = [token.lower() for token in tokens]
    if "move-item" in lowered:
        for flag in ("-path", "-literalpath"):
            if flag in lowered:
                index = lowered.index(flag)
                if index + 1 < len(tokens):
                    source = tokens[index + 1]
                break
    elif "robocopy" in lowered and any(re.fullmatch(r"/(?:move|mov)", token, re.I) for token in tokens):
        index = lowered.index("robocopy")
        if index + 2 < len(tokens):
            source = tokens[index + 1]
    else:
        for name in ("mv",):
            if name in lowered:
                index = lowered.index(name)
                args = [token for token in tokens[index + 1:] if not token.startswith("-")]
                if len(args) >= 2:
                    source = args[0]
                break

    if not source or any(mark in source for mark in "*?[$"):
        return "could-not-verify", "local move source could not be extracted"
    if re.match(r"^(?:[a-z]+://|[^\\/\s]+@[^\\/\s:]+:)", source, re.I):
        return "could-not-verify", "remote move source requires contract evidence"
    path = Path(source).expanduser()
    if path.exists():
        return "still-present", f"move source still exists: {path}"
    return "verified-deleted", f"move source gone: {path}"


def verify_docker_rm(cmd: str) -> tuple[str, str]:
    """docker rm <container> — check `docker ps -a` doesn't list it."""
    if not shutil.which("docker"):
        return "could-not-verify", "docker not in PATH"
    m = re.search(r"\bdocker\s+(?:rm|rmi|volume\s+rm|network\s+rm)\s+(?:-[a-zA-Z]+\s+)*(.+?)(?:$|\|)", cmd)
    if not m:
        return "could-not-verify", "could not extract container name"
    raw = m.group(1).strip()
    names = [n for n in raw.split() if not n.startswith("-")]
    if not names:
        return "could-not-verify", "no container names extracted"

    list_cmd = "docker ps -a --format '{{.Names}}'"
    if "rmi" in cmd:
        list_cmd = "docker images --format '{{.Repository}}:{{.Tag}}'"
    elif "volume rm" in cmd:
        list_cmd = "docker volume ls --format '{{.Name}}'"
    elif "network rm" in cmd:
        list_cmd = "docker network ls --format '{{.Name}}'"

    try:
        proc = subprocess.run(list_cmd, shell=True, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return "could-not-verify", f"docker list exit {proc.returncode}: {proc.stderr.strip()[:120]}"
        listed = set(line for line in proc.stdout.strip().split("\n") if line)
    except (subprocess.TimeoutExpired, OSError) as e:
        return "could-not-verify", f"list failed: {e}"

    still_present = [n for n in names if n in listed]
    if still_present:
        return "still-present", f"docker resources still listed: {', '.join(still_present)}"
    return "verified-deleted", f"all {len(names)} resource(s) absent from docker"


def verify_kubectl_delete(cmd: str) -> tuple[str, str]:
    """kubectl delete <type> <name> — kubectl get should NotFound."""
    if not shutil.which("kubectl"):
        return "could-not-verify", "kubectl not in PATH"
    m = re.search(r"\bkubectl\s+delete\s+(\w+)\s+(\S+)", cmd)
    if not m:
        return "could-not-verify", "could not parse kubectl delete syntax"
    rtype, rname = m.group(1), m.group(2)
    try:
        proc = subprocess.run(
            ["kubectl", "get", rtype, rname],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0 and "NotFound" in (proc.stderr + proc.stdout):
            return "verified-deleted", f"kubectl get {rtype}/{rname} → NotFound"
        if proc.returncode == 0:
            return "still-present", f"kubectl get {rtype}/{rname} still returns the resource"
        return "could-not-verify", f"kubectl get exit {proc.returncode}"
    except (subprocess.TimeoutExpired, OSError) as e:
        return "could-not-verify", f"kubectl get failed: {e}"


def verify_curl_delete(cmd: str) -> tuple[str, str]:
    """curl -X DELETE <url> — GET <url> should be 404 or similar."""
    if not shutil.which("curl"):
        return "could-not-verify", "curl not in PATH"
    m = re.search(r"https?://[^\s\"';|]+", cmd)
    if not m:
        return "could-not-verify", "no URL extracted"
    url = m.group(0)
    # Sanitize: only HTTPS to avoid arbitrary fetch
    if not url.startswith("https://"):
        return "could-not-verify", "non-HTTPS URL — skipping verify"
    try:
        proc = subprocess.run(
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", "10", url],
            capture_output=True, text=True, timeout=15,
        )
        code = proc.stdout.strip()
        if code in ("404", "410", "204"):
            return "verified-deleted", f"GET {url} → HTTP {code}"
        if code == "200":
            return "still-present", f"GET {url} → HTTP 200 (resource still served)"
        return "could-not-verify", f"GET {url} → HTTP {code} (ambiguous)"
    except (subprocess.TimeoutExpired, OSError) as e:
        return "could-not-verify", f"curl GET failed: {e}"


# =============================================================================
# Dispatch — pick verifier based on command shape
# =============================================================================

DISPATCH = [
    (r"\b(rm|rmdir)\s+", verify_rm),
    (r"\bmove-item\b|(?:^|[;&|])\s*mv\s+|\brobocopy\b.*\/(?:move|mov)\b", verify_move),
    (r"\bdocker\s+(rm|rmi|volume\s+rm|network\s+rm)\b", verify_docker_rm),
    (r"\bkubectl\s+delete\s+\w+\s+\S+", verify_kubectl_delete),
    (r"\bcurl\s+[^|]*-X\s+DELETE\b", verify_curl_delete),
]

# Things we recognize as destructive but don't have a verify strategy for.
# Logged as "could-not-verify" with a hint.
DESTRUCTIVE_NO_STRATEGY = [
    (r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", "DB DROP — connect and check `\\dt` manually"),
    (r"\bTRUNCATE\b", "TRUNCATE — connect and SELECT count(*) manually"),
    (r"\bDELETE\s+FROM\s+", "SQL DELETE — connect and SELECT count(*) manually"),
    (r"\baws\s+\w+\s+(delete|terminate|remove)-\w+", "AWS delete — `aws describe` to verify"),
    (r"\bgcloud\s+\w+(\s+\w+)*\s+delete\b", "GCP delete — gcloud describe to verify"),
    (r"\bcloudflared\s+tunnel\s+delete\b", "CF tunnel delete — `cloudflared tunnel list` to verify"),
    (r"\bgit\s+(reset\s+--hard|branch\s+-D|push\s+--force)", "git destructive — git log/branch/reflog"),
    (r"\bsystemctl\s+(stop|disable)\b", "systemctl — verify with systemctl status"),
    (r"\bkill\s+-9\b|\bpkill\s+-9\b|\bkillall\b", "process kill — verify with ps/pgrep"),
    (r"\b(apt|apt-get)\s+(remove|purge)\b", "apt remove — verify with dpkg -l"),
    (r"\bpip\s+uninstall\b", "pip uninstall — verify with pip show"),
    (r"\bnpm\s+(uninstall|rm)\b", "npm uninstall — verify with npm ls"),
]


def main() -> None:
    event = read_event()
    if event.get("tool_name") != "Bash":
        # PostToolUse is registered for many tools; only act on Bash
        sys.exit(0)
    cmd = (event.get("tool_input") or {}).get("command", "")
    if not cmd:
        sys.exit(0)

    # Did the command exit successfully? If it failed, no verification needed.
    response = event.get("tool_response", {}) or {}
    interrupted = response.get("interrupted")
    if interrupted:
        sys.exit(0)

    # Try dispatch verifiers
    for pattern, fn in DISPATCH:
        if re.search(pattern, cmd, re.IGNORECASE):
            verdict, details = fn(cmd)
            log("INFO" if verdict == "verified-deleted" else "WARN",
                "verify_deleted", verdict, pattern, f"{details} :: {cmd[:200]}")
            if verdict == "still-present":
                warn(f"⚠ STILL PRESENT after destructive op: {details}")
                warn(f"   Command: {cmd[:200]}")
                warn("   The agent should NOT report 'deleted' until this is resolved.")
            elif verdict == "verified-deleted":
                info(f"✓ verified deletion: {details}")
            else:
                info(f"could not verify: {details}")
            sys.exit(0)

    # No verifier — log if it's a recognized destructive without strategy
    for pattern, hint in DESTRUCTIVE_NO_STRATEGY:
        if re.search(pattern, cmd, re.IGNORECASE):
            log("INFO", "verify_deleted", "could-not-verify", pattern, f"{hint} :: {cmd[:200]}")
            info(f"destructive op detected but no auto-verify strategy. {hint}")
            sys.exit(0)

    # Non-destructive — silent
    sys.exit(0)


if __name__ == "__main__":
    main()
