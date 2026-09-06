---
name: feature-new
description: >
  Scaffold a feature narrative in an existing project layer with Design,
  Plan, Verify, and Conclusion sections. Use when: "create a new feature",
  "start work on feature", "scaffold feature doc", "/feature-new", or
  "begin feature narrative". Inspects and preserves the target project's
  feature ID, registry, filename, and coordination conventions; does not
  create a missing layer (use /layer-new).
user-invocable: true
model: sonnet
---

# /feature-new -- scaffold a feature narrative

Creates a feature document in an existing layer. The document follows
the ULTRAPACK-style narrative template (Design / Plan / Verify /
Conclusion) extended with explicit cross-references to layer
invariants and global principles.

## When to use

- Beginning design work on a new feature, **before** writing code
- Migrating an in-flight feature from "scattered context" into the
  formal narrative
- Creating a feature placeholder when planning future work that
  another session will pick up

## When NOT to use

- One-line bug fixes that do not need a design phase (just commit)
- Documentation-only changes (those go in handoffs or PR
  descriptions)
- Refactors with no behavioral change (commit message is sufficient)

## Arguments

```
/feature-new <layer> <slug> [--title "..."] [--branch <name>] [--id <project-id>]
```

- `<layer>` -- existing layer name. Must be a directory under
  `docs/layers/`. If missing, suggest `/layer-new <layer>` first.
- `<slug>` -- kebab-case feature identifier without a project ID
  prefix. Examples: `api-key-rotation`, `audit-log`,
  `dual-encryption`.
- `--title` -- human-readable feature title. If omitted, derive from
  slug by title-casing.
- `--branch` -- git branch name. If omitted, default to
  `feature/<slug>`.
- `--id` -- override the auto-allocated project-native ID. Use only when
  migrating a pre-existing feature with a known ID. Refuse if the ID
  already exists in this layer.

## Direction (what to do, in order)

### Step 1 -- Verify environment

1. Determine repo root via `git rev-parse --show-toplevel`.
2. Confirm `docs/layers/<layer>/` exists. If not, refuse with a
   suggestion to run `/layer-new <layer>` first.
3. Confirm `docs/layers/<layer>/features/_FEATURE-TEMPLATE.md`
   exists. If not, copy from
   `<claude-code-skills-checkout>/templates/kb-skeleton/docs/layers/_LAYER-TEMPLATE/features/_FEATURE-TEMPLATE.md`.

### Step 2 -- Discover and reserve the project-native ID

Do this before changing the feature document, layer README, or registry. A
feature registry is project-owned state; this skill does not impose its old
`F-NNN` example on it.

1. Inspect existing feature documents, the layer README, `feature_list.json`
   (if present), a co-located schema or validator, and `AGENTS.md`/project
   docs for the actual ID format, namespace, filename convention, fields,
   initial status, allocator, and coordination rule. For example, this
   repository's long-run template uses lowercase `feat-NNN` IDs with
   `description`, `dependencies`, and string `evidence`; that is not
   interchangeable with the old `F-NNN` example.
2. If `--id` was provided, validate it against the discovered convention and
   check every project-owned feature source that the convention names. If it
   is already used, refuse without changing anything.
3. Otherwise use the project's allocator when one exists. If the convention is
   visible only in current records, derive a candidate from those records and
   recheck all of them immediately before reservation. Do not infer a global
   namespace, digit width, prefix, or sort order from this skill.
4. Follow an existing project coordination mechanism when one exists and you
   are authorized to use it. Otherwise reserve the **logical ID**, not a
   slug-bearing pathname, with `scripts/reserve_feature_id.py`. It atomically
   creates `refs/feature-new/reservations/<project-id>` in the repository and
   binds that ID to the layer, slug, and final document path. This is a Git
   allocator record, not a second feature registry: the same request returns
   `resumed`; a different layer/slug/path returns `conflict` and must not edit
   the registry or another claimant's document.
5. On `conflict`, re-inventory the project convention and choose the next
   project-native candidate. Continue safe reconciliation while the requested
   scaffold remains actionable; do not guess that a durable reservation has a
   stale owner, overwrite it, or impose an arbitrary retry limit.
