# -*- coding: utf-8 -*-
"""Round five: a group across lines, a redefined consumer, an attached flag.

Three evasions, all proven to execute. Two are last round's rules failing on a
spelling they had not been asked about - a group written across lines, and an
allowlisted name that the same line had just redefined - and one is a regex that
required a separator where GNU sort accepts none.

The reviewer's verified negatives are kept as tests too, including one he had
first reported as a false positive and then withdrew after finding the fault in
his own probe.
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

# Finding 1: the group is written across lines, so depth reset to zero.
GROUP_ACROSS_LINES = [
    "{\n  echo 'rm -rf /srv/data'\n} | bash",
    "{ cd /tmp\n  echo 'rm -rf /srv/data'\n} | bash",
    "(\n  echo 'rm -rf /srv/data'\n) | bash",
    "{ {\n  echo 'rm -rf /srv/data'\n  }\n} | bash",
]

# Finding 2: the line redefines a name the allowlist trusts.
REDEFINED_CONSUMER = [
    "cat() { bash; }; echo 'rm -rf /srv/data' | cat",
    "grep() { sh; }; echo 'rm -rf /srv/data' | grep x",
]

# Finding 3: GNU sort accepts the path attached to the flag.
ATTACHED_OUTPUT_FLAG = [
    "echo 'rm -rf /srv/data' | sort -o/tmp/x.sh && bash /tmp/x.sh",
    "echo 'rm -rf /srv/data' | sort -uo/tmp/x.sh",
    "echo 'rm -rf /srv/data' | sort --output=/tmp/x.sh",
]

GROUPS = [
    ("group across lines", GROUP_ACROSS_LINES),
    ("redefined consumer", REDEFINED_CONSUMER),
    ("attached output flag", ATTACHED_OUTPUT_FLAG),
]

# Verified negatives. The last one is the reviewer's own withdrawn false
# positive: an unquoted pattern legitimately stays in scope.
MUST_STAY_INERT = [
    "{ cd /tmp; echo 'check the rm -rf log'; } | grep -c warn",
    "{ cd /tmp\n  echo 'check the rm -rf log'\n} | grep -c warn",
    "{ echo 'check the rm -rf log'; } | sort | uniq -c",
    'grep -n "rm -rf" /var/log/exec.log 2>&1',
    'grep -rn "rm -rf" /var/log | sort | uniq -c',
]

failures = []
for label, group in GROUPS:
    for command in group:
        seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
        if not seen:
            failures.append((label, command))
        print(f"  {'ok  ' if seen else 'MISS'} {label:<22} {command.splitlines()[0][:50]}")

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
print(f"all {total} fifth-round cases correct")
