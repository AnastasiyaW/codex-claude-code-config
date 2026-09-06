---
name: repo-map
description: Ranked symbol map of a codebase within a token budget — a compact "what matters in this repo" before reading files. Use when starting work in an unfamiliar/large codebase, before a refactor or deep-review fan-out, when you need JIT context instead of dumping whole files, or asked "give me a map of this repo / where are the important functions / what's the structure". Zero-dependency (stdlib only); Aider-inspired regex extraction and PageRank ranking, not a tree-sitter parser. Do NOT use to find correctness/security defects in a change or to audit a diff; use deep-review for that (this only ranks and lists symbols, it does not evaluate code quality).
---

# repo-map

Produces a **ranked list of the structurally-important symbol definitions** in a
codebase, capped to a token budget. The point: instead of dumping whole files
(wasteful, blows the context window), get a cheap "skeleton" of the repo —
the functions/classes everything else depends on — and read full files only
where it matters.

This is our zero-dependency port of [Aider's repo-map](https://aider.chat/docs/repomap.html).

## When to use

- **Onboarding** to an unfamiliar or large codebase — get the lay of the land first.
- **Before a refactor / `deep-review` / `workflow-orchestration` fan-out** — feed each
  subagent the map so it knows the important entry points without re-scanning.
- **JIT context** (principle 07 / `practice_context_engineering`) — load the map, not the files.
- Anytime the instinct is "let me read 20 files to understand this" → run this first.

## Usage

```bash
python scripts/repo_map.py [ROOT] [--budget-tokens N] [--top N] [--json] [--no-signature] [--max-files N]
```

- `ROOT` — repo root (default: cwd). If it's a git repo, only **tracked files** are
  scanned (honors `.gitignore`); otherwise a filtered directory walk is used.
- `--budget-tokens` (default 1024) — stop emitting once ~this many tokens are used
  (≈4 chars/token heuristic). Use 256–512 for a quick orientation, 2048+ for depth.
- `--top N` — hard cap on symbols before the budget applies.
- `--json` — machine-readable output (for piping into a workflow / another agent).
- `--no-signature` — emit `path:line: name` instead of the full signature line.

JSON distinguishes `symbols_extracted_total` (before `--top`),
`symbols_ranked_after_top` (after that cap), and `symbols_emitted` (after the
token budget). The legacy `symbols_total` key retains its post-`--top` meaning
for compatibility. None is a semantic coverage guarantee: extraction is regex-based
and `--max-files` can limit input. Never diagnose parser coverage from a capped map.

### Typical recipes

```bash
# Quick orientation in a new repo
python scripts/repo_map.py . --budget-tokens 512

# Feed a fan-out: JSON map of the most important 40 symbols
python scripts/repo_map.py /path/to/repo --top 40 --json > repo_map.json

# Focus a subdirectory (a single layer/service)
python scripts/repo_map.py /path/to/repo/services/auth --budget-tokens 800
```

## How ranking works

1. Extract definitions (functions/classes/types) and identifier references per file
   via per-language regexes (py/js/ts/tsx/go/rust/java/ruby/c/cpp/csharp/php/kotlin/swift).
2. Build a directed graph: edge `F → D` when file `F` references an identifier
   **defined** in file `D`. Rare identifiers (defined in few files) weigh more.
3. Run **PageRank** over the file graph → structurally-central files float up
   (shared utilities, core models, base classes).
4. Symbol score = `pagerank(def_file) × (1 + total_refs) × rarity`. Emit highest
   first until the token budget is hit.

So the map surfaces the code **everything else leans on**, not just the first files
alphabetically.

## Gotchas

- **Regex extraction, not tree-sitter.** Fidelity is good for ranking but not a
  parser. Exotic syntax, heavy macros, or unusual formatting can miss/misattribute a
  def. This is a deliberate trade for zero-install + runs-anywhere. To upgrade
  fidelity, replace `extract()` with `tree-sitter-language-pack` tags — the graph/
  PageRank stages stay identical. (Don't install tree-sitter casually: it trips the
  7-day supply-chain gate; gate it like any fresh dep.)
- **Token count is a heuristic** (`chars/4`), not a real tokenizer. Treat the budget
  as approximate; it errs slightly high on code with many short tokens.
- **Same name in many files** (e.g. `get`, `handle`) ranks each def site separately —
  expected, since each is a distinct definition. Use `--top` to trim noise.
- **Non-git dirs** fall back to a denylist walk (`node_modules`, `dist`, `venv`, …).
  If your build output lives somewhere unusual, it may get scanned — point ROOT at the
  source dir instead.
- **Generated code** (protobuf, `src/gen/`) can dominate ranks because it's referenced
  everywhere. Point ROOT at hand-written source, or filter after the fact.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `0 files scanned` | ROOT has no recognized source extensions, or all gitignored | Check `git ls-files`; point ROOT at the source subdir |
| A key function is missing | Regex didn't match its signature style | Lower `--budget-tokens` pressure (raise budget) or accept the limitation; verify by `grep` |
| `--top 12` appears to find only 12 definitions | Post-cap count confused with extraction | Inspect `symbols_extracted_total`; remove caps before investigating actual extraction misses |
| Map dominated by one vendored file | A `vendor/`/generated tree got scanned (non-git mode) | Run inside the git repo, or point ROOT at hand-written source |
| Wrong/old map | File moved; map is a point-in-time snapshot | Re-run — it's cheap and stateless |

## Verification

`scripts/repo_map.py` is stdlib-only and was verified to run on real trees (it
correctly ranks shared-utility files to the top via PageRank). Re-run on any repo to
confirm; there is no state to corrupt.