6. If no project ID/path convention exists at all, bootstrap only this skill's
   documented default: lowercase `feat-NNN`, globally allocated through the
   Git-ref helper, with `docs/layers/<layer>/features/feat-NNN-<slug>.md` as
   the document path. Do not create `feature_list.json`; once a registry exists
   it becomes authoritative over this fallback.
7. After reservation, re-read the README and registry before companion
   updates. If their convention changed, preserve the valid document and stop
   before a stale README/registry write; report the exact conflict and reserved
   path for the owner to reconcile.

When the project has no registry schema or helper, do not stop merely because
it differs from this skill's example. Adapt by copying one current entry's
field set and ID style, changing only values whose meaning is established by
the project. If no representative entry or documented meaning exists, create
the requested narrative only and leave the unknown registry untouched rather
than append an invented record.

### Step 3 -- Validate slug

- Lowercase kebab-case (`[a-z][a-z0-9-]*`).
- Length <= 50 characters.
- Does not repeat the discovered ID prefix.
- The resulting project-native feature filename does not already exist.

### Step 4 -- Copy and fill the template

Source: `docs/layers/<layer>/features/_FEATURE-TEMPLATE.md`

Destination: the project-native feature filename discovered in Step 2.

In the new file, replace placeholders:

| Placeholder | Replacement |
|-------------|-------------|
| feature ID/title placeholder | the discovered ID and `<title>` |
| `**Layer:** [<layer-name>](../README.md)` | `**Layer:** [<layer>](../README.md)` |
| `**Status:** design` | leave as `design` |
| `**Branch:** feature/<slug>` | use `--branch` value or default |
| `**Started:** YYYY-MM-DD` | today's date |
| `**Owner:** <name>` | infer from git config user.name, or leave placeholder |

Leave Design / Plan / Verify / Conclusion section bodies as template
placeholders -- the user fills these.

### Step 5 -- Update layer README

Inspect `docs/layers/<layer>/README.md` for its existing feature index and
preserve its columns, ID form, ordering, and link style. Insert the new entry
only if a feature index exists and its row convention is understood:

```
| <project-id> | <title> | <project-native initial status> | YYYY-MM-DD | <project-native link> |
```

If the table has only known placeholder rows, replace only those placeholders.
If there is no compatible index, do not invent one; report that the narrative
was created without a README index.

### Step 6 -- Update feature_list.json (if present)

If `<repo>/feature_list.json` exists at repo root, parse it and use the
project's schema or validator plus a representative entry to construct a
native record. Preserve the existing top-level shape, field names, value
types, default status, evidence representation, ordering, and encoding.
Change only fields that the project convention establishes for a new feature
(such as its unique ID, title/name, description, document link, or initial
state).

Important encoding rule (per
`~/.claude/rules/api-utf8-posting.md`): write the JSON file with
`json.dump(data, f, ensure_ascii=False, indent=2)` to preserve any
Cyrillic in titles.

Do NOT change existing entries or add fields merely because this skill's old
example had them. Run the project-provided feature registry validator when one
exists. If the registry's required fields cannot be determined safely, leave
it unchanged and report that fact; the requested narrative remains valid.

If `feature_list.json` does not exist, do not auto-create it -- emit
a hint instead.

### Step 7 -- Confirm and suggest next step

Print a summary:

```
Created: <project-native feature-document path>
Updated: <README path or "not indexed; no compatible feature index">
Updated: <feature_list.json path and project-native ID, or "not changed; no safe registry mapping">

Suggested next steps:
1. Fill the Design section in <feature document>
   - Approach (one paragraph)
   - Invariants (IV-1, IV-2, ...)
   - Rejected alternatives
2. When Design is reviewed, change Status: design -> planning and fill Plan
3. Create the git branch: git checkout -b feature/<slug>
```

## Blueprints (files this skill writes from)

- `templates/kb-skeleton/docs/layers/_LAYER-TEMPLATE/features/_FEATURE-TEMPLATE.md` -- the source template

## Status lifecycle

