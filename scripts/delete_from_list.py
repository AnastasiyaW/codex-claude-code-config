"""Delete exactly the paths in an owner-approved deletion list, then verify each one is gone.

Owner decision 2026-10-11: long delete lists (temp, regenerable and test leftovers) live in a file
instead of the chat, and one general "yes" approves the whole file.

    python delete_from_list.py <list.txt> --show        # line to show the owner + count and size
    python delete_from_list.py <list.txt> --sha <hex>   # delete after the owner's bare go-ahead

The list lives in ~/.claude/state/deletion-lists/ and holds one absolute path per line ('#'
comments and blank lines are ignored). human-confirmation-guard lets the delete run only when the
owner's latest message is a bare go-ahead to my answer that showed
`deletion-list: <path> sha256:<hex>`. This script checks the digest again (the file must be the one
the owner saw) and refuses every path the guard's target_hard_limit refuses.

Exit codes: 0 every listed path is gone; 1 something was refused or is still there;
2 could not check (list outside the folder, digest mismatch, guard not loadable).
A <list>.result.json report is written next to the list.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path

LIST_DIR = Path.home() / ".claude" / "state" / "deletion-lists"
APPROVAL_LOG = Path.home() / ".claude" / "logs" / "deletion-approvals.jsonl"
CONSUMED = LIST_DIR / ".consumed-approvals.jsonl"
APPROVAL_MAX_AGE_S = 300


def list_key(path: str) -> str:
    """Same normalisation as human-confirmation-guard._list_key."""
    return Path(path.replace("\\", "/")).expanduser().as_posix().lower()


def find_approval(raw_list_arg: str, sha: str) -> tuple[dict | None, str]:
    """The guard's fresh, unused audit record for exactly this list and digest (review round 10:
    the script does not trust how it was invoked; only the guard writes these records after the
    owner's go-ahead)."""
    key, sha = list_key(raw_list_arg), sha.lower()
    try:
        lines = APPROVAL_LOG.read_text(encoding="utf-8").splitlines()[-200:]
    except OSError:
        return None, "no approval log"
    try:
        used = set(CONSUMED.read_text(encoding="utf-8").splitlines())
    except OSError:
        used = set()
    now = datetime.datetime.now()
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("list") != key or rec.get("sha") != sha:
            continue
        if line in used:
            return None, "this approval was already used"
        try:
            age = (now - datetime.datetime.fromisoformat(rec["ts"])).total_seconds()
        except (KeyError, ValueError):
            return None, "approval record without a valid time"
        if not 0 <= age <= APPROVAL_MAX_AGE_S:
            return None, f"approval is {age:.0f}s old (max {APPROVAL_MAX_AGE_S}s)"
        return {"line": line, **rec}, ""
    return None, "the guard has not approved this list and digest"
GUARD = Path(__file__).resolve().parent.parent / "hooks" / "human-confirmation-guard.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("human_confirmation_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_list(path: Path) -> tuple[bytes, list[str]]:
    data = path.read_bytes()
    lines = [ln.strip() for ln in data.decode("utf-8-sig", errors="replace").splitlines()]
    return data, [ln for ln in lines if ln and not ln.startswith("#")]


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main() -> int:
    # allow_abbrev=False: only the exact "--sha"/"--show" spellings the guard recognises are accepted
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False, fromfile_prefix_chars=None)
    ap.add_argument("list")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--show", action="store_true")
    mode.add_argument("--sha")
    args = ap.parse_args()

    if not args.list.lower().endswith(".txt"):  # the guard recognises a run by its .txt list argument
        print("UNKNOWN: the list must be a .txt file", file=sys.stderr)
        return 2
    try:
        path = Path(args.list).expanduser().resolve(strict=True)
        path.relative_to(LIST_DIR.resolve())
        data, entries = read_list(path)
    except (OSError, ValueError):
        print(f"UNKNOWN: the list must be an existing file in {LIST_DIR}", file=sys.stderr)
        return 2
    digest = hashlib.sha256(data).hexdigest()
    try:
        guard = load_guard()
    except Exception as exc:  # no guard -> no deletes; a missing check is not a pass
        print(f"UNKNOWN: cannot load the guard's hard limits: {exc}", file=sys.stderr)
        return 2

    def refusal(e: str) -> str | None:
        # review 2026-10-11 F3: on Windows a drive-less path means "current drive"; refuse it
        if os.name == "nt" and not re.match(r"^[A-Za-z]:[\\/]", e):
            return "a path needs a drive letter on Windows"
        why = guard.target_hard_limit(e)
        if why:
            return why
        why = guard.irreplaceable_reason(e, True)  # review R2: never via a list
        return f"irreplaceable ({why}) - name it in the chat" if why else None

    if args.show:
        refused = [(e, refusal(e)) for e in entries if refusal(e)]
        present = [Path(e) for e in entries if Path(e).exists()]
        total = sum(size_of(p) for p in present)
        print(f"deletion-list: {path.as_posix()} sha256:{digest[:16]}")
        print(f"entries={len(entries)} present={len(present)} size={total / 2**30:.2f} GiB refused={len(refused)}")
        for e in entries:  # review F4/R3: the owner sees every name, not only counts
            print(f"  {e}")
        for e, why in refused:
            print(f"REFUSED {e}: {why}")
        return 1 if refused else 0

    if not digest.startswith(args.sha.lower()) or len(args.sha) < 16:
        print("UNKNOWN: the list changed after it was shown (sha256 mismatch)", file=sys.stderr)
        return 2
    approval, why = find_approval(args.list, args.sha)
    if approval is None:
        print(f"REFUSED: {why}", file=sys.stderr)
        return 1
    try:  # one-shot: the same approval cannot run twice
        CONSUMED.parent.mkdir(parents=True, exist_ok=True)
        with CONSUMED.open("a", encoding="utf-8") as fh:
            fh.write(approval["line"] + "\n")
    except OSError as exc:
        print(f"UNKNOWN: cannot record the used approval: {exc}", file=sys.stderr)
        return 2

    results = []
    for e in entries:
        why = refusal(e)
        p = Path(e)
        if why:
            results.append({"path": e, "status": "refused", "reason": why})
            continue
        if not p.exists() and not p.is_symlink():
            results.append({"path": e, "status": "already_absent"})
            continue
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as exc:
            results.append({"path": e, "status": "error", "reason": str(exc)})
            continue
        gone = not p.exists() and not p.is_symlink()  # deletion is not done until it is verified
        results.append({"path": e, "status": "deleted" if gone else "still_present"})

    bad = [r for r in results if r["status"] not in {"deleted", "already_absent"}]
    report = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "list": path.as_posix(),
              "sha256": digest, "entries": len(entries), "failed": len(bad), "results": results}
    path.with_suffix(".result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {s: sum(r["status"] == s for r in results) for s in {r["status"] for r in results}}
    print(f"deleted list {path.name}: {counts}")
    for r in bad:
        print(f"{r['status'].upper()} {r['path']}: {r.get('reason', '')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
