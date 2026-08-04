"""Does the high-risk review requirement actually fire, and is it actually satisfiable?

Driven through the real hook in a real temporary git repo, because the whole point of
this session was that a gate present in a config is not a gate that runs.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HOOK = Path.home() / ".claude" / "claude-code-config" / "hooks" / "test-gate-stop-hook.py"

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")
    print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def fire(repo, env):
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps({"hook_event_name": "Stop", "cwd": str(repo)}),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(repo), env=env)
    out = (r.stdout or "").strip()
    blocked = '"decision": "block"' in out
    reason = json.loads(out)["reason"] if blocked else ""
    return blocked, reason, (r.stderr or "")


with tempfile.TemporaryDirectory() as td:
    repo = Path(td) / "proj"
    (repo / "src" / "auth").mkdir(parents=True)
    (repo / ".claude").mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")

    # A command that reliably exits 0 here, so only the review requirement can block.
    # A quoted absolute python path is not runnable as a bare command line: the gate
    # then blocked for the RIGHT reason -- it refuses to pass on a test command it could
    # not execute -- but that made this file test the wrong thing.
    (repo / ".claude" / "test-command").write_text("python --version\n", encoding="utf-8")
    # make the session look old enough for the gate to engage
    os.utime(repo / ".claude", (0, 0))

    env = dict(os.environ)
    env["CLAUDE_REVIEW_EVIDENCE"] = str(Path(td) / "evidence.jsonl")
    env.pop("CLAUDE_SKIP_TEST_GATE", None)

    print("=== a localized, low-risk change ===")
    (repo / "src" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    blocked, reason, err = fire(repo, env)
    check("plain source change is not blocked", blocked, False)

    print("\n=== a high-risk change, tests green, no independent pass ===")
    (repo / "src" / "auth" / "login.py").write_text("def check():\n    return True\n",
                                                    encoding="utf-8")
    blocked, reason, err = fire(repo, env)
    check("high-risk with green tests IS blocked", blocked, True)
    check("the reason says more of our own tests is not deeper",
          "not a deeper check" in reason, True)
    check("the reason hands over the exact command", "--record" in reason, True)

    print("\n=== record the review, then retry ===")
    r = subprocess.run([sys.executable, str(HOOK), "--record",
                        "deep-review: 0 blocking findings; verdict PROCEED"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(repo), env=env)
    print("      " + (r.stdout or r.stderr).strip()[:100])
    blocked, reason, err = fire(repo, env)
    check("recorded review unblocks", blocked, False)

    print("\n=== move a DIFFERENT boundary: old evidence must not carry ===")
    (repo / "src" / "auth" / "session.py").write_text("def s():\n    return 2\n",
                                                      encoding="utf-8")
    blocked, reason, err = fire(repo, env)
    check("evidence does not carry to a new surface", blocked, True)

print("\nREVIEW GATE:", "PASS" if not failures else "FAIL")
for f in failures:
    print("  -", f)
sys.exit(0 if not failures else 1)
