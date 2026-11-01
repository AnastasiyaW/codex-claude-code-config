"""Rename exactly the folders/files of an owner-approved relocate list, then verify each one moved.

Owner 2026-11-01 («поправь хук»: the course layout by topic stopped because the guard reads
Move-Item as a delete). A rename on one volume loses nothing, so it goes through a list like
delete_from_list.py, but nothing is ever removed:

    python relocate_from_list.py <list.txt> --show        # line to show the owner + every pair
    python relocate_from_list.py <list.txt> --sha <hex>   # rename after her «да» / «переноси»

The list lives in ~/.claude/state/relocate-lists/ and holds one `SRC => DST` per line ('#' comments
and blank lines are ignored). human-confirmation-guard writes a one-shot approval record only when
the owner's latest message is a bare go-ahead or «переноси» to my answer that showed
`relocate-list: <path> sha256:<hex>`; this script requires that record, re-checks the digest and the
guard's relocate_problem() for every pair, never overwrites (the target must not exist) and never
crosses volumes (os.rename). Each moved entry is checked: target present, source gone, same number
of files.

Exit codes: 0 every pair moved (or was already moved); 1 something was refused or failed;
2 could not check. A <list>.result.json report is written next to the list.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

LIST_DIR = Path.home() / ".claude" / "state" / "relocate-lists"
APPROVAL_LOG = Path.home() / ".claude" / "logs" / "deletion-approvals.jsonl"
CONSUMED = LIST_DIR / ".consumed-approvals.jsonl"
APPROVAL_MAX_AGE_S = 300
GUARD = Path(__file__).resolve().parent.parent / "hooks" / "human-confirmation-guard.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("human_confirmation_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_approval(key: str, sha: str) -> tuple[dict | None, str]:
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
        if rec.get("action") != "relocate" or rec.get("list") != key or rec.get("sha") != sha.lower():
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


def count_files(p: Path) -> int:
    return 1 if p.is_file() else sum(len(fs) for _, _, fs in os.walk(p))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("list")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--show", action="store_true")
    mode.add_argument("--sha")
    args = ap.parse_args()
    if not args.list.lower().endswith(".txt"):
        print("UNKNOWN: the list must be a .txt file", file=sys.stderr)
        return 2
    try:
        guard = load_guard()
        path = Path(args.list).expanduser().resolve(strict=True)
        path.relative_to(LIST_DIR.resolve())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        print(f"UNKNOWN: the list must be an existing file in {LIST_DIR} ({exc})", file=sys.stderr)
        return 2
    except Exception as exc:  # no guard -> no renames; a missing check is not a pass
        print(f"UNKNOWN: cannot load the guard: {exc}", file=sys.stderr)
        return 2
    pairs, why = guard.read_relocate_list(str(path), digest)
    if pairs is None:
        print(f"UNKNOWN: {why}", file=sys.stderr)
        return 2

    if args.show:
        refused = [(s, d, guard.relocate_problem(s, d)) for s, d in pairs]
        refused = [r for r in refused if r[2]]
        taken = [d for s, d in pairs if Path(d).exists()]
        print(f"relocate-list: {path.as_posix()} sha256:{digest[:16]}")
        print(f"entries={len(pairs)} present={sum(Path(s).exists() for s, _ in pairs)} "
              f"refused={len(refused)} target_exists={len(taken)}")
        for s, d in pairs:
            print(f"  {s}\n    -> {d}")
        for s, d, w in refused:
            print(f"REFUSED {s}: {w}")
        for d in taken:
            print(f"TARGET-EXISTS {d}")
        return 1 if refused or taken else 0

    if len(args.sha) < 16 or not digest.startswith(args.sha.lower()):
        print("UNKNOWN: the list changed after it was shown (sha256 mismatch)", file=sys.stderr)
        return 2
    approval, why = find_approval(guard._list_key(args.list), args.sha)
    if approval is None:
        print(f"REFUSED: {why}", file=sys.stderr)
        return 1
    try:
        CONSUMED.parent.mkdir(parents=True, exist_ok=True)
        with CONSUMED.open("a", encoding="utf-8") as fh:
            fh.write(approval["line"] + "\n")
    except OSError as exc:
        print(f"UNKNOWN: cannot record the used approval: {exc}", file=sys.stderr)
        return 2

    results = []
    for s, d in pairs:
        src, dst = Path(s), Path(d)
        why = guard.relocate_problem(s, d)
        if why:
            results.append({"src": s, "dst": d, "status": "refused", "reason": why})
            continue
        if not src.exists() and dst.exists():
            results.append({"src": s, "dst": d, "status": "already_moved"})
            continue
        if not src.exists():
            results.append({"src": s, "dst": d, "status": "error", "reason": "source missing"})
            continue
        if dst.exists():
            results.append({"src": s, "dst": d, "status": "refused", "reason": "target exists"})
            continue
        n = count_files(src)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)  # same volume; raises instead of overwriting or copying
        except OSError as exc:
            results.append({"src": s, "dst": d, "status": "error", "reason": str(exc)})
            continue
        ok = dst.exists() and not src.exists() and count_files(dst) == n
        results.append({"src": s, "dst": d, "status": "moved" if ok else "unverified", "files": n})

    bad = [r for r in results if r["status"] not in {"moved", "already_moved"}]
    report = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "list": path.as_posix(),
              "sha256": digest, "entries": len(pairs), "failed": len(bad), "results": results}
    path.with_suffix(".result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {k: sum(r["status"] == k for r in results) for k in {r["status"] for r in results}}
    print(f"relocated list {path.name}: {counts}")
    for r in bad:
        print(f"{r['status'].upper()} {r['src']}: {r.get('reason', '')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
