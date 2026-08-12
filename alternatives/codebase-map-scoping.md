---
related_principles: [4, 7, 11]
last_reviewed: 2026-08-12
---

# Codebase Map Scoping

## Problem

On large repositories, agents often start with broad `rg`, directory reads, or
many `cat` calls. This burns context and still misses reverse dependencies,
layer boundaries, and architecture drift. A machine-readable code graph can
scope the first read more precisely, but only if it is current and verified.

## Compared Approaches

| Approach | Best For | Pros | Cons |
|---|---|---|---|
| Belief map / code graph | Non-trivial code changes in Python/TypeScript-heavy repos | Fast boundary discovery; explicit deps/rdeps; queryable facts; smaller initial context | Requires build step, parser deps, and freshness checks |
| Symbol index / LSP queries | Mature language servers, IDE-style analysis | Precise definitions/references when LSP is configured | Can be slow or brittle across monorepos and generated code |
| Targeted `rg` first | Small changes or missing graph | Always available; transparent; no setup | Easy to over-read; weak at blast-radius and architecture boundaries |
| Full context upfront | Tiny repos only | Simple; fewer moving parts | Does not scale; hides what is relevant |

## Evaluated Candidate: diskd-ai/codespaces

Source:

- https://github.com/diskd-ai/codespaces
- https://www.skills.sh/diskd-ai/codespaces

Core idea: build `.belief_map.sexp` from a repository, then query it before
reading source: `search -> analyze -> rdeps/boundary -> read boundary files`.

Local evaluation on Windows, 2026-06-24:

- `belief_search.py` CLI help worked without third-party dependencies.
- `build_belief_map.py --full .` worked in an isolated `uv` venv after installing
  `tree-sitter`, `tree-sitter-typescript`, `tree-sitter-python`.
- Smoke on the cloned `codespaces` repo produced `.belief_map.sexp` with
  5 Python nodes and 137 entities.
- Queries worked: `search "belief_search"`, `analyze scripts/belief_search`,
  `boundary scripts/belief_search --files-only`, `find_function cmd_analyze`,
  and `invariants all`.
- Upstream unit tests did not run portably: `tests/test_belief_search.py`
  hardcodes an author-local absolute path.
- Non-LSP build did not produce call edges for that repo, so function-call
  analysis should be treated as best-effort unless `--lsp` is also verified.

Verdict: adopt the pattern; do not require this exact third-party skill as a
hard dependency until its tests are path-portable and a target project smoke is
green.

## Evaluated Candidate: syabro/pi-web-search

Source:

- https://github.com/syabro/pi-web-search

Core idea: a Pi extension that registers `web_search` and routes across search
providers with free tiers.

Local evaluation on Windows, 2026-06-24:

- Static review showed it is a Pi extension, not a Claude Code or Codex plugin.
- `npm install --ignore-scripts --package-lock-only` completed under the local
  npm 7-day release-age gate.
- `npm audit` reported 4 high vulnerabilities in the dev/peer dependency graph
  through `@earendil-works/pi-coding-agent`, `undici`, `protobufjs`, and `ws`.

Verdict: park for Pi-specific setups. Do not add it to this repo's default
Claude/Codex workflow. Re-evaluate only if Pi becomes part of the active agent
stack and the dependency audit is clean or risk-accepted.

## Recommended Default

1. If a current machine-readable code map exists, query it before broad source
   reads.
2. For non-trivial code changes, use this sequence:
   `search -> analyze -> rdeps/boundary -> read boundary files -> edit -> rebuild/query -> test`.
3. If the graph is missing, stale, fails to build, or lacks the target language,
   fall back to targeted `rg` and record why the graph path was skipped.
4. Do not trust the graph alone. It scopes reading; it does not replace tests,
   type checks, runtime smoke, security review, or human reasoning.
5. Do not install third-party skills globally until they pass the repository's
   supply-chain, test, and path-portability checks.

## When To Choose

Choose a codebase map when:

- the task changes a public contract, shared module, API, data model, or
  cross-service flow;
- the repository is large enough that broad reading is wasteful;
- reverse dependencies matter;
- architecture boundaries or layer violations are part of the risk.

Skip it when:

- the task is a commit summary, log review, demo run, browser QA, or single-file
  edit with obvious context;
- no current graph exists and building one would cost more than the task;
- the parser does not support the language being changed.

## Minimum Evidence Before Adoption

- Tool source and license reviewed.
- Dependencies installed only under the local supply-chain freshness gate.
- Build/query smoke passes on the target OS.
- At least one target repo smoke proves useful boundary output.
- Upstream test suite is path-portable, or local wrapper tests cover the broken
  path.
- The workflow has a documented fallback when the graph is absent or stale.
