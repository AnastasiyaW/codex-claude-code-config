"""Can the gate run a project whose test command is a shell script?

A project's `.claude/test-command` is written for the repository, not for the machine
that reads it. `./init.sh --fast` is the correct command on Linux and macOS; on Windows
CreateProcess refuses it with WinError 193, and the gate reported "unavailable ... no
green evidence was produced". That sentence is indistinguishable from a red suite, so
the honest reading was "go fix your tests" while the tests had never run at all.

Driven through the real hook in a real temporary git repo, for the same reason as
test_high_risk_review_gate.py: a gate present in a config is not a gate that runs.
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HOOK = Path(__file__).resolve().parents[1] / "hooks" / "test-gate-stop-hook.py"

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")
    print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")


def load_hook():
    """Import the hook as a module. Registering it in sys.modules first is required:
    its dataclass decorator resolves the owning module by name, and dies without it."""
    spec = importlib.util.spec_from_file_location("test_gate_stop_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


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
    return blocked, reason


def write_script(path, exit_code, marker):
    path.write_text(f'#!/usr/bin/env bash\necho "{marker}"\nexit {exit_code}\n',
                    encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


hook = load_hook()

print("=== portable_argv: bare program names ===")
here = Path.cwd()
for cmd in (["npm", "test", "--silent"], ["pytest", "--tb=short", "-q"],
            ["go", "test", "./..."], ["cargo", "test", "--quiet"]):
    got = hook.portable_argv(list(cmd), here)
    resolved = shutil.which(cmd[0])
    if os.name == "nt" and resolved:
        # CreateProcess appends only .exe to a bare name, so `npm` (npm.cmd) raised
        # WinError 2 and the gate blocked every Stop on a suite that never ran.
        check(f"windows: {cmd[0]} resolved to its PATH entry", got, [resolved, *cmd[1:]])
    else:
        check(f"untouched: {cmd}", got, cmd)
check("untouched: []", hook.portable_argv([], here), [])
# Nothing on PATH: keep the command, so the failure says what is really missing.
missing = ["no-such-runner-3f9c2a", "test"]
check("unresolvable bare name untouched", hook.portable_argv(list(missing), here), missing)

# Measured, not assumed: on Windows a .cmd and a .bat given by path run fine through
# subprocess, so touching them would be a change with no defect behind it.
for cmd in (["ci\\suite.bat"], ["./tools/run.cmd"]):
    check(f"untouched: {cmd}", hook.portable_argv(list(cmd), here), cmd)

print("\n=== detect_test_command returns a runnable path, not a bare name ===")
with tempfile.TemporaryDirectory() as td:
    proj = Path(td)
    (proj / "package.json").write_text('{"scripts": {"test": "x"}}', encoding="utf-8")
    detected = hook.detect_test_command(proj)
    if shutil.which("npm"):
        check("npm detected", detected[1] if detected else None, "npm test")
        check("npm argv[0] is the resolved path", detected[0][0], shutil.which("npm"))
    else:
        check("no npm on PATH: nothing detected", detected, None)

print("\n=== a shell command is made runnable, and only on Windows ===")
routed = hook.portable_argv(["./init.sh", "--fast"], here)
if os.name == "nt" and hook.windows_bash():
    check("windows: bash is prepended", routed[0].lower().endswith("bash.exe"), True)
    check("windows: arguments survive", routed[1:], ["./init.sh", "--fast"])
    # System32\bash.exe is the WSL launcher: without a distro the script never runs,
    # and the gate read that launch failure as a red suite. Git's bash must win.
    git_exe = shutil.which("git")
    git_root = Path(git_exe).resolve().parent.parent if git_exe else None
    if git_root and (git_root / "bin" / "bash.exe").is_file():
        check("windows: Git's bash is chosen over the WSL launcher",
              Path(routed[0]).parent.name.lower() not in ("system32", "windowsapps"), True)
    # Windows filenames are case-insensitive, so INIT.SH is a real file that fails
    # with the same WinError 193. Matching only the lowercase spelling would leave
    # the hole open for the one nobody thinks to test.
    upper = hook.portable_argv(["./INIT.SH", "--fast"], here)
    check("windows: uppercase suffix is routed too",
          upper[0].lower().endswith("bash.exe"), True)
    check("windows: uppercase name is passed through verbatim",
          upper[1:], ["./INIT.SH", "--fast"])
elif os.name == "nt":
    # No bash: returning the command untouched keeps the failure honest rather than
    # swapping one unrunnable command for another.
    check("windows without bash: untouched", routed, ["./init.sh", "--fast"])
else:
    check("posix: untouched, the OS can exec it", routed, ["./init.sh", "--fast"])

if os.name == "nt" and not hook.windows_bash():
    print("\nSHELL TEST COMMAND:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    sys.exit(0 if not failures else 1)

with tempfile.TemporaryDirectory() as td:
    repo = Path(td) / "proj"
    (repo / "src").mkdir(parents=True)
    (repo / ".claude").mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")

    (repo / ".claude" / "test-command").write_text("./run-tests.sh\n", encoding="utf-8")
    os.utime(repo / ".claude", (0, 0))  # make the session look old enough to engage

    env = dict(os.environ)
    env["CLAUDE_REVIEW_EVIDENCE"] = str(Path(td) / "evidence.jsonl")
    env.pop("CLAUDE_SKIP_TEST_GATE", None)

    # A low-risk path: only the shell command itself decides the verdict here.
    (repo / "src" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")

    print("\n=== the script exits 0: the gate lets the session close ===")
    write_script(repo / "run-tests.sh", 0, "SUITE-RAN-GREEN")
    blocked, reason = fire(repo, env)
    check("green shell suite does not block", blocked, False)

    print("\n=== the script exits 1: the gate still blocks, and for the real reason ===")
    write_script(repo / "run-tests.sh", 1, "SUITE-RAN-RED")
    blocked, reason = fire(repo, env)
    check("red shell suite blocks", blocked, True)
    # The distinction this whole file exists for: the script's own output has to be in
    # the reason. If it says "unavailable" instead, the command never ran and the gate
    # is reporting its own failure to launch as a test verdict.
    check("the reason carries the script's output", "SUITE-RAN-RED" in reason, True)
    check("the reason is not 'unavailable'", "unavailable" in reason, False)

if shutil.which("npm") and shutil.which("node"):
    # The same distinction through the auto-detected npm path, with the real npm: on
    # Windows it is npm.cmd, and before the fix the gate never managed to launch it.
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "npmproj"
        (repo / "src").mkdir(parents=True)
        (repo / ".claude").mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("# t\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        os.utime(repo / ".claude", (0, 0))

        env = dict(os.environ)
        env["CLAUDE_REVIEW_EVIDENCE"] = str(Path(td) / "evidence.jsonl")
        env.pop("CLAUDE_SKIP_TEST_GATE", None)
        (repo / "src" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")

        def npm_suite(code, marker):
            script = f"node -e \"console.log('{marker}');process.exit({code})\""
            (repo / "package.json").write_text(
                json.dumps({"name": "p", "version": "1.0.0", "scripts": {"test": script}}),
                encoding="utf-8")

        print("\n=== auto-detected npm test exits 0: the gate lets the session close ===")
        npm_suite(0, "NPM-RAN-GREEN")
        blocked, reason = fire(repo, env)
        check("green npm suite does not block", blocked, False)

        print("\n=== auto-detected npm test exits 1: the gate still blocks, on npm's output ===")
        npm_suite(1, "NPM-RAN-RED")
        blocked, reason = fire(repo, env)
        check("red npm suite blocks", blocked, True)
        check("the reason carries npm's output", "NPM-RAN-RED" in reason, True)
        check("the reason is not 'unavailable'", "unavailable" in reason, False)

print("\nSHELL TEST COMMAND:", "PASS" if not failures else "FAIL")
for f in failures:
    print("  -", f)
sys.exit(0 if not failures else 1)
