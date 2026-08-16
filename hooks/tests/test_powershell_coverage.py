# -*- coding: utf-8 -*-
"""PowerShell destructive verbs must match a pattern at all.

Independent review, round three, correcting one of its own earlier claims: it
had reported several PowerShell forms as slipping because of the masking rule.
The masking hole was real, but it was not why they passed - they passed because
`human-confirmation-guard` had no pattern for `Remove-Item` whatsoever, and that
guard explicitly accepts `tool_name: PowerShell` on a machine where PowerShell
is the primary shell.

This suite is about the pattern list, not about scoping: every command here is
plain, unquoted and uncommented.
"""
import importlib.util
import os
import pathlib
import sys

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location("hcg", HOOKS / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hcg)
spec2 = importlib.util.spec_from_file_location("sc", HOOKS / "safety_common.py")
sc = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(sc)

MUST_MATCH = [
    "Remove-Item -Recurse -Force C:\\data",
    "Remove-Item C:\\important.txt",
    "Clear-Content C:\\important.log",
    "Stop-Service nginx",
    "Stop-Computer",
    "Restart-Computer -Force",
    "Move-Item a b",
]
MUST_NOT_MATCH = [
    "Get-ChildItem C:\\data",
    "Select-String -Path guard.py -Pattern Remove",
    "Write-Output 'done'",
]

failures = []
for command in MUST_MATCH:
    hit = sc.any_match(command, hcg.DESTRUCTIVE_INTENT, command=True)
    if hit is None:
        failures.append(("no pattern covers it", command))
    print(f"  {'ok  ' if hit else 'NO PATTERN'} {command[:56]}")

print()
for command in MUST_NOT_MATCH:
    hit = sc.any_match(command, hcg.DESTRUCTIVE_INTENT, command=True)
    if hit is not None:
        failures.append(("harmless, but matched " + str(hit), command))
    print(f"  {'ok  ' if not hit else 'FALSE POSITIVE'} harmless: {command[:50]}")

print()
if failures:
    for why, command in failures:
        print(f"  - {why}: {command}")
    sys.exit(1)
print(f"all {len(MUST_MATCH) + len(MUST_NOT_MATCH)} PowerShell coverage cases correct")
