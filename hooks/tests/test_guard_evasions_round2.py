# -*- coding: utf-8 -*-
"""The seventeen attacks the second independent review landed.

The first repair closed six reported holes and was still NEEDS_WORK, for one
structural reason: the here-doc rule had been inverted to a fail-safe allowlist
of inert readers, but the pipeline rule was still a fail-open allowlist of
dangerous names. Anything spelled differently walked past it - an absolute path,
a wrapper, a flag with an argument, a redirect, a line continuation, PowerShell.

Six of these were proven to execute by the reviewer with harmless markers. All
must be seen as dangerous. The inert cases at the end must still pass, including
the `grep` alternation that the naive segment splitter used to block.
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

DESTRUCTIVE = [
    r"\brm\s+-[a-z]*r[a-z]*f?\b", r"\breboot\b", r"\bDROP\s+TABLE\b",
    r"\bgit\s+reset\s+--hard\b", r"\bRemove-Item\b", r"\bscp\b", r"\brsync\b",
]

# Finding 2: the interpreter respelled.
RESPELLED_INTERPRETER = [
    "echo 'rm -rf /srv/data' | /bin/bash",
    "echo 'rm -rf /srv/data' | /usr/bin/sh",
    "echo 'rm -rf /srv/data' | env bash",
    "echo 'rm -rf /srv/data' | nohup bash",
    "echo 'rm -rf /srv/data' | command sh",
    "echo 'rm -rf /srv/data' | sudo -u root bash",
    "echo 'rm -rf /srv/data' | bash -O extglob",
    "echo 'rm -rf /srv/data' | bash 2>/dev/null",
]

# Finding 3: the consumer is on the next line.
CONSUMER_ON_THE_NEXT_LINE = [
    "echo 'rm -rf /srv/data' |\n  bash",
    "echo 'rm -rf /srv/data' \\\n  | bash",
]

# Finding 4: an inert reader heading a pipeline that executes the body.
INERT_READER_FEEDING_A_SHELL = [
    "cat <<EOF | bash\nrm -rf /srv/data\nEOF",
    "sudo cat <<'EOF' | sh\nrm -rf /srv/data\nEOF",
    "cat <<SQL | psql mydb\nDROP TABLE prices;\nSQL",
]

# Finding 5: PowerShell's execute-a-string idioms.
POWERSHELL = [
    "Write-Output 'Remove-Item -Recurse -Force C:\\data' | % { iex $_ }",
    "Write-Output 'Remove-Item -Recurse -Force C:\\data' | ForEach-Object { iex $_ }",
    "Write-Output 'Remove-Item -Recurse -Force C:\\data' | pwsh -Command -",
]

GROUPS = [
    ("interpreter respelled", RESPELLED_INTERPRETER),
    ("consumer on the next line", CONSUMER_ON_THE_NEXT_LINE),
    ("inert reader feeding a shell", INERT_READER_FEEDING_A_SHELL),
    ("powershell execute-a-string", POWERSHELL),
]

# Finding 6: these are ordinary searches and must NOT be blocked. The middle two
# were blocked by the naive splitter, which cut inside the quoted pattern.
STILL_INERT = [
    'grep -n "reboot\\|shutdown" /var/log/syslog',
    'grep -En "reboot|shutdown" /var/log/syslog',
    'rg "rm -rf|DROP TABLE" .',
    'grep -n "reboot" /var/log/syslog',
    "echo 'rm -rf /srv/data' | cat",
    "echo 'rm -rf /srv/data' | grep rm | wc -l",
    "cat <<'NOTE' > note.md\nrm -rf is dangerous\nNOTE",
]

failures = []
for label, group in GROUPS:
    for command in group:
        seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
        if not seen:
            failures.append((label, command))
        print(f"  {'ok  ' if seen else 'MISS'} {label:<30} {command.splitlines()[0][:52]}")

print()
for command in STILL_INERT:
    seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
    if seen:
        failures.append(("a harmless command must pass", command))
    print(f"  {'ok  ' if not seen else 'FALSE POSITIVE'} inert: {command.splitlines()[0][:56]}")

print()
if failures:
    print(f"{len(failures)} case(s) wrong:")
    for label, command in failures[:10]:
        print(f"  - {label}: {command.splitlines()[0][:70]}")
    sys.exit(1)
print(f"all {sum(len(g) for _, g in GROUPS) + len(STILL_INERT)} second-round cases correct")
