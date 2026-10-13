"""Switch ~/.codex/hooks.json to one dispatcher entry per event (see hooks/codex_hook_dispatch.py for why).

    python codex_hook_dispatch_install.py            # convert (idempotent); backup hooks.json first
    python codex_hook_dispatch_install.py --revert   # put the full handler list back into hooks.json

The full handler list moves to ~/.codex/hooks.dispatch.json. If hooks.json is already in dispatcher form (e.g. a
re-run), the handler list is taken from hooks.dispatch.json; if install_hooks.py --codex has rewritten hooks.json
with the full list again, that new list replaces hooks.dispatch.json. Codex runs a changed hook only after the
owner approves it in /hooks (config.toml hooks.state trusted_hash): this script never writes trust.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

CODEX = Path.home() / ".codex"
HOOKS, FULL = CODEX / "hooks.json", CODEX / "hooks.dispatch.json"
DISPATCHER = Path(__file__).resolve().parent.parent / "hooks" / "codex_hook_dispatch.py"


def is_dispatch_form(cfg: dict) -> bool:
    return all(len(groups) == 1 and len(groups[0].get("hooks", [])) == 1
               and "codex_hook_dispatch.py" in groups[0]["hooks"][0].get("command", "")
               for groups in cfg.get("hooks", {}).values()) and bool(cfg.get("hooks"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    cur = json.loads(HOOKS.read_text(encoding="utf-8-sig"))
    backup = HOOKS.with_name(f"hooks.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(HOOKS, backup)
    if a.revert:
        if not is_dispatch_form(cur):
            print("hooks.json already holds the full list; nothing to revert"); return 0
        HOOKS.write_text(FULL.read_text(encoding="utf-8-sig"), encoding="utf-8")
        print(f"reverted: hooks.json = {FULL} (backup {backup.name})"); return 0
    full = json.loads(FULL.read_text(encoding="utf-8-sig")) if is_dispatch_form(cur) else cur
    n = {ev: sum(len(g.get("hooks", [])) for g in gs) for ev, gs in full.get("hooks", {}).items()}
    FULL.write_text(json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8")
    slim = {k: v for k, v in full.items() if k != "hooks"}
    slim["hooks"] = {}
    for ev, groups in full["hooks"].items():
        timeout = sum(int(h.get("timeout") or 60) for g in groups for h in g.get("hooks", []))
        slim["hooks"][ev] = [{"hooks": [{"type": "command", "command": f'python "{DISPATCHER.as_posix()}" {ev}',
                                          "timeout": min(timeout, 1800),
                                          "statusMessage": f"Running {n[ev]} {ev} guards..."}]}]
    HOOKS.write_text(json.dumps(slim, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"dispatch form: {sum(n.values())} handlers in {len(n)} events -> {len(n)} entries; backup {backup.name}")
    print("Codex runs them after approval in /hooks:", ", ".join(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
