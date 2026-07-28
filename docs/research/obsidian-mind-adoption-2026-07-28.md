# Obsidian Mind: adoption decision

Date: 2026-07-28

## Verified upstream design

The upstream repository combines three layers: a plain Markdown/Obsidian vault,
deterministic lifecycle hooks, and an optional QMD semantic-search layer. Its
manifest is the coordination point for index naming, infrastructure boundaries,
content roots, and frontmatter requirements. The architecture also keeps eager
session context under a byte budget and treats QMD as a fallback rather than a
hard dependency.

Source: https://github.com/breferrari/obsidian-mind and its
`ARCHITECTURE.md` and `.codex/hooks.json` files.

## Decision for this harness

Adopt the portable ideas, not a wholesale clone:

- Git remains the source of truth for durable work;
- the private chat archive may expose an Obsidian-compatible `Home.md` and
  manifest as a navigation view;
- evidence links and privacy boundaries stay enforced by the existing archive
  writer and knowledge-first search;
- QMD/MCP stays opt-in until a measured benchmark shows a real retrieval gain.

This keeps the open harness free of private conversations and prevents a second
stale memory store. The live private archive contains the bridge implementation;
this public note documents the reusable decision and its proof boundary.

## Proof boundary

The bridge is accepted only after tests show that it writes navigation metadata,
does not copy raw JSONL or secrets, and is byte-idempotent for the same input.
The absence of `obsidian` and `qmd` on the current machine means GUI behavior
and semantic-search quality remain unverified; neither is claimed as enabled.
