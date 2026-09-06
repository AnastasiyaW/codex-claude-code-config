#!/usr/bin/env python3
"""
repo_map.py — ranked symbol map of a codebase within a token budget.

Faithful (zero-dependency) reimplementation of Aider's repo-map idea
(https://aider.chat/docs/repomap.html): build a graph where files are nodes
and an edge F->D means "file F references an identifier *defined* in file D",
run PageRank over that graph to find structurally-important files, then emit
the highest-ranked symbol definitions (path:line: signature) until a token
budget is exhausted.

Why: dumping whole files into context is wasteful and blows the window. A
ranked map gives the model "what matters in this repo" cheaply, before a
refactor / deep-review fan-out.

Design notes vs Aider:
  - Aider uses tree-sitter for exact def/ref tags. This version uses robust
    regex extractors for common languages so it runs anywhere with stdlib
    only (no install, no supply-chain gate). Fidelity is lower than
    tree-sitter but good enough for ranking. To upgrade fidelity, swap
    `extract_defs`/`extract_idents` for tree-sitter-language-pack tags.
  - PageRank is power-iteration (no networkx/scipy).
  - Rare identifiers (defined in few files) weigh more, like Aider.

Usage:
    python repo_map.py [ROOT] [--budget-tokens 1024] [--max-files 0]
                       [--include-signature] [--json] [--top 0]
ROOT defaults to cwd. If ROOT is a git repo, only tracked files are scanned
(respects .gitignore); otherwise a directory walk with a denylist is used.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict

# ---- language config -------------------------------------------------------

# extension -> language key
EXT_LANG = {
    ".py": "py", ".pyi": "py",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "ts", ".tsx": "ts",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
}

# Per-language regexes capturing a definition name in group "name".
# Patterns are intentionally conservative (anchored at line start, allowing
# leading whitespace) to keep false positives low.
DEF_PATTERNS = {
    "py": [
        re.compile(r"^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\("),
        re.compile(r"^\s*class\s+(?P<name>[A-Za-z_]\w*)\s*[\(:]"),
    ],
    "js": [
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)\s*\("),
        re.compile(r"^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)"),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"),
        re.compile(r"^\s*(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{"),  # method shorthand
    ],
    "go": [
        re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_]\w*)\s*\("),
        re.compile(r"^\s*type\s+(?P<name>[A-Za-z_]\w*)\s+"),
    ],
    "rust": [
        re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+(?P<name>[A-Za-z_]\w*)"),
    ],
    "java": [
        re.compile(r"^\s*(?:public|private|protected|static|final|abstract|\s)*(?:class|interface|enum)\s+(?P<name>[A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:public|private|protected|static|final|synchronized|abstract|\s)+[\w<>\[\].]+\s+(?P<name>[A-Za-z_]\w*)\s*\("),
    ],
    "ruby": [
        re.compile(r"^\s*def\s+(?P<name>[A-Za-z_]\w*[!?=]?)"),
        re.compile(r"^\s*(?:class|module)\s+(?P<name>[A-Z]\w*)"),
    ],
    "c": [
        re.compile(r"^\s*(?:[A-Za-z_][\w\s\*]+?)\s+(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)\s*\{"),
        re.compile(r"^\s*(?:struct|enum|union)\s+(?P<name>[A-Za-z_]\w*)\s*\{"),
    ],
    "csharp": [
        re.compile(r"^\s*(?:public|private|protected|internal|static|sealed|abstract|partial|\s)*(?:class|interface|struct|enum)\s+(?P<name>[A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:public|private|protected|internal|static|virtual|override|async|\s)+[\w<>\[\].]+\s+(?P<name>[A-Za-z_]\w*)\s*\("),
    ],
    "php": [
        re.compile(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+(?P<name>[A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:public|private|protected|static|\s)*function\s+(?P<name>[A-Za-z_]\w*)\s*\("),
    ],
    "kotlin": [
        re.compile(r"^\s*(?:fun)\s+(?P<name>[A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:open\s+|data\s+|sealed\s+|abstract\s+)?(?:class|interface|object)\s+(?P<name>[A-Za-z_]\w*)"),
    ],
    "swift": [
        re.compile(r"^\s*(?:public|private|internal|fileprivate|open|static|\s)*func\s+(?P<name>[A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:public|private|internal|fileprivate|open|final|\s)*(?:class|struct|enum|protocol)\s+(?P<name>[A-Za-z_]\w*)"),
    ],
}
# ts/cpp reuse js/c patterns plus a couple extras
DEF_PATTERNS["ts"] = DEF_PATTERNS["js"] + [
    re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+(?P<name>[A-Za-z_$][\w$]*)"),
]
DEF_PATTERNS["cpp"] = DEF_PATTERNS["c"] + [
    re.compile(r"^\s*(?:class)\s+(?P<name>[A-Za-z_]\w*)"),
]

IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")

# language keywords to exclude from "definition names" and identifier refs
KEYWORDS = set("""
if else for while do switch case default break continue return func function def class
struct enum trait interface type const let var public private protected static final abstract
new delete try catch finally throw throws import from export package module use using namespace
void int float double bool boolean char string str list dict set map vec true false null nil none
self this super async await yield lambda pass with as in is and or not print len range
""".split())

WALK_DENY = {
    ".git", "node_modules", "dist", "build", "out", "target", ".venv", "venv",
    "__pycache__", ".next", ".nuxt", ".cache", "vendor", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".mypy_cache", "site-packages", ".tox",
}

# ---- file collection -------------------------------------------------------

def list_files(root: str) -> list[str]:
    """Tracked files if git repo (honors .gitignore), else filtered walk."""
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files"],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode == 0 and out.stdout.strip():
            files = [os.path.join(root, p) for p in out.stdout.splitlines()]
            return [f for f in files if os.path.splitext(f)[1] in EXT_LANG]
    except (OSError, subprocess.SubprocessError):
        pass
    collected = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in WALK_DENY and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1] in EXT_LANG:
                collected.append(os.path.join(dirpath, fn))
    return collected

# ---- extraction ------------------------------------------------------------

def extract(path: str, lang: str):
    """Return (defs, ident_counts).
    defs: list of (name, line_no, signature)
    ident_counts: {identifier: count} for refs in this file.
    """
    defs = []
    ident_counts = defaultdict(int)
    patterns = DEF_PATTERNS.get(lang, [])
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return defs, ident_counts
    for i, line in enumerate(lines, 1):
        if len(line) > 2000:  # skip minified / data lines
            continue
        for pat in patterns:
            m = pat.match(line)
            if m:
                name = m.group("name")
                if name and name not in KEYWORDS:
                    defs.append((name, i, line.rstrip()[:200]))
                break
        for tok in IDENT_RE.findall(line):
            if tok not in KEYWORDS and len(tok) > 1:
                ident_counts[tok] += 1
    return defs, ident_counts

# ---- pagerank --------------------------------------------------------------

def pagerank(nodes, edges, damping=0.85, iters=60, tol=1e-7):
    """Power-iteration PageRank.
    nodes: iterable of node keys.
    edges: {src: {dst: weight}} directed.
    """
    nodes = list(nodes)
    n = len(nodes)
    if n == 0:
        return {}
    rank = {x: 1.0 / n for x in nodes}
    out_w = {s: sum(d.values()) for s, d in edges.items()}
    base = (1.0 - damping) / n
    for _ in range(iters):
        new = {x: base for x in nodes}
        dangling = damping * sum(rank[x] for x in nodes if out_w.get(x, 0) == 0) / n
        for x in nodes:
            new[x] += dangling
        for s, dsts in edges.items():
            w = out_w.get(s, 0)
            if w <= 0:
                continue
            share = damping * rank[s] / w
            for dst, wt in dsts.items():
                new[dst] += share * wt
        delta = sum(abs(new[x] - rank[x]) for x in nodes)
        rank = new
        if delta < tol:
            break
    return rank

# ---- main map --------------------------------------------------------------

def build_map(root, budget_tokens=1024, max_files=0, include_signature=True, top=0):
    root = os.path.abspath(root)
    files = list_files(root)
    if max_files and len(files) > max_files:
        files = files[:max_files]

    # symbol -> set of files defining it; per-file defs; per-file ident counts
    def_files = defaultdict(set)
    file_defs = {}
    file_idents = {}
    for f in files:
        lang = EXT_LANG[os.path.splitext(f)[1]]
        defs, idents = extract(f, lang)
        file_defs[f] = defs
        file_idents[f] = idents
        for name, _ln, _sig in defs:
            def_files[name].add(f)

    n_files = max(len(files), 1)
    # rarity weight: idents defined in few files matter more (Aider-style)
    def rarity(name):
        df = len(def_files.get(name, ()))
        if df == 0:
            return 0.0
        return math.sqrt(n_files / df)

    # graph: edge F -> D when F references identifier defined in D (D != F)
    edges = defaultdict(lambda: defaultdict(float))
    for f in files:
        for ident, cnt in file_idents[f].items():
            definers = def_files.get(ident)
            if not definers:
                continue
            w = rarity(ident) * cnt
            for d in definers:
                if d == f:
                    continue
                edges[f][d] += w

    ranks = pagerank(files, {s: dict(d) for s, d in edges.items()})

    # symbol score = pagerank(def_file) * total refs to it across repo * rarity
    total_refs = defaultdict(int)
    for f in files:
        for ident, cnt in file_idents[f].items():
            if ident in def_files:
                total_refs[ident] += cnt

    scored = []  # (score, file, line, name, signature)
    for f in files:
        fr = ranks.get(f, 0.0)
        for name, ln, sig in file_defs[f]:
            score = fr * (1 + total_refs.get(name, 0)) * rarity(name)
            scored.append((score, f, ln, name, sig))
    scored.sort(key=lambda x: x[0], reverse=True)

    extracted_total = len(scored)
    if top:
        scored = scored[:top]

    # emit within token budget (~4 chars/token heuristic)
    selected = []
    used_chars = 0
    char_budget = budget_tokens * 4
    for score, f, ln, name, sig in scored:
        rel = os.path.relpath(f, root)
        line = f"{rel}:{ln}: {sig.strip()}" if include_signature else f"{rel}:{ln}: {name}"
        if used_chars + len(line) + 1 > char_budget and selected:
            break
        selected.append({"file": rel, "line": ln, "name": name,
                         "signature": sig.strip(), "score": round(score, 6)})
        used_chars += len(line) + 1

    return {
        "root": root,
        "files_scanned": len(files),
        "symbols_extracted_total": extracted_total,
        "symbols_ranked_after_top": len(scored),
        # Compatibility: this older key has always counted the post-top set.
        "symbols_total": len(scored),
        "symbols_emitted": len(selected),
        "budget_tokens": budget_tokens,
        "approx_tokens_used": used_chars // 4,
        "symbols": selected,
    }

def render_text(result):
    lines = [
        f"# Repo map: {result['root']}",
        f"# {result['files_scanned']} files scanned, "
        f"{result['symbols_emitted']} emitted / "
        f"{result['symbols_ranked_after_top']} after --top / "
        f"{result['symbols_extracted_total']} extracted symbols "
        f"(~{result['approx_tokens_used']} tokens, budget {result['budget_tokens']})",
        "",
    ]
    last_file = None
    for s in result["symbols"]:
        if s["file"] != last_file:
            lines.append(f"\n{s['file']}:")
            last_file = s["file"]
        lines.append(f"  {s['line']}: {s['signature']}")
    return "\n".join(lines)

def main(argv=None):
    ap = argparse.ArgumentParser(description="Ranked repo symbol map within a token budget.")
    ap.add_argument("root", nargs="?", default=".", help="repo root (default: cwd)")
    ap.add_argument("--budget-tokens", type=int, default=1024)
    ap.add_argument("--max-files", type=int, default=0, help="cap files scanned (0 = all)")
    ap.add_argument("--top", type=int, default=0, help="cap symbols before budget (0 = all)")
    ap.add_argument("--no-signature", action="store_true", help="emit names only")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    result = build_map(
        args.root,
        budget_tokens=args.budget_tokens,
        max_files=args.max_files,
        include_signature=not args.no_signature,
        top=args.top,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_text(result))
    return 0

if __name__ == "__main__":
    sys.exit(main())
