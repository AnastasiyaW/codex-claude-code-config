#!/usr/bin/env python3
"""Answer "what access do we actually hold for X?" before claiming a check is impossible.

An agent reported that it could not verify a live path because it had no token
for the host -- while the credential store held a file named for exactly that
purpose, plus full API access to the provider whose logs would have answered the
question. Nothing was missing except the twenty seconds it takes to look.

That is not a knowledge problem, it is a lookup problem, so it gets a lookup.

    python access_inventory.py                # everything we hold, grouped
    python access_inventory.py cloudflare     # only what matches
    python access_inventory.py staging myproduct

Prints NAMES, files and sizes only -- never a value. Reading a secret to use it
is normal work here; printing one into a transcript is not.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# Credential stores to scan. Override with CLAUDE_SECRET_STORES (os.pathsep-separated);
# a store that does not exist is skipped, so listing extras costs nothing.
STORES = [Path(p) for p in os.environ.get("CLAUDE_SECRET_STORES", "").split(os.pathsep) if p] or [
    Path.home() / ".secrets",
    Path(Path.home().anchor) / ".secrets",   # drive-root store, if the setup uses one
]

VAR_RE = re.compile(r'\s*(?:export\s+)?([A-Za-z][A-Za-z0-9_]{2,})\s*=')
# Files whose whole point is the credential: the name is the inventory entry.
OPAQUE_SUFFIXES = (".token", ".txt", ".pem", ".key", ".json")
BACKUP_RE = re.compile(r"\.bak|\.old|-pre-|\.orig", re.IGNORECASE)


def collect(include_backups: bool = False) -> tuple[dict[str, list[str]], list[Path]]:
    variables: dict[str, list[str]] = defaultdict(list)
    opaque: list[Path] = []
    for store in STORES:
        if not store.is_dir():
            continue
        for f in sorted(store.iterdir()):
            if not f.is_file():
                continue
            if not include_backups and BACKUP_RE.search(f.name):
                continue
            if f.suffix.lower() in OPAQUE_SUFFIXES and f.suffix.lower() != ".json":
                opaque.append(f)
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            names = {m.group(1) for m in (VAR_RE.match(l) for l in text.splitlines()) if m}
            if names:
                # Full path as the key: the same filename exists in more than one
                # store (two tokens.env), and keying on the name alone made the
                # second silently replace the first -- under-reporting, in the one
                # tool whose whole purpose is not to under-report.
                variables[str(f)] = sorted(names)
            elif f.suffix.lower() in OPAQUE_SUFFIXES:
                opaque.append(f)
    return variables, opaque


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("terms", nargs="*", help="filter: host, provider or service words")
    ap.add_argument("--include-backups", action="store_true",
                    help="also scan rotated/backup copies (names only, as always)")
    args = ap.parse_args()

    variables, opaque = collect(args.include_backups)
    if not variables and not opaque:
        print("no credential store found at: " + ", ".join(str(s) for s in STORES))
        return 1

    pattern = re.compile("|".join(re.escape(t) for t in args.terms), re.IGNORECASE) \
        if args.terms else None

    shown = 0
    for origin, names in sorted(variables.items()):
        hits = [n for n in names if not pattern or pattern.search(n) or pattern.search(origin)]
        if not hits:
            continue
        shown += len(hits)
        print(f"\n  {origin}")
        for n in hits:
            print(f"     {n}")

    files = [f for f in opaque if not pattern or pattern.search(f.name)]
    if files:
        print("\n  single-purpose credential files (the name IS the entry)")
        for f in files:
            print(f"     {f.parent.name}/{f.name}   ({f.stat().st_size} B)")
        shown += len(files)

    if shown == 0:
        print("\n  nothing matched" + (f" {args.terms}" if args.terms else ""))
        print("  Before writing that a check is impossible: this listing is the evidence")
        print("  required for that claim. Missing access is a task, not a verdict --")
        print("  widen the scope, use another credential, or say which one is needed.")
        return 1

    print(f"\n  {shown} entr{'y' if shown == 1 else 'ies'}. Values are never printed here;")
    print("  load them in the process that needs them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
