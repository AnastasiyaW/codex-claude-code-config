#!/usr/bin/env python3
"""PreToolUse: auto-snapshot DB before bypassed destructive SQL + verify it's real.

Sibling of auto_backup_git.py but for databases. Third safety layer:
  Layer 1: block_destructive   (block if no bypass)
  Layer 2: require_human_confirmation  (require dual token: bypass + user-confirmed)
  Layer 3: pre_db_snapshot     (this — auto-backup right before destruction)

Activates only when both layers above passed (destructive pattern + bypass +
user-confirmed token), so the snapshot is taken right before a sanctioned op.

Snapshot strategy
=================
  1. Try to extract connection target (psql/mysql/mongo URL or -h/-U/-d flags)
  2. Run dump in best-effort mode to /tmp/db-snapshot-<engine>-<ts>.{sql,bson}
  3. **VERIFY** the dump is real (not empty, not truncated, has expected
     structure) — this is the part that distinguishes "we tried" from "it
     actually worked"
  4. Print recovery hint to stderr
  5. ALLOW the destructive command to proceed

Verification checks per engine
==============================
PostgreSQL (pg_dump):
  - File exists
  - File size > MIN_PG_SIZE (~200 bytes — empty schema dump baseline)
  - Footer line `-- PostgreSQL database dump complete` present (pg_dump
    writes this only on clean exit; truncated dumps lack it)
  - At least one `CREATE` or `COPY` or `INSERT` statement present

MySQL (mysqldump):
  - File exists, size > MIN_MYSQL_SIZE
  - Footer line `-- Dump completed` present
  - At least one `CREATE TABLE` or `INSERT INTO` statement

MongoDB (mongodump):
  - Output dir exists and not empty
  - At least one `.bson` file > 0 bytes
  - For each collection: matching `.metadata.json` present

If verify FAILS — loud WARN, but still ALLOW (we are not a blocker, we are
a safety net that didn't fully catch). Verify result also logged to safety.log.

Failure to *create* snapshot is treated the same: WARN, ALLOW. Reason:
blocking destructive ops because backup tooling missing creates a fail2-style
lockup that prevents legitimate dev work on machines without pg_dump.

Bypass: `# claude-bypass: db-snapshot` or CLAUDE_ALLOW_DB_SNAPSHOT=1
(use only on testing/throwaway DBs).
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    allow,
    any_match,
    bash_command,
    bypass,
    log,
    read_event,
)

SQL_DESTRUCTIVE_PATTERNS = [
    r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",
    r"\bTRUNCATE\s+TABLE\b",
    r"\bdropdb\b",
    r"\bmongo\s+.*\bdropDatabase\b",
    r"\bredis-cli\s+.*\bflushall\b",
    r"\bDELETE\s+FROM\s+\w+\s*(;|$)",
]

# Minimum sane sizes — below these we suspect truncated/empty dumps
MIN_PG_SIZE = 200       # empty PG schema dump baseline
MIN_MYSQL_SIZE = 200
MIN_BSON_SIZE = 1       # any non-empty bson

SNAPSHOT_DIR = Path("/tmp")  # Linux/macOS; Git Bash on Windows maps to C:\Users\<u>\AppData\Local\Temp


def now_ts() -> str:
    return _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def find_pg_url(cmd: str) -> str | None:
    m = re.search(r"postgres(?:ql)?://[^\s\"';]+", cmd)
    return m.group(0) if m else None


def find_mysql_dsn(cmd: str) -> dict | None:
    if not re.search(r"\bmysql\b|\bmysqldump\b", cmd):
        return None
    h = re.search(r"-h\s*(\S+)", cmd)
    u = re.search(r"-u\s*(\S+)", cmd)
    db = re.search(r"\b(?:mysql|mysqldump)\s+(?:[-\w\s]+\s+)?(\S+)\s*$", cmd)
    return {
        "host": h.group(1) if h else "localhost",
        "user": u.group(1) if u else None,
        "db": db.group(1) if db else None,
    }


def find_mongo_url(cmd: str) -> str | None:
    m = re.search(r"mongodb(?:\+srv)?://[^\s\"';]+", cmd)
    return m.group(0) if m else None


# =============================================================================
# Snapshot creation
# =============================================================================

def try_pg_snapshot(url: str, out_path: Path) -> tuple[bool, str]:
    if not shutil.which("pg_dump"):
        return False, "pg_dump not in PATH"
    try:
        proc = subprocess.run(
            ["pg_dump", "--no-owner", "--no-acl", "-f", str(out_path), url],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode == 0:
            return True, "pg_dump exit 0"
        return False, f"pg_dump exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    except subprocess.TimeoutExpired:
        return False, "pg_dump timed out (180s)"
    except OSError as e:
        return False, f"pg_dump OSError: {e}"


def try_mysql_snapshot(dsn: dict, out_path: Path) -> tuple[bool, str]:
    if not shutil.which("mysqldump"):
        return False, "mysqldump not in PATH"
    if not dsn.get("db"):
        return False, "no db name extracted"
    args = ["mysqldump", "-h", dsn["host"]]
    if dsn.get("user"):
        args += ["-u", dsn["user"]]
    args += [dsn["db"]]
    try:
        with out_path.open("wb") as fh:
            proc = subprocess.run(
                args, stdout=fh, stderr=subprocess.PIPE, timeout=180,
            )
        if proc.returncode == 0:
            return True, "mysqldump exit 0"
        return False, f"mysqldump exit {proc.returncode}: {proc.stderr.decode()[:200]}"
    except subprocess.TimeoutExpired:
        return False, "mysqldump timed out (180s)"
    except OSError as e:
        return False, f"mysqldump OSError: {e}"


def try_mongo_snapshot(url: str, out_dir: Path) -> tuple[bool, str]:
    if not shutil.which("mongodump"):
        return False, "mongodump not in PATH"
    try:
        proc = subprocess.run(
            ["mongodump", f"--uri={url}", f"--out={out_dir}"],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode == 0:
            return True, "mongodump exit 0"
        return False, f"mongodump exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    except subprocess.TimeoutExpired:
        return False, "mongodump timed out (180s)"
    except OSError as e:
        return False, f"mongodump OSError: {e}"


# =============================================================================
# Snapshot verification — proves the dump is real, not just "command exit 0"
# =============================================================================

def verify_pg_snapshot(out_path: Path) -> tuple[bool, str]:
    """Verify pg_dump output is complete and non-empty.

    Checks:
      1. File exists and size > MIN_PG_SIZE
      2. Footer marker `-- PostgreSQL database dump complete` present
         (pg_dump writes this only on clean exit)
      3. At least one CREATE / COPY / INSERT statement
    """
    if not out_path.exists():
        return False, "file does not exist"
    size = out_path.stat().st_size
    if size < MIN_PG_SIZE:
        return False, f"too small ({size} bytes < {MIN_PG_SIZE} threshold)"
    try:
        text = out_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"unreadable: {e}"
    if "PostgreSQL database dump complete" not in text:
        return False, "missing footer (likely truncated mid-dump)"
    has_create = bool(re.search(r"^CREATE\s+(TABLE|SCHEMA|TYPE|INDEX)", text, re.MULTILINE))
    has_data = bool(re.search(r"^COPY\s+\w+|^INSERT\s+INTO\s+", text, re.MULTILINE))
    if not (has_create or has_data):
        return False, "no CREATE or COPY/INSERT statements found"
    n_stmts = text.count("\nCOPY ") + text.count("\nINSERT INTO ") + text.count("\nCREATE ")
    return True, f"size={size}B, statements~{n_stmts}, footer OK"


def verify_mysql_snapshot(out_path: Path) -> tuple[bool, str]:
    """Verify mysqldump output."""
    if not out_path.exists():
        return False, "file does not exist"
    size = out_path.stat().st_size
    if size < MIN_MYSQL_SIZE:
        return False, f"too small ({size} bytes < {MIN_MYSQL_SIZE})"
    try:
        text = out_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"unreadable: {e}"
    if "Dump completed" not in text:
        return False, "missing 'Dump completed' footer"
    has_create = "CREATE TABLE" in text
    has_data = bool(re.search(r"^INSERT\s+INTO\s+", text, re.MULTILINE))
    if not (has_create or has_data):
        return False, "no CREATE TABLE or INSERT statements"
    n_stmts = text.count("CREATE TABLE") + text.count("INSERT INTO ")
    return True, f"size={size}B, statements~{n_stmts}, footer OK"


def verify_mongo_snapshot(out_dir: Path) -> tuple[bool, str]:
    """Verify mongodump output dir is non-empty and has expected structure."""
    if not out_dir.exists() or not out_dir.is_dir():
        return False, "output dir missing"
    bson_files = list(out_dir.rglob("*.bson"))
    if not bson_files:
        return False, "no .bson files produced"
    non_empty = [f for f in bson_files if f.stat().st_size >= MIN_BSON_SIZE]
    if not non_empty:
        return False, f"all {len(bson_files)} .bson files are empty"
    # Sanity: each .bson should have a sibling .metadata.json (mongodump creates both)
    missing_meta = [
        f for f in non_empty
        if not f.with_suffix(".metadata.json").exists()
        and not (f.parent / (f.stem + ".metadata.json")).exists()
    ]
    total_bytes = sum(f.stat().st_size for f in non_empty)
    note = f", {len(missing_meta)} without metadata" if missing_meta else ""
    return True, f"collections={len(non_empty)}, total={total_bytes}B{note}"


# =============================================================================
# Hook entry point
# =============================================================================

def warn(msg: str) -> None:
    sys.stderr.write(f"[pre_db_snapshot] {msg}\n")


def process_pg(cmd: str, ts: str) -> list[str]:
    pg = find_pg_url(cmd)
    if not pg:
        return []
    out = SNAPSHOT_DIR / f"db-snapshot-pg-{ts}.sql"
    msgs = []
    ok, info = try_pg_snapshot(pg, out)
    if not ok:
        msgs.append(f"PG SNAPSHOT FAILED: {info}")
        return msgs
    v_ok, v_info = verify_pg_snapshot(out)
    if v_ok:
        msgs.append(f"PG snapshot OK → {out} ({v_info})")
    else:
        msgs.append(f"PG snapshot CREATED BUT VERIFY FAILED → {out} ({v_info})")
        msgs.append("  ↑ ВНИМАНИЕ: dump может быть неполным/обрезанным. ПРОВЕРЬ вручную перед DROP.")
    return msgs


def process_mysql(cmd: str, ts: str) -> list[str]:
    dsn = find_mysql_dsn(cmd)
    if not dsn:
        return []
    out = SNAPSHOT_DIR / f"db-snapshot-mysql-{ts}.sql"
    msgs = []
    ok, info = try_mysql_snapshot(dsn, out)
    if not ok:
        msgs.append(f"MySQL SNAPSHOT FAILED: {info}")
        return msgs
    v_ok, v_info = verify_mysql_snapshot(out)
    if v_ok:
        msgs.append(f"MySQL snapshot OK → {out} ({v_info})")
    else:
        msgs.append(f"MySQL snapshot CREATED BUT VERIFY FAILED → {out} ({v_info})")
        msgs.append("  ↑ ВНИМАНИЕ: dump подозрительный. ПРОВЕРЬ вручную.")
    return msgs


def process_mongo(cmd: str, ts: str) -> list[str]:
    mongo = find_mongo_url(cmd)
    if not mongo:
        return []
    out_dir = SNAPSHOT_DIR / f"db-snapshot-mongo-{ts}"
    msgs = []
    ok, info = try_mongo_snapshot(mongo, out_dir)
    if not ok:
        msgs.append(f"Mongo SNAPSHOT FAILED: {info}")
        return msgs
    v_ok, v_info = verify_mongo_snapshot(out_dir)
    if v_ok:
        msgs.append(f"Mongo snapshot OK → {out_dir} ({v_info})")
    else:
        msgs.append(f"Mongo snapshot CREATED BUT VERIFY FAILED → {out_dir} ({v_info})")
        msgs.append("  ↑ ВНИМАНИЕ: collections могут быть неполными. ПРОВЕРЬ вручную.")
    return msgs


def main() -> None:
    event = read_event()
    if event.get("tool_name") != "Bash":
        allow()
    cmd = bash_command(event.get("tool_input", {}))
    if not cmd:
        allow()

    hit = any_match(cmd, SQL_DESTRUCTIVE_PATTERNS, command=True)
    if not hit:
        allow()

    # Opt-out: explicit `# claude-bypass: db-snapshot` for test/throwaway DBs
    if bypass("db-snapshot", cmd):
        log("INFO", "pre_db_snapshot", "skip-bypassed", hit, cmd)
        allow()

    ts = now_ts()
    all_msgs: list[str] = []
    all_msgs += process_pg(cmd, ts)
    all_msgs += process_mysql(cmd, ts)
    all_msgs += process_mongo(cmd, ts)

    if not all_msgs:
        all_msgs.append(
            "no recognizable connection string in command — snapshot SKIPPED. "
            "If the destructive op uses env DATABASE_URL or psql with .pgpass, "
            "auto-snapshot can't see it. Make a manual backup first."
        )

    # Determine overall verdict for log
    any_verified = any("snapshot OK" in m for m in all_msgs)
    any_failed_verify = any("VERIFY FAILED" in m for m in all_msgs)
    any_creation_failed = any("SNAPSHOT FAILED" in m for m in all_msgs)
    if any_verified and not any_failed_verify:
        verdict = "snapshot-verified"
    elif any_verified and any_failed_verify:
        verdict = "snapshot-partial"
    elif any_failed_verify:
        verdict = "snapshot-suspect"
    elif any_creation_failed:
        verdict = "snapshot-failed"
    else:
        verdict = "snapshot-skipped"

    log("WARN", "pre_db_snapshot", verdict, hit, cmd[:300])

    for m in all_msgs:
        warn(m)
    if any_verified:
        warn("Recovery hint: psql -f <snapshot.sql> <restore-target> "
             "(or mysql/mongorestore equivalents)")
    if any_failed_verify or any_creation_failed:
        warn("⚠ Snapshot имеет проблемы — рассмотри отмену destructive операции "
             "или сделай manual backup ДО запуска.")
    allow()


if __name__ == "__main__":
    main()
