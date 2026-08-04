#!/usr/bin/env python3
"""Archive and index local Codex conversation histories.

This hook is intentionally local/private. It preserves source JSONL session logs
under ~/.codex/conversation-history/archive and writes a compact searchable index
with session ids, cwd hints, user prompts, and source hashes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


HOME = Path.home()
# A session transcript here reaches multiple GB; refusing to start below this leaves
# room to fail cleanly instead of halfway through a copy.
MIN_FREE_BYTES = 2 * 1024**3
SOURCE_ROOT = HOME / ".codex" / "sessions"


def _relocatable(name: str) -> Path:
    """`~/.codex/<name>`, unless a sibling `<name>.location` file says otherwise.

    A pointer file rather than a directory junction: a junction on this machine once
    emptied the skill catalogue without a word, and a wrong path that still resolves
    is worse than one that does not. Ignored unless absolute, which is what caught the
    first pointer being written with printf and coming out as `D:gent-archives`. No
    path is hardcoded here because this file is public; the machine-specific value
    lives in the pointer.

    conversation-history-github-sync.py carries this same resolver and must stay in
    step -- if the two disagree, one writes where the other does not look.
    """
    try:
        target = Path((HOME / ".codex" / f"{name}.location")
                      .read_text(encoding="utf-8-sig").strip())
        if target.is_absolute():
            return target
    except (OSError, ValueError):
        pass
    return HOME / ".codex" / name


DEST_ROOT = _relocatable("conversation-history")
ARCHIVE_ROOT = DEST_ROOT / "archive"
INDEX_PATH = DEST_ROOT / "codex_sessions_index.jsonl"
LATEST_MD = DEST_ROOT / "LATEST.md"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def iter_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    yield item
    except OSError:
        return


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                val = part.get("text") or part.get("content")
                if isinstance(val, str):
                    parts.append(val)
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    if isinstance(content, dict):
        val = content.get("text") or content.get("content")
        return val if isinstance(val, str) else ""
    return ""


def find_role_messages(obj: Any, role: str, found: list[str]) -> None:
    if isinstance(obj, dict):
        if obj.get("role") == role:
            text = text_from_content(obj.get("content") or obj.get("text") or obj.get("message"))
            if text:
                found.append(text.strip())
        for val in obj.values():
            find_role_messages(val, role, found)
    elif isinstance(obj, list):
        for val in obj:
            find_role_messages(val, role, found)


def session_id_from(path: Path, records: list[dict[str, Any]]) -> str:
    for rec in records:
        if rec.get("type") == "session_meta":
            payload = rec.get("payload") or {}
            sid = payload.get("id") or payload.get("session_id")
            if sid:
                return str(sid)
        sid = rec.get("session_id")
        if sid:
            return str(sid)
    stem = path.stem
    return stem.replace("rollout-", "")


def session_id_from_record(rec: dict[str, Any]) -> str:
    if rec.get("type") == "session_meta":
        payload = rec.get("payload") or {}
        sid = payload.get("id") or payload.get("session_id")
        if sid:
            return str(sid)
    sid = rec.get("session_id")
    return str(sid) if sid else ""


def cwd_from_record(rec: dict[str, Any]) -> str:
    for key in ("cwd", "working_directory", "workdir"):
        val = rec.get(key)
        if isinstance(val, str) and val:
            return val
    payload = rec.get("payload")
    if isinstance(payload, dict):
        val = payload.get("cwd") or payload.get("working_directory")
        if isinstance(val, str) and val:
            return val
    return ""


def cwd_from(records: list[dict[str, Any]]) -> str:
    for rec in records:
        for key in ("cwd", "working_directory", "workdir"):
            val = rec.get(key)
            if isinstance(val, str) and val:
                return val
        payload = rec.get("payload")
        if isinstance(payload, dict):
            val = payload.get("cwd") or payload.get("working_directory")
            if isinstance(val, str) and val:
                return val
    return ""


def summarize(path: Path) -> dict[str, Any]:
    users: list[str] = []
    user_count = 0
    assistant_count = 0
    sid = ""
    cwd = ""
    for rec in iter_jsonl(path):
        if not sid:
            sid = session_id_from_record(rec)
        if not cwd:
            cwd = cwd_from_record(rec)
        rec_users: list[str] = []
        rec_assistants: list[str] = []
        find_role_messages(rec, "user", rec_users)
        find_role_messages(rec, "assistant", rec_assistants)
        user_count += len(rec_users)
        assistant_count += len(rec_assistants)
        if len(users) < 12:
            users.extend(rec_users[: 12 - len(users)])
    stat = path.stat()
    file_hash = sha256_file(path)
    if not sid:
        sid = path.stem.replace("rollout-", "")
    return {
        "session_id": sid,
        "source_path": str(path),
        "archive_path": "",
        "sha256": file_hash,
        "mtime_utc": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(timespec="seconds"),
        "size_bytes": stat.st_size,
        "cwd": cwd,
        "user_prompt_count": user_count,
        "assistant_message_count": assistant_count,
        "user_prompts_sample": [u[:500] for u in users[:12]],
    }


def archive_path_for(src: Path, session_id: str) -> Path:
    try:
        rel = src.relative_to(SOURCE_ROOT)
        parts = rel.parts
        if len(parts) >= 3:
            return ARCHIVE_ROOT.joinpath(*parts)
    except ValueError:
        pass
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in session_id)[:80]
    return ARCHIVE_ROOT / "misc" / f"{safe}.jsonl"


def load_existing_index() -> dict[str, dict[str, Any]]:
    existing: dict[str, dict[str, Any]] = {}
    if not INDEX_PATH.exists():
        return existing
    try:
        for line in INDEX_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            key = rec.get("source_path") or rec.get("session_id")
            if key:
                existing[str(key)] = rec
    except (OSError, json.JSONDecodeError):
        return {}
    return existing


def write_index(records: list[dict[str, Any]]) -> None:
    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_PATH.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records),
        encoding="utf-8",
    )
    os.replace(tmp, INDEX_PATH)

    latest = sorted(records, key=lambda r: r.get("mtime_utc", ""), reverse=True)[:25]
    lines = ["# Latest Codex Conversation History Index", ""]
    for rec in latest:
        prompts = rec.get("user_prompts_sample") or []
        title = prompts[0].replace("\n", " ")[:140] if prompts else "(no user prompt sample)"
        lines.append(f"- `{rec.get('mtime_utc')}` `{rec.get('session_id')}` - {title}")
    LATEST_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect(recent_days: int, limit: int) -> dict[str, Any]:
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - recent_days * 86400
    files = []
    if SOURCE_ROOT.exists():
        for path in SOURCE_ROOT.rglob("*.jsonl"):
            try:
                if path.stat().st_mtime >= cutoff:
                    files.append(path)
            except OSError:
                continue
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if limit > 0:
        files = files[:limit]

    existing = load_existing_index()
    merged = dict(existing)
    archived = 0
    updated = 0
    for src in files:
        old = existing.get(str(src))
        # Cheap check first. summarize() reads the whole transcript and hashes it, so
        # doing it before this comparison meant every Stop re-read up to `limit` files
        # out of a 30.7 GB tree -- measured at over 45s per session close. Size plus
        # mtime is the same quick-check rsync makes; a rewrite that preserves both is
        # the accepted blind spot.
        if old and Path(str(old.get("archive_path", ""))).exists():
            try:
                stat = src.stat()
                unchanged = (
                    old.get("size_bytes") == stat.st_size
                    and old.get("mtime_utc") == dt.datetime.fromtimestamp(
                        stat.st_mtime, dt.timezone.utc).isoformat(timespec="seconds"))
            except OSError:
                unchanged = False
            if unchanged:
                merged[str(src)] = old
                continue
        rec = summarize(src)
        dst = archive_path_for(src, rec["session_id"])
        rec["archive_path"] = str(dst)
        if old and old.get("sha256") == rec["sha256"] and Path(str(old.get("archive_path", ""))).exists():
            merged[str(src)] = old
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        archived += 1
        updated += 1
        merged[str(src)] = rec

    records = sorted(merged.values(), key=lambda r: r.get("mtime_utc", ""), reverse=True)
    write_index(records)
    return {
        "source_root": str(SOURCE_ROOT),
        "archive_root": str(ARCHIVE_ROOT),
        "index_path": str(INDEX_PATH),
        "latest_path": str(LATEST_MD),
        "seen_recent": len(files),
        "archived_or_updated": archived,
        "indexed_total": len(records),
    }


def _stop_hook_reentry() -> bool:
    """True when this is the anti-loop re-fire of the same Stop event.

    The hook is a CLI that never read its event, so every Stop -- including the
    re-fire -- paid a full rglob + sha256 of up to `limit` session files. Measured
    2026-08-04: over 45s per invocation against a 30.7 GB sessions tree.
    """
    if sys.stdin is None or sys.stdin.isatty():
        return False
    try:
        return bool(json.loads(sys.stdin.read() or "{}").get("stop_hook_active"))
    except (ValueError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recent-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if argv is None and not sys.argv[1:] and _stop_hook_reentry():
        return 0
    free = shutil.disk_usage(DEST_ROOT if DEST_ROOT.exists() else HOME).free
    if free < MIN_FREE_BYTES:
        # Copying a multi-GB transcript onto a full disk raises WinError 112 and the
        # archive silently stops being an archive. Say so instead of dying mid-copy.
        print(f"[conversation-history] skipped: {free / 2**30:.1f} GB free on the archive "
              f"volume, below the {MIN_FREE_BYTES / 2**30:.0f} GB floor. Nothing was "
              f"archived this session; free space or move DEST_ROOT.", file=sys.stderr)
        return 0
    result = collect(args.recent_days, args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "[conversation-history] indexed_total={indexed_total} "
            "recent={seen_recent} archived_or_updated={archived_or_updated} "
            "index={index_path}".format(**result)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
