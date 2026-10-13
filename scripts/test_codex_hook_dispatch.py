"""Checks for hooks/codex_hook_dispatch.py against a given handler list (default: the live ~/.codex dispatch list).

    python test_codex_hook_dispatch.py [handler-list.json]

1. a benign shell command passes (exit 0) and the dispatcher reports its time;
2. negative control: a recursive delete of the drive root MUST be blocked (exit 2, or a JSON block/deny) — if it passes, the dispatcher
   lost a guard;
3. SessionStart returns context (the handlers print a handoff/check banner);
4. a handler list that cannot be read is exit 1 with a message, never a silent pass.
Exit 0 = all four hold, 1 = a check failed."""
import json, os, subprocess, sys, time
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "hooks" / "codex_hook_dispatch.py"
LIST = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / ".codex" / "hooks.dispatch.json")
CWD = str(Path.home())


def run(event, payload, lst=LIST):
    env = dict(os.environ, CODEX_HOOK_DISPATCH_FILE=lst)
    t = time.time()
    r = subprocess.run([sys.executable, str(D), event], input=json.dumps(payload).encode(), capture_output=True,
                       env=env, cwd=CWD, timeout=900)
    return round(time.time() - t, 1), r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


base = {"session_id": "dispatch-test", "cwd": CWD, "hook_event_name": "PreToolUse", "tool_name": "Bash"}
fails = []
t, rc, out, err = run("PreToolUse", base | {"tool_input": {"command": 'python -c "print(40+2)"'}})
print(f"benign      {t:6.1f}s rc={rc}")
fails += [] if rc == 0 else [f"benign command not passed: rc={rc} {err[:200]}"]
danger = " ".join(["rm", "-" + "rf", "/"])          # built here so this file itself is not a delete command
t, rc, out, err = run("PreToolUse", base | {"tool_input": {"command": danger}})
print(f"delete root {t:6.1f}s rc={rc} {err[:100]!r}")
blocked = rc == 2 or '"decision": "block"' in out or '"permissionDecision": "deny"' in out   # exit 2 or JSON block
fails += [] if blocked else [f"NEGATIVE CONTROL passed: delete of the root was not blocked (rc={rc})"]
t, rc, out, err = run("SessionStart", {"session_id": "dispatch-test", "cwd": CWD, "hook_event_name": "SessionStart",
                                       "source": "startup"})
print(f"session     {t:6.1f}s rc={rc} context={len(out)}B")
fails += [] if rc == 0 and out.strip() else [f"SessionStart gave no context: rc={rc} {err[:200]}"]
t, rc, out, err = run("PreToolUse", base | {"tool_input": {"command": "echo 1"}}, lst=str(Path(CWD) / "no-such-list.json"))
print(f"no list     {t:6.1f}s rc={rc}")
fails += [] if rc == 1 and "NOT run" in err else [f"missing handler list not reported: rc={rc}"]
for f in fails:
    print("FAIL", f)
print("OK" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
