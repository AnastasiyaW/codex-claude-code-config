#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Search Claude desktop app sessions by title / cwd / sessionId substring.

Usage:
    python sessions_find.py <query>                  # case-insensitive substring in title or cwd
    python sessions_find.py <query> --account <prefix>  # filter by accountId prefix (8 hex chars)
    python sessions_find.py --since 2026-04-01       # all sessions since date
    python sessions_find.py --untitled                # find empty/parse-failed sessions

Read-only. Output includes ready-to-copy restore command.
"""
from __future__ import annotations
import argparse
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

def storage_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude" / "claude-code-sessions"
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude-code-sessions"
    return Path.home() / ".config" / "Claude" / "claude-code-sessions"


ROOT = storage_root()

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)


def parse_session(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            obj = json.load(f)
    except Exception as e:
        return {"error": str(e), "path": path}
    sid_raw = obj.get("sessionId") or path.stem
    sid_clean = sid_raw.removeprefix("local_")  # storage stores with prefix; we keep canonical UUID
    return {
        "title": obj.get("title", ""),
        "cwd": obj.get("cwd", ""),
        "last": obj.get("lastActivityAt"),
        "session_id": sid_clean,
        "size": path.stat().st_size,
        "path": path,
    }


def fmt_ts(v) -> str:
    if not v:
        return "?"
    if isinstance(v, (int, float)):
        ts = v / 1000 if v > 1e10 else v
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(v)
    return str(v)[:16]


def to_ts(v) -> float:
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e10 else v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", nargs="?", default="", help="substring to find in title or cwd")
    ap.add_argument("--account", help="filter by accountId prefix (8 hex chars)")
    ap.add_argument("--since", help="filter to sessions since date YYYY-MM-DD")
    ap.add_argument("--untitled", action="store_true", help="find sessions without title or with parse errors")
    ap.add_argument("--limit", type=int, default=50, help="max results (default 50)")
    args = ap.parse_args()

    if not ROOT.exists():
        print(f"ERROR: {ROOT} does not exist", file=sys.stderr)
        return 1

    since_ts = 0.0
    if args.since:
        try:
            since_ts = datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        except ValueError:
            print(f"ERROR: --since must be YYYY-MM-DD", file=sys.stderr)
            return 2

    q = args.query.lower()
    matches = []
    for acct_dir in ROOT.iterdir():
        if not acct_dir.is_dir():
            continue
        if args.account and not acct_dir.name.startswith(args.account):
            continue
        for json_path in acct_dir.rglob("local_*.json"):
            meta = parse_session(json_path)
            org_id = json_path.parent.name
            meta["acct"] = acct_dir.name
            meta["org"] = org_id

            if since_ts and to_ts(meta.get("last")) < since_ts:
                continue

            if args.untitled:
                if "error" in meta or not meta.get("title"):
                    matches.append(meta)
                continue

            if q:
                hay = " ".join((meta.get("title", ""), meta.get("cwd", ""), meta.get("session_id", ""))).lower()
                if q not in hay:
                    continue
            matches.append(meta)

    matches.sort(key=lambda m: to_ts(m.get("last")), reverse=True)
    matches = matches[: args.limit]

    if not matches:
        print(f"# No sessions matching: query={q!r}, account={args.account}, since={args.since}")
        return 0

    print(f"# Found {len(matches)} sessions")
    print(f"# {'date':<16}  {'sid (12-char prefix-unique)':<20}  {'acct':<8}  title  [cwd]")
    print(f"# {'-'*16}  {'-'*20}  {'-'*8}  -----")
    for m in matches:
        last = fmt_ts(m.get("last"))
        sid = m.get("session_id", "?")[:12]  # 12 chars = essentially collision-free across <10K sessions
        acct = m.get("acct", "?")[:8]
        title = (m.get("title") or "(untitled)")[:60]
        cwd = m.get("cwd", "?")
        cwd_tail = "/".join(cwd.replace("\\", "/").split("/")[-2:]) if cwd else "?"
        err = " [PARSE_ERR]" if "error" in m else ""
        print(f"  {last:<16}  local_{sid:<14}  {acct:<8}  {title}{err}  [{cwd_tail}]")

    print()
    print("# To restore: copy the local_xxxxxxxxxxxx prefix and run:")
    print(f'#   python "{Path(__file__).resolve().with_name("sessions_restore.py")}" local_xxxxxxxxxxxx')
    return 0


if __name__ == "__main__":
    sys.exit(main())
