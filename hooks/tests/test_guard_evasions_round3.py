# -*- coding: utf-8 -*-
"""Round three: output that reaches an executor without a pipe.

The inverted pipeline rule held - the reviewer could not respell his way past it
and said so. What it did not cover is that output has three other routes: a
process substitution, a file that a later command runs, and a shell profile that
runs at next start. Four of these were proven to execute.

`tee` and `out-file` were removed from the inert list for the same reason: a
consumer that writes to disk is a bridge, not a dead end.
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

DESTRUCTIVE = [r"\brm\s+-[a-z]*r[a-z]*f?\b", r"\bRemove-Item\b", r"\bscp\b"]

# Finding 1: no pipe at all, or an inert name with a dangerous argument.
PROCESS_SUBSTITUTION = [
    "echo 'rm -rf /srv/data' > >(bash)",
    "echo 'rm -rf /srv/data' | tee >(bash)",
    "echo 'rm -rf /srv/data' | tee /dev/null >(sh)",
]

# Finding 2: written to a file, then run by a later command on the same line.
WRITE_THEN_RUN = [
    "echo 'rm -rf /srv/data' | tee /tmp/x.sh && bash /tmp/x.sh",
    "echo 'rm -rf /srv/data' > /tmp/x.sh && bash /tmp/x.sh",
    "echo 'rm -rf /srv/data' | tee /tmp/x.sh ; sh /tmp/x.sh",
    "echo 'rm -rf /srv/data' | sort -o /tmp/x.sh",
    "echo 'rm -rf /srv/data' | base64 -d > /tmp/x.sh",
]

# Finding 3: persistence - executed at the next shell start.
PERSISTENCE = [
    "echo 'rm -rf /srv/data' >> ~/.bashrc",
    "echo 'rm -rf /srv/data' | tee -a ~/.bashrc",
    "echo 'rm -rf /srv/data' | tee /etc/cron.d/cleanup",
    "Write-Output 'Remove-Item -Recurse -Force C:\\data' | Out-File $PROFILE",
]

GROUPS = [
    ("process substitution", PROCESS_SUBSTITUTION),
    ("write then run", WRITE_THEN_RUN),
    ("persistence", PERSISTENCE),
]

# Still inert. Discarding output and merging stderr carry a payload nowhere, so
# the ordinary search must keep passing.
STILL_INERT = [
    'grep -n "rm -rf" /var/log/history 2>/dev/null',
    'grep -n "rm -rf" /var/log/history 2>&1',
    "echo 'rm -rf /srv/data' | cat",
    "echo 'rm -rf /srv/data' | grep rm | wc -l",
    'rg "rm -rf|DROP TABLE" .',
]

failures = []
for label, group in GROUPS:
    for command in group:
        seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
        if not seen:
            failures.append((label, command))
        print(f"  {'ok  ' if seen else 'MISS'} {label:<22} {command[:56]}")

print()
for command in STILL_INERT:
    seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
    if seen:
        failures.append(("a harmless command must pass", command))
    print(f"  {'ok  ' if not seen else 'FALSE POSITIVE'} inert: {command[:56]}")

print()
if failures:
    print(f"{len(failures)} case(s) wrong:")
    for label, command in failures[:10]:
        print(f"  - {label}: {command[:70]}")
    sys.exit(1)
print(f"all {sum(len(g) for _, g in GROUPS) + len(STILL_INERT)} third-round cases correct")
