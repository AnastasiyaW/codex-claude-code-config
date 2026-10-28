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
    (f'cd C:/work/x && cp -p a.md b.md "{BASH_TMP}/bak/"', True, "Git Bash spelling of TEMP"),
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
    (f"Copy-Item C:\\x\\a.md {TMP}\\b -Filter C:\\work\\x", True, "a value parameter's value is not a positional"),
    (f"copy /Y a.md {TMP}\\b", True, "cmd copy with a /switch"),
    (f'cp a.md "{TMP}/b', False, "unbalanced quote cannot be parsed"),
    ("cp -p a.md C:/work/x/Desktop/a.md", False, "destination outside TEMP"),
    (f"cp -p a.md {TMP}/b && cp -p a.md C:/work/x/a.md", False, "one copy escapes TEMP"),
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
    # independent review 2026-10-28, each one executed as an ALLOW before the fix
    ("cp a.md /tmp/bak/a.md", True, "POSIX /tmp root"),
    ("cp a.md bak/a.md", False, "relative destination cannot be proven to be TEMP"),
    (f"cp a $(scp s h:d) {TMP}/x", False, "command substitution in a source position"),
    (f"cp a `scp s h:d` {TMP}/x", False, "backtick substitution in a source position"),
    (f"Copy-Item -Destination {TMP}\\x -Path Microsoft.PowerShell.Core\\FileSystem::\\\\host\\s", False,
     "provider-qualified UNC mid-token"),
]
# A drive letter that is not a local fixed disk (mapped share) is another machine.
if os.name == "nt":
    import ctypes
    import string
    REMOTE_LETTER = next((d for d in reversed(string.ascii_uppercase)
                          if ctypes.windll.kernel32.GetDriveTypeW(f"{d}:\\") != 3), None)
    if REMOTE_LETTER:
        CASES.append((f"Copy-Item a.md -Destination:{REMOTE_LETTER}:/tmp/x", False,
                      "non-fixed drive hidden behind -Destination:"))
        CASES.append((f"cp a.md {REMOTE_LETTER}:/tmp/x", False, "temp folder on a non-fixed drive letter"))
        CASES.append((f"cp {REMOTE_LETTER}:/share/a.md {TMP}/x", False, "source on a non-fixed drive letter"))
# A junction inside TEMP that points outside it must not count as TEMP.
JUNCTION = os.path.join(tempfile.gettempdir(), "tcg-test-junction")
if os.name == "nt" and not os.path.exists(JUNCTION):
    import subprocess
    subprocess.run(["cmd", "/c", "mklink", "/J", JUNCTION, str(HOOKS)], capture_output=True)
if os.path.isdir(JUNCTION) and os.path.realpath(JUNCTION) != os.path.abspath(JUNCTION):
    CASES.append((f"cp a.md {JUNCTION.replace(chr(92), '/')}/x.py", False, "junction under TEMP pointing outside"))

LOCAL_TEMP = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp").replace("\\", "/")
if os.environ.get("LOCALAPPDATA") and not guard._DRIVE_TEMP.match(LOCAL_TEMP.lower()):
    CASES.append((f"cp a.md {LOCAL_TEMP}/b/a.md", True, "%LOCALAPPDATA%\\Temp is a temp root too"))

failures = []
try:
    for command, expected, why in CASES:
        got = guard._local_copy_into_temp(command)
        print(f"  {'ok  ' if got == expected else 'FAIL'} expected={expected!s:5} got={got!s:5} {why}")
        if got != expected:
            failures.append(why)
finally:
    # rmdir removes only the junction itself; a recursive TEMP sweep through a
    # live junction would delete the hooks it points at.
    if os.path.isdir(JUNCTION) and os.path.realpath(JUNCTION) != os.path.abspath(JUNCTION):
        os.rmdir(JUNCTION)

if failures:
    print(f"{len(failures)} of {len(CASES)} cases wrong")
    sys.exit(1)
print(f"all {len(CASES)} cases correct")
