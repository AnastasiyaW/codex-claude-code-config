# -*- coding: utf-8 -*-
"""Round four: a brace group, a rebound descriptor, and a regression I caused.

Two evasions, both proven to execute, and one false-positive class that the
previous round's fix introduced. The reviewer also withdrew two candidates after
checking them - `echo '…' >&2` is genuinely harmless and a single-statement
brace group was already blocked - and those two are kept here as the boundary,
because a rule is only understood where it stops.
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

# Finding 1: a multi-statement brace group piping into a shell. The walk stopped
# at the `;` inside the group and never reached the pipe past the `}`.
BRACE_GROUPS = [
    "{ cd /tmp; echo 'rm -rf /srv/data'; } | bash",
    "{ echo setup; echo 'rm -rf /srv/data'; } | bash",
    "{ cd /tmp; echo 'rm -rf /srv/data' ;} | bash",
    # The boundary cases the reviewer checked: both were already blocked, and
    # must stay blocked.
    "(cd /tmp; echo 'rm -rf /srv/data') | bash",
    "{ echo 'rm -rf /srv/data'; } | sh",
]

# Finding 2: a descriptor rebound to a file, then written through `>&3`.
REBOUND_DESCRIPTORS = [
    "exec 3>/tmp/x.sh; echo 'rm -rf /srv/data' >&3; bash /tmp/x.sh",
    "exec 2>/tmp/x.sh; echo 'rm -rf /srv/data' >&2; bash /tmp/x.sh",
]

GROUPS = [
    ("brace group into a shell", BRACE_GROUPS),
    ("rebound descriptor", REBOUND_DESCRIPTORS),
]

# Finding 3, my regression: dropping sort and uniq blocked five of eight ordinary
# pipelines. They are inert unless they are told where to put their output.
MUST_STAY_INERT = [
    'grep -rn "rm -rf" /var/log | sort',
    'grep -rn "rm -rf" /var/log | sort | uniq -c',
    'grep -n "rm -rf" /var/log | sort -u',
    'grep -n "rm -rf" /var/log | uniq',
    "echo 'check rm -rf log' | sort | head -3",
    'grep -n "rm -rf" /var/log | wc -l',
    # Harmless: the payload goes to the terminal, nothing executes.
    "echo 'rm -rf /srv/data' >&2",
]

# ... but a named output is still a bridge.
STILL_DANGEROUS = [
    "echo 'rm -rf /srv/data' | sort -o /tmp/x.sh",
    "echo 'rm -rf /srv/data' | uniq /tmp/in /tmp/x.sh",
]

failures = []
for label, group in GROUPS:
    for command in group:
        seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
        if not seen:
            failures.append((label, command))
        print(f"  {'ok  ' if seen else 'MISS'} {label:<26} {command[:54]}")

for command in STILL_DANGEROUS:
    seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
    if not seen:
        failures.append(("a named output is still a bridge", command))
    print(f"  {'ok  ' if seen else 'MISS'} {'named output':<26} {command[:54]}")

print()
for command in MUST_STAY_INERT:
    seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
    if seen:
        failures.append(("an ordinary pipeline must pass", command))
    print(f"  {'ok  ' if not seen else 'FALSE POSITIVE'} inert: {command[:56]}")

print()
if failures:
    print(f"{len(failures)} case(s) wrong:")
    for label, command in failures[:10]:
        print(f"  - {label}: {command[:70]}")
    sys.exit(1)
total = sum(len(g) for _, g in GROUPS) + len(STILL_DANGEROUS) + len(MUST_STAY_INERT)
print(f"all {total} fourth-round cases correct")
