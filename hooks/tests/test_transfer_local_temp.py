# -*- coding: utf-8 -*-
"""A local copy into a temp folder needs no transfer contract; everything else still does.

Reproducer: on 2026-10-28 `cp -p rules/x.md <scratchpad>/backup/` and the
PowerShell `Copy-Item` twin were blocked while backing files up before an edit.
The False rows are the negative controls: if any of them turns True the
exemption has become a hole.
"""
import importlib.util
import os
import pathlib
import sys
import tempfile

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("guard", HOOKS / "transfer-contract-guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

TMP = tempfile.gettempdir().replace("\\", "/")
BASH_TMP = "/" + TMP[0].lower() + TMP[2:] if TMP[1:2] == ":" else TMP

CASES = [
    (f"cp -p rules/a.md {TMP}/bak/a.md", True, "plain local backup into TEMP"),
    (f'cd C:/Users/x && cp -p a.md b.md "{BASH_TMP}/bak/"', True, "Git Bash spelling of TEMP"),
    (f'mkdir -p "{TMP}/b" && cp -p a.md "{TMP}/b/" && cp -p c.md "{TMP}/b/"', True, "several copies, all into TEMP"),
    (f'Copy-Item "C:\\x\\a.md" "{TMP}\\b\\a.md"', True, "PowerShell positional"),
    (f'Copy-Item -Path C:\\x\\a.md -Destination "{TMP}\\b"', True, "PowerShell named destination"),
    (f"robocopy C:\\src {TMP}\\dst /E", True, "robocopy copy into TEMP"),
    (f"cp -t {TMP}/b a.md c.md", True, "cp -t target directory"),
    (f"cp --target-directory={TMP}/b a.md", True, "cp --target-directory="),
    (f"robocopy C:\\src {TMP}\\dst a.md", True, "robocopy destination is the second positional, not the last"),
    (f"Copy-Item a.md -Destination:{TMP}\\b", True, "PowerShell -Destination:value"),
    (f"Copy-Item a.md -Destination: {TMP}\\b", True, "PowerShell '-Destination: value' takes the next token"),
    (f"Copy-Item -Recurse C:\\src {TMP}\\b", True, "a switch without a value does not eat the next token"),
    (f"Copy-Item C:\\x\\a.md {TMP}\\b -Filter C:\\Users\\x", True, "a value parameter's value is not a positional"),
    (f"copy /Y a.md {TMP}\\b", True, "cmd copy with a /switch"),
    (f'cp a.md "{TMP}/b', False, "unbalanced quote cannot be parsed"),
    ("cp -p a.md C:/Users/x/Desktop/a.md", False, "destination outside TEMP"),
    (f"cp -p a.md {TMP}/b && cp -p a.md C:/Users/x/a.md", False, "one copy escapes TEMP"),
    (f"scp host:/etc/x {TMP}/x", False, "remote source, even into TEMP"),
    (f"cp host:/etc/x {TMP}/x", False, "host:path token"),
    (f"robocopy \\\\nas\\share {TMP}\\dst", False, "UNC source"),
    (f"robocopy C:\\src {TMP}\\dst /MOVE", False, "move changes the source"),
    (f"mv a.md {TMP}/a.md", False, "mv is not a copy"),
    (f"Move-Item a.md {TMP}\\a.md", False, "Move-Item is not a copy"),
    ('cp -p a.md "$B/a.md"', False, "unresolved variable destination"),
    (f"cp -p a.md {TMP}/../a.md", False, "dot-dot escape"),
    (f"rsync -a src/ {TMP}/dst/", False, "rsync is a sync tool"),
    (f"git clone https://example.com/r.git {TMP}/r", False, "clone is not a local copy"),
    (f"cp -p a.md {TMP}", False, "TEMP root itself is not a folder inside it"),
    (f"Copy-Item a.md {TMP}\\x -ToSession $s", False, "PowerShell remoting"),
]

LOCAL_TEMP = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp").replace("\\", "/")
if os.environ.get("LOCALAPPDATA") and not guard._DRIVE_TEMP.match(LOCAL_TEMP.lower()):
    CASES.append((f"cp a.md {LOCAL_TEMP}/b/a.md", True, "%LOCALAPPDATA%\\Temp is a temp root too"))

failures = []
for command, expected, why in CASES:
    got = guard._local_copy_into_temp(command)
    print(f"  {'ok  ' if got == expected else 'FAIL'} expected={expected!s:5} got={got!s:5} {why}")
    if got != expected:
        failures.append(why)

if failures:
    print(f"{len(failures)} of {len(CASES)} cases wrong")
    sys.exit(1)
print(f"all {len(CASES)} cases correct")
