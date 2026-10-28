---
name: layer-new
description: >
  Scaffold a new layer in a project's docs/layers/ tree following the
  feature-layer architecture (principle 28). A layer is a bounded
  concern (security, data, ui, infrastructure, domain) with its own
  invariants, decisions, gotchas, patterns, and feature narratives.
  Use when: "create a new layer", "add security layer", "scaffold
  layer", "start tracking <concern> separately", "/layer-new", "add
  bounded concern". Operates on the kb-skeleton structure; idempotent
  -- will not overwrite existing layers. Do NOT use to scaffold an
  individual feature narrative inside an existing layer; use /feature-new
  for that (a layer is the container, not the per-feature doc).
user-invocable: true
model: sonnet
---

# /layer-new -- scaffold a project layer

Creates `docs/layers/<layer-name>/` with the full template structure
defined by [principle 28](https://github.com/AnastasiyaW/codex-claude-code-config/blob/main/principles/28-feature-layer-architecture.md).

## When to use

- Starting to track a new bounded concern in a long-running project
- Refactoring sprawling cross-cutting code into a documented layer
- Onboarding a new team member who needs the layer map

## When NOT to use

- One-off scripts or pet projects with <5 features (overhead not
  justified)
- Layer name describes a directory (`src` is not a layer)
- The "layer" is actually one feature in disguise -- use `/feature-new`
  inside an existing layer instead

## Arguments

```
/layer-new <layer-name> [--purpose "..."] [--principles P-NN,P-MM]
```

- `<layer-name>` -- kebab-case, single word preferred. Examples:
  `security`, `data`, `image-processing`, `observability`.
- `--purpose` -- one-sentence purpose. If omitted, prompt the user.
- `--principles` -- comma-separated Tier 1 principle IDs that govern
  this layer (e.g. `P-02,P-21`). If omitted, leave placeholder in
  README.

## Direction (what to do, in order)

### Step 1 -- Verify environment

Check the current working directory:

1. Is it a git repository? Run `git rev-parse --show-toplevel`. If
   not, ask the user whether to initialize one (offer `git init` +
   private GitHub repo per global rule).
2. Does `docs/` exist? If not, create it.
3. Does `docs/layers/README.md` exist? If not, copy from
   `${CLAUDE_PLUGIN_ROOT}/templates/kb-skeleton/docs/layers/README.md`.
4. Check if `docs/layers/<layer-name>/` already exists. If yes,
   **stop** with a message -- do not overwrite. Suggest
   `/feature-new <layer> <slug>` instead.

### Step 2 -- Validate layer name

- Must be lowercase kebab-case (`[a-z][a-z0-9-]*`).
- Must not start with `_` (reserved for templates).
- Must not be a generic file-system name (`src`, `tests`, `docs`,
  `build`).
- If invalid, refuse with a clear message and a suggested fix.

### Step 3 -- Copy the template

Source: `${CLAUDE_PLUGIN_ROOT}/templates/kb-skeleton/docs/layers/_LAYER-TEMPLATE/`

Destination: `<repo>/docs/layers/<layer-name>/`

Copy the entire directory tree. Preserve subdirectory structure (`kb/`
and `features/`). Result:

```
docs/layers/<layer-name>/
├── README.md
├── history.md
├── kb/
│   ├── invariants.md
│   ├── decisions.md
│   ├── gotchas.md
│   └── patterns.md
└── features/
    └── _FEATURE-TEMPLATE.md
```

### Step 4 -- Fill placeholders

In every file under the new layer, replace:

- `<layer-name>` -> the actual layer name
- `<Layer name>` -> Title Case of the layer name (e.g. "Security",
  "Image Processing")

In `README.md` specifically:

- `**Purpose:** <one sentence...>` -> the `--purpose` argument value,
  or prompt the user
- `## Governing principles` list -> populate from `--principles` arg,
  or leave the placeholder bullets in place for the user to fill

In `history.md`:

- Insert a "Layer created" entry at the top with today's date
  (YYYY-MM-DD) and the originating reason. Prompt the user for the
  reason if not provided.

### Step 5 -- Register the layer

Update `docs/layers/README.md`:

- Add a row to the `## Layer index` table:
  `| <layer-name> | <purpose> | active |`
- If a cross-layer Mermaid graph exists, add a node for the new layer
  with no edges (user will add edges as dependencies form).

### Step 6 -- Wire to project state

If the project has `feature_list.json` at repo root, leave it alone --
features get added by `/feature-new`. Do not edit `feature_list.json`
from this skill.

If the project has `AGENTS.md`, suggest (but do not auto-edit) adding
the new layer to the "Source-of-truth docs" table if multiple layers
exist.

### Step 7 -- Confirm and suggest next step

Print a summary:

```
Layer created: docs/layers/<layer-name>/
Files: 1 README, 1 history, 4 kb/, 1 feature template

Suggested next steps:
1. Fill governing principles in docs/layers/<layer-name>/README.md
2. Write the first feature: /feature-new <layer-name> <slug>
3. Add the first invariant when it earns its place
```

## Blueprints (files this skill writes from)

- `${CLAUDE_PLUGIN_ROOT}/templates/kb-skeleton/docs/layers/_LAYER-TEMPLATE/` -- the source
  tree to copy
- `${CLAUDE_PLUGIN_ROOT}/templates/kb-skeleton/docs/layers/README.md` -- the layers index
  template (used only if missing)

## Gotchas

- **Renaming a layer is not idempotent.** If the user runs
  `/layer-new wrong-name` then realizes they wanted `right-name`,
  manually rename the directory and update references. This skill
  does NOT detect or fix duplicates.
- **Layer name collision with existing directories.** If
  `docs/<layer-name>/` exists at the `docs/` root (not under
  `docs/layers/`), refuse and ask the user which they want -- there
  is no automatic merge.
- **Templates may have moved.** If the template path
  `${CLAUDE_PLUGIN_ROOT}/templates/kb-skeleton/docs/layers/_LAYER-TEMPLATE/`
  does not exist (e.g. user is on a different machine), fall back to
  reading from
  `https://github.com/AnastasiyaW/codex-claude-code-config/tree/main/templates/kb-skeleton/docs/layers/_LAYER-TEMPLATE`
  via `gh api`.
- **Encoding boundary.** When writing files with Cyrillic content,
  follow the global rule from `~/.claude/rules/api-utf8-posting.md` --
  always specify `encoding="utf-8"` explicitly.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Layer already exists" | Directory `docs/layers/<name>/` present | Use `/feature-new` to add to it, or pick a different name |
| Template files missing | Path moved or different machine | Pull templates from public repo via `gh api repos/AnastasiyaW/codex-claude-code-config/contents/templates/kb-skeleton/docs/layers/_LAYER-TEMPLATE` |
| Layers README not updated | `docs/layers/README.md` had no `## Layer index` table | Open file manually, add table per the kb-skeleton template |
| Validator warns about layer | `validate_kb_links.py` flagged broken link | Layer is fine; broken link is in a feature doc inside it. Run `python scripts/build_kb_graph.py` from the project root for the full health report. |

## Implementation note

The bulk of the work is file copy + placeholder replacement. No
dynamic logic is needed; the template files do all the structural
heavy lifting. Keep this skill **deterministic and idempotent** -- it
must be safe to invoke twice on the same layer (second call should be
a no-op with a clear message).
