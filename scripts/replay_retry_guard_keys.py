#!/usr/bin/env python3
"""Score candidate target_key designs against 14 days of this machine's real history.

The first fix (skip `cd`) moved the top key from cmd:cd:<dir> to cmd:tailscale:ssh,
then to cmd:cat:>, then to cmd:#:claude-bypass -- each patch revealing the next
prefix. That pattern says the problem is the approach, not the patch: the key was
trying to read intent out of a shell string.

So instead of arguing, score the candidates on the same traffic. Two numbers matter:
  blocks        -- how often it would stop real work (false positives live here)
  true_repeats  -- how often it fires on a genuinely IDENTICAL failing command,
                   which is the case the guard exists for. Keeping this while
                   blocks collapses is the whole objective.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path

HOOK = Path.home() / ".claude" / "claude-code-config" / "hooks" / "repeated-attempt-guard.py"
PROJECTS = Path.home() / ".claude" / "projects"
spec = importlib.util.spec_from_file_location("rag", HOOK)
rag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rag)
WINDOW, SOFT, HARD = rag.WINDOW, rag.WARN_AFTER_FAILURES, rag.BLOCK_AFTER_FAILURES

_FLAG = re.compile(r"^-")
_PATHISH = re.compile(r"[\\/]|\.[A-Za-z0-9]{1,5}$")


def _norm(tok: str) -> str:
    tok = tok.strip("\"'")
    return Path(tok).name.lower() if _PATHISH.search(tok) else tok.lower()


def key_current(tool, ti):
    """Whatever is in the hook right now."""
    return rag.target_key(tool, ti)


def key_all_args(tool, ti):
    """Verb plus EVERY non-flag argument. Flags are the surface variation the guard
    was written to see through; arguments are the identity of the attempt."""
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return rag.target_key(tool, ti)
    cmd = (ti.get("command") or "").strip()
    if not cmd:
        return ""
    toks = [t for t in cmd.split() if not _FLAG.match(t)]
    if not toks:
        return ""
    return "cmd:" + ":".join(_norm(t) for t in toks[:12])


def key_whole_command(tool, ti):
    """The command itself, whitespace-normalised. Maximum precision."""
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return rag.target_key(tool, ti)
    cmd = " ".join((ti.get("command") or "").split()).lower()
    return f"cmd:{cmd[:300]}" if cmd else ""


def key_first_argument(tool, ti):
    """The key as it shipped before 2026-08-04: verb plus the first path-ish argument.

    Kept so the reason for the change stays reproducible. Once `target_key` was fixed,
    the old behaviour vanished from this script and the claim that justified the fix
    became unverifiable — an independent reviewer said exactly that, and was right.
    """
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return rag.target_key(tool, ti)
    cmd = (ti.get("command") or "").strip()
    if not cmd:
        return ""
    toks = [t for t in cmd.split() if not _FLAG.match(t)]
    if not toks:
        return ""
    verb = Path(toks[0].strip("\"'")).name.lower()
    arg = next((Path(t.strip("\"'")).name.lower() for t in toks[1:] if _PATHISH.search(t)), "")
    return f"cmd:{verb}:{arg}" if arg else f"cmd:{verb}"


VARIANTS = {"first_argument (old)": key_first_argument, "current": key_current,
            "all_args": key_all_args, "whole_command": key_whole_command}


def parse(path: Path):
    results, calls = {}, []
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return []
    with fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            content = (obj.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    calls.append({"id": b.get("id"), "tool": b.get("name") or "",
                                  "input": b.get("input") if isinstance(b.get("input"), dict) else {},
                                  "ts": obj.get("timestamp") or ""})
                elif b.get("type") == "tool_result":
                    t = b.get("content")
                    if isinstance(t, list):
                        t = " ".join(str(p.get("text", "")) for p in t if isinstance(p, dict))
                    results[b.get("tool_use_id")] = str(b.get("is_error")).lower() == "true"
    for c in calls:
        c["err"] = results.get(c["id"], False)
    return calls


def epoch(ts, fb):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return fb


def score(calls, keyfn):
    rows, fails, reads = deque(), defaultdict(list), deque()
    stats = Counter()
    exact = defaultdict(list)   # key -> exact command strings that failed
    samples = []

    def trim(now):
        while rows and now - rows[0][0] > WINDOW:
            ts, kind, k = rows.popleft()
            if kind == "fail":
                lst = fails[k]
                if lst and lst[0] == ts:
                    lst.pop(0)
            elif reads and reads[0] == ts:
                reads.popleft()

    base = time.time() - 86400 * 400
    for c in calls:
        ts = epoch(c["ts"], base)
        tool, ti = c["tool"], c["input"]
        if tool in rag.ACTING:
            k = keyfn(tool, ti)
            if k:
                trim(ts)
                f = fails.get(k) or []
                if f:
                    last = max(f)
                    consulted = any(r > last for r in reads)
                    if not consulted and len(f) >= HARD:
                        stats["block"] += 1
                        text = json.dumps(ti, ensure_ascii=False)
                        if exact[k] and text in exact[k]:
                            stats["true_repeat"] += 1
                        elif len(samples) < 25:
                            samples.append({"key": k[:90], "blocked": text[:150],
                                            "cause": exact[k][-1][:150] if exact[k] else ""})
        if tool in rag.CONSULTING:
            trim(ts)
            rows.append((ts, "read", ""))
            reads.append(ts)
        elif tool in rag.ACTING and c["err"]:
            k = keyfn(tool, ti)
            if k:
                trim(ts)
                rows.append((ts, "fail", k))
                fails[k].append(ts)
                exact[k].append(json.dumps(ti, ensure_ascii=False))
    return stats, samples


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    cutoff = time.time() - 86400 * days
    calls = []
    for p in sorted(PROJECTS.rglob("*.jsonl")):
        if p.stat().st_mtime <= cutoff:
            continue
        for c in parse(p):
            calls.append(c)
    # Bound by CALL timestamp, not file mtime. Selecting transcripts by mtime pulls in
    # every call those files contain, so "last 14 days" silently spanned 8 July to
    # 5 August — 28 days. An independent replay bounded by call time got different
    # numbers on 2026-08-04, and it was right: this filter is the fix, not a footnote.
    from datetime import datetime, timedelta, timezone
    edge = datetime.now(timezone.utc) - timedelta(days=days)
    calls = [c for c in calls if c["ts"] and c["ts"][:10] >= edge.strftime("%Y-%m-%d")]
    calls.sort(key=lambda c: c["ts"])
    span = f"{calls[0]['ts']}..{calls[-1]['ts']}" if calls else "empty"
    print(f"window: calls within {days}d -> {span}", flush=True)
    print(f"tool calls: {len(calls)}", flush=True)

    report = {}
    for name, fn in VARIANTS.items():
        stats, samples = score(calls, fn)
        report[name] = {"blocks": stats["block"], "true_repeats": stats["true_repeat"],
                        "samples": samples}
        print(f"{name:14s} blocks={stats['block']:5d}  of which identical-command "
              f"repeats={stats['true_repeat']:4d}", flush=True)
    (out / "key-variants.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                           encoding="utf-8")


if __name__ == "__main__":
    main()
