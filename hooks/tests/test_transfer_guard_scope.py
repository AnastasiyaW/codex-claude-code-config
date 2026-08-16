# -*- coding: utf-8 -*-
"""The reproducer, before the fix: the guard reads words, not operations.

Every case here is a command I actually ran this session or an obvious sibling.
The ones marked False transfer nothing - they search text, write documentation,
or mention a tool in a comment - and each of them was blocked. The ones marked
True must keep blocking after the fix, or the repair is a hole.
"""
import importlib.util
import os
import pathlib
import sys

# The REGISTERED copy, taken from settings.json rather than assumed. The first
# version of this test loaded ~/.claude/hooks/transfer-contract-guard.py, which
# the harness does not run - so twelve green checks described a file that never
# executed. An independent review found that by reading the manifest.
HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
GUARD = HOOKS / "transfer-contract-guard.py"
spec = importlib.util.spec_from_file_location("guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

CASES = [
    # (command, should the guard treat this as a transfer, why)
    ('grep -n "rsync|robocopy|Copy-Item|scp " /some/file.py', False,
     "searching a file for those words moves nothing"),
    ('Select-String -Path guard.py -Pattern "rsync|Copy-Item"', False,
     "same search, PowerShell spelling"),
    ('# copy the models later\nls -la /tmp', False,
     "the word lives in a comment"),
    # Expected False in the first version; an independent review showed why that
    # is wrong. `python -` executes what arrives on stdin, and the same shape
    # reaches psql and every other client that runs its input. Only a reader that
    # provably cannot execute - cat, tee, jq - lets its body go.
    ('python - <<\'PY\'\ntext = "rsync --exclude models/** cost us a model"\nopen("note.md","w").write(text)\nPY', True,
     "a here-doc read by python, which executes what it is given"),
    ('cat <<\'NOTE\' > note.md\nrsync --exclude models/** cost us a model\nNOTE', False,
     "the same text handed to cat, which cannot execute anything"),
    ('echo "we will scp this tomorrow"', False,
     "a word inside an echo string"),

    ('scp /local/file host:/remote/file', True, "a real copy"),
    ('rsync -a /src/ /dst/', True, "a real sync"),
    ('robocopy C:\\a C:\\b /MOVE', True, "a real move"),
    ('Copy-Item -Path a -Destination b -Force', True, "a real copy"),
    ('cp -a /etc/fstab /etc/fstab.bak', True, "a real copy"),
    ("ssh host 'bash -s' <<'EOF'\nrsync -a /src/ /dst/\nEOF", True,
     "a here-doc executed as a remote shell really does run rsync"),
    ('git clone https://example.com/repo.git', True, "a clone"),
]

failures = []
for command, expected, why in CASES:
    detected = guard._transfer_kind(command) is not None
    mark = "ok  " if detected == expected else "FAIL"
    if detected != expected:
        failures.append((command, expected, detected, why))
    first = command.splitlines()[0][:62]
    print(f"  {mark} expected={'transfer' if expected else 'not a transfer':<14} got={'transfer' if detected else 'not a transfer':<14} {first}")

print()
if failures:
    print(f"{len(failures)} of {len(CASES)} cases wrong:")
    for command, expected, detected, why in failures:
        print(f"  - {why}: expected {'transfer' if expected else 'no'}, got {'transfer' if detected else 'no'}")
    sys.exit(1)
print(f"all {len(CASES)} cases correct")