The following lifecycle is the bundled long-run-project convention, not a
universal registry schema. Apply it only after Step 2 confirms that the target
project uses it; otherwise preserve the project's own lifecycle and mapping.

### Doc Status (narrative phase, in feature.md frontmatter)

Tracks where in the ULTRAPACK Design / Plan / Verify / Conclusion
journey the feature is.

```
design --> planning --> executing --> reviewing --> done
                                  \
                                   --> blocked --> executing
```

Six states: `design`, `planning`, `executing`, `reviewing`, `done`,
`blocked`. Transitions are manual edits. Once `done`, the feature doc
is read-only history; further changes go into a superseding feature.

### feature_list.json status (machine state, for tooling)

Tracks the machine-readable state used by build_kb_graph.py and
validate_kb_links.py.

```
not-started --> in-progress --> done
              \
               --> blocked --> in-progress
```

Four states: `not-started`, `in-progress`, `blocked`, `done`. `done` is
**one-way** (no rollback; regression becomes a new feature) per
[principle 27](https://github.com/AnastasiyaW/claude-code-config/blob/main/principles/27-feature-tracking.md).

### Mapping between the two

| Doc Status | feature_list.json status | Notes |
|------------|--------------------------|-------|
| design | not-started | newly created, no plan yet |
| planning | in-progress | plan being written |
| executing | in-progress | code being written |
| reviewing | in-progress | review/verify phase |
| blocked | blocked | identical |
| done | done | identical |

For a project that uses this convention, create the doc with `Status: design`
and the native JSON record with `status: "not-started"`. Subsequent transitions
are manual and follow that project's coordination rule.

## Gotchas

- **ID namespace is project-defined.** It may be global, per layer, or managed
  by a registry. Discover it before allocation; never treat `F-NNN` as a
  universal format.
- **Concurrent allocation.** Scanning and then writing is a race. Use the
  existing project coordinator or reserve the logical ID with the Git-ref
  helper before a document/registry mutation. A same-ID different-slug/layer
  claimant must conflict; re-inventory it, never overwrite it or guess that
  the durable reservation is stale.
- **Migration of in-flight features.** When migrating an existing
  feature into the new format, pass its project-native `--id` explicitly so the
  feature retains its prior ID in any links from PROBLEMS.md or
  handoffs. The skill will not auto-detect existing IDs.
- **Cyrillic titles + Windows.** Per global rule
  `api-utf8-posting.md`, when writing the markdown file or
  feature_list.json, always specify `encoding="utf-8"` explicitly to
  avoid mojibake on Windows.
- **Layer README table edit.** Preserve the project's existing columns and
  ordering. If the index cannot be interpreted safely, leave it unchanged and
  report the unindexed narrative rather than inventing a canonical 5-column
  row.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Layer does not exist" | `docs/layers/<layer>/` missing | Run `/layer-new <layer>` first |
| ID reservation conflict | Another request owns that logical ID | Re-inventory project state and use the next native candidate; never overwrite or delete the durable reservation |
| `feature_list.json` parse/schema error | Registry is invalid or uses an unknown convention | Preserve the narrative and do not write the registry; report the exact parser/schema failure and use a project-native adapter when its fields are established |
| Template missing on this machine | Different host / fresh clone | Pull from public repo: `gh api repos/AnastasiyaW/claude-code-config/contents/templates/kb-skeleton/docs/layers/_LAYER-TEMPLATE/features/_FEATURE-TEMPLATE.md` |
| Cyrillic in title shows as `?????` | File written without explicit utf-8 | Re-write the file with `encoding="utf-8"`; see `~/.claude/rules/api-utf8-posting.md` |

## Implementation note

This is a **scaffolding** skill: file copy + placeholder replacement +
small JSON merge. Keep it deterministic. The Design / Plan / Verify
sections of the produced document are meant for the user (or the
session that invoked the skill) to fill -- this skill does not
attempt to generate Design content from the title.

ID discovery reads only the sources that the project's convention declares.
Reserve the resulting logical ID atomically, then re-read mutable sources;
cache is not authority across a concurrent mutation.
