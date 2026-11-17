# -*- coding: utf-8 -*-
"""The backup swap passes both guards that judge it; anything close to it stays gated.

Reproducer, 2026-11-16: `ssh <server> 'cd D && test ! -e f.bak && cp -p f f.bak && mv f.new f'`
was blocked by transfer-contract-guard (the backup cp read as a transfer). With the contract marker
appended, human-confirmation-guard blocked it (nothing may follow the swap). No form passed both, and
the deploy went through a hand-applied patch instead. Both guards now import one recognizer
(hooks/backup_swap.py). The BLOCK rows are the negative controls.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

HOOKS = pathlib.Path(os.environ.get("HOOKS_DIR", pathlib.Path(__file__).resolve().parents[1]))
SWAP = "cd /srv/app/src && test ! -e app.py.bak-1 && cp -p app.py app.py.bak-1 && mv app.py.new app.py"

CASES = [
    # (command, transfer-contract-guard, human-confirmation-guard, why)
    (SWAP, "ALLOW", "ALLOW", "local swap"),
    (f"ssh host '{SWAP}'", "ALLOW", "ALLOW", "swap over ssh"),
    (f'ssh -o BatchMode=yes host "{SWAP}"', "ALLOW", "ALLOW", "swap over ssh, double quotes, safe option"),
    ("test ! -e f.bak && cp -p f f.bak && mv f.new f", "ALLOW", "ALLOW", "swap without cd"),
    (f"ssh host '{SWAP}' && scp a.py host:/srv/app/a.py", "BLOCK", "ALLOW", "a real copy beside the swap"),
    (f"ssh host '{SWAP}'; cp -p a /srv/other/a", "BLOCK", "ALLOW", "a second copy after the swap"),
    ("cp -p app.py /srv/other/app.py", "BLOCK", "ALLOW", "plain copy to another folder"),
    ("test ! -e b && cp -r app.py b && mv app.py.new app.py", "BLOCK", "BLOCK", "cp -r is not the swap"),
    ("test ! -e b && cp -p app.py c && mv app.py.new app.py", "BLOCK", "BLOCK", "backup name differs from the checked one"),
    (f"ssh host '{SWAP} && rm app.py.bak-1'", "BLOCK", "BLOCK", "swap then delete the backup"),
    ("echo 'test ! -e b && cp -p f b && mv n f' && cp -p f /srv/x/f", "BLOCK", "ALLOW", "quoted swap as decoy, real copy outside"),
]


def verdict(guard: str, command: str) -> str:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "cwd": str(HOOKS), "session_id": "test-backup-swap", "transcript_path": ""}
    r = subprocess.run([sys.executable, str(HOOKS / guard)], input=json.dumps(event), capture_output=True,
                       text=True, encoding="utf-8", timeout=60)
    if r.returncode == 2 or '"block"' in r.stdout or '"deny"' in r.stdout:
        return "BLOCK"
    if r.returncode == 0:
        return "ALLOW"
    return f"UNKNOWN rc={r.returncode}: {(r.stdout + r.stderr)[:200]}"


@pytest.mark.parametrize("command,transfer,confirm,why", CASES, ids=[c[3] for c in CASES])
def test_guards_agree_on_backup_swap(command, transfer, confirm, why):
    assert verdict("transfer-contract-guard.py", command) == transfer, why
    assert verdict("human-confirmation-guard.py", command) == confirm, why


def test_one_recognizer():
    text = (HOOKS / "human-confirmation-guard.py").read_text(encoding="utf-8")
    assert "def backed_up_moves" not in text, "a second copy of the swap recognizer would drift"
    assert "from backup_swap import" in text
    assert "from backup_swap import backed_up_moves" in (HOOKS / "transfer-contract-guard.py").read_text(encoding="utf-8")
