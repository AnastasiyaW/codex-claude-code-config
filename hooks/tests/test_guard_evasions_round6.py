# -*- coding: utf-8 -*-
"""Round six: the branch that never consulted the depth it had just computed.

One finding, one condition wide. The whole-command depth machinery built in
round five was correct - it simply was not reached when a line OPENS a group,
holds the payload, and has nothing after it. That shape scans as a single
segment entering at depth 0, so the fast path took it and masked a payload
sitting at depth 1.

Round five looked complete because every multi-line form it tested had either a
separator on the payload line or a threaded depth of 1 from a brace alone on the
previous line. The untested shape was brace-and-payload sharing a line.

Also here: the latent here-doc depth defect (a `}` in a body is data, not
syntax) and the documented conservative false positive.
"""
import importlib.util
import os
import pathlib
import sys

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
MODULE = HOOKS / "safety_common.py"
spec = importlib.util.spec_from_file_location("safety_common", MODULE)
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

DESTRUCTIVE = [r"\brm\s+-[a-z]*r[a-z]*f?\b"]

# Finding 1: the opening brace and the payload share a line, nothing follows.
OPENS_AND_HOLDS_PAYLOAD = [
    "{ echo 'rm -rf /home '\n} | bash",
    "( echo 'rm -rf /home '\n) | bash",
    "{ echo 'rm -rf /home '\n} <<EOF | bash\nx\nEOF",
    "{ cd /tmp && echo 'rm -rf /home '\n} | sh",
    "( echo 'rm -rf /home '\n) | tee /tmp/x.sh",
]

# Finding 2: a brace inside here-doc DATA must not move the guard's depth.
HEREDOC_BODY_IS_DATA = [
    "{ cat <<EOF\n}\nEOF\necho 'rm -rf /home '\n} | bash",
    "{ psql <<SQL\n}\nSQL\necho 'rm -rf /home '\n} | bash",
]

# Round five's forms, which must keep blocking.
STILL_BLOCKED = [
    "{\n  echo 'rm -rf /home '\n} | bash",
    "{ echo 'rm -rf /home '; } | bash",
    "cat() { bash; }; echo 'rm -rf /home ' | cat",
    "echo 'rm -rf /home ' | sort -o/tmp/x.sh && bash /tmp/x.sh",
]

GROUPS = [
    ("opens and holds payload", OPENS_AND_HOLDS_PAYLOAD),
    ("here-doc body is data", HEREDOC_BODY_IS_DATA),
    ("round five still blocked", STILL_BLOCKED),
]

# Verified negatives, including the reviewer's function-definition probes: a
# blanket refusal to mask must not turn an ordinary search into a block.
MUST_STAY_INERT = [
    'grep -rn "shutdown() {" /etc/init.d/',
    'grep -rn "cleanup() {" scripts/',
    "{ echo 'check the rm -rf log'; } | grep -c warn",
    "{ cd /tmp\n  echo 'check the rm -rf log'\n} | grep -c warn",
    "{ echo 'check the rm -rf log'; } | sort | uniq -c",
    "cat <<'NOTE' > note.md\nrm -rf notes\nNOTE",
    'grep -n "rm -rf" /var/log/exec.log 2>&1',
]

failures = []
for label, group in GROUPS:
    for command in group:
        seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
        if not seen:
            failures.append((label, command))
        print(f"  {'ok  ' if seen else 'MISS'} {label:<26} {command.splitlines()[0][:44]}")

print()
for command in MUST_STAY_INERT:
    seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
    if seen:
        failures.append(("an ordinary command must pass", command))
    print(f"  {'ok  ' if not seen else 'FALSE POSITIVE'} inert: {command.splitlines()[0][:52]}")

print()
if failures:
    print(f"{len(failures)} case(s) wrong:")
    for label, command in failures[:10]:
        print(f"  - {label}: {command.splitlines()[0][:70]}")
    sys.exit(1)
total = sum(len(g) for _, g in GROUPS) + len(MUST_STAY_INERT)
print(f"all {total} sixth-round cases correct")
