# -*- coding: utf-8 -*-
"""Round seven: an unmatched `)` is not a group close, and a kept body is code.

Both of this round's findings were CREATED by the previous round's fix, each in
the seam that fix moved. That is the shape convergence takes, and it is why
these cases live in the suite rather than in another review round.

Finding 1: the scanner counts every `)` as a close, but a `case` arm's `)` closes
nothing in shell grammar. Inside a group that silently dropped the recorded
depth to 0 and masked a payload that ran. Every segment now records the depth
its LINE started at as a floor, because an unmatched close can only lower depth
and lower is the unsafe direction.

Finding 2: "keep here-doc bodies verbatim" removed comment-stripping and
argument-masking from body content, which reinstated the two false positives
this whole change set was built to remove - one level down, inside a here-doc.
Bodies are still skipped for DEPTH; their content is treated per line again.
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

DESTRUCTIVE = [r"\brm\s+-[a-z]*r[a-z]*f?\b", r"\breboot\b"]

# Finding 1: a case arm's `)` desyncs depth. The payload has to be the SECOND
# statement on the arm line - as the first, segment_depth already held it at 1.
CASE_ARM_DESYNC = [
    "{ case a in\na) cd /tmp; echo 'rm -rf /home ' ;;\nesac\n} | bash",
    "( case a in\na) cd /tmp; echo 'rm -rf /home ' ;;\nesac\n) | bash",
    "{ case $x in\nstart) true; echo 'rm -rf /home ' ;;\n*) ;;\nesac\n} | sh",
]

# Finding 2 must not have reopened anything: a body that really deletes still
# blocks, and so does a body line that pipes into a shell.
BODY_STILL_BLOCKS = [
    "ssh h 'bash -s' <<'EOF'\nrm -rf /srv/data/old\nEOF",
    "ssh h 'bash -s' <<'EOF'\necho 'rm -rf /home ' | bash\nEOF",
    "psql <<SQL\nSELECT 1;\nSQL\nrm -rf /srv/data/old",
    "ssh h 'bash -s' <<'EOF'\necho 'rm -rf /srv/data/old' > /tmp/x.sh && bash /tmp/x.sh\nEOF",
    "ssh h 'bash -s' <<'EOF'\necho 'rm -rf /srv/data/old' > >(bash)\nEOF",
    "ssh h 'bash -s' <<'EOF'\n{ echo 'rm -rf /srv/data/old'; } | bash\nEOF",
    "ssh h 'bash -s' <<'EOF'\necho 'rm -rf /srv/data/old' | tee /tmp/x.sh && bash /tmp/x.sh\nEOF",
]

# Each of these transfers a destructive byte sequence to an executor without
# the ordinary direct pipe spelling.  The first is the exact redirection bridge
# whose apparent false-positive fix was measured to reopen it.
EXECUTION_BRIDGES = [
    "{ echo 'rm -rf /srv/data/old' } > /tmp/x.sh && bash /tmp/x.sh",
    "{ ssh h 'bash -s' <<'EOF'\nrm -rf /srv/data/old\nEOF\n} | cat",
]

GROUPS = [
    ("case arm desync", CASE_ARM_DESYNC),
    ("here-doc body still blocks", BODY_STILL_BLOCKS),
    ("redirect and group execution bridges", EXECUTION_BRIDGES),
]

# The founding false positives of this whole change set, one level down. Each
# was blocking again after the round-six commit kept bodies verbatim.
MUST_STAY_INERT = [
    "ssh h 'bash -s' <<'EOF'\necho \"reboot required after update\"\nuptime\nEOF",
    "ssh h 'bash -s' <<'EOF'\n# reboot is documented below\nls\nEOF",
    "ssh h 'bash -s' <<'EOF'\necho \"never run rm -rf /home here\"\nls\nEOF",
    "{ cd /tmp; echo 'check the rm -rf log'; } | cat",
    "{ cd /tmp\n  echo 'check the rm -rf log'\n} | grep -c warn",
    "cat <<'NOTE' > note.md\nrm -rf notes\nNOTE",
]

failures = []
for label, group in GROUPS:
    for command in group:
        seen = sc.any_match(command, DESTRUCTIVE, command=True) is not None
        if not seen:
            failures.append((label, command))
        print(f"  {'ok  ' if seen else 'MISS'} {label:<28} {command.splitlines()[0][:40]}")

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
print(f"all {total} seventh-round cases correct")
