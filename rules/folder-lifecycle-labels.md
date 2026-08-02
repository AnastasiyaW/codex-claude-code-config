# Folder Lifecycle Labels

Every new non-obvious directory should carry a machine-readable cleanup label.
The marker file is `.folder-meta.json` in the directory root.

## Labels

- `PROJECT_ROOT`: intentional root for a project/worktree. Do not delete by cleanup scripts.
- `GIT_BACKED`: code/config exists in GitHub or another git remote; local clone can be recreated after verifying clean git state.
- `TEMP_REPRODUCIBLE`: scratch/test/probe files; safe to delete after the task if no running process uses it.
- `DATASET_REBUILDABLE`: media dataset generated or downloadable from manifests/scripts; code and manifests are the source of truth, bulky files can be removed after verification.
- `CACHE_GENERATED`: cache/model/build/download cache; safe to remove when the producer can regenerate it.
- `ARTIFACT_REGENERABLE`: reports/previews/contact sheets generated from code or source data; delete only after preserving source command/manifest.
- `KEEP_MANUAL`: contains manual/user-created/irreplaceable data; never bulk-delete without explicit user confirmation.
- `NEEDS_REVIEW`: cleanup safety is unknown; inspect before moving or deleting.

## Marker Schema

```json
{
  "label": "TEMP_REPRODUCIBLE",
  "project": "example-app",
  "created_by": "codex",
  "created_at": "2026-07-03",
  "safe_to_delete": true,
  "source_of_truth": "git, manifest, or upstream URL",
  "rebuild": "command or short explanation",
  "notes": "why this directory exists"
}
```

## Cleanup Policy

- Delete candidates: `TEMP_REPRODUCIBLE`, `CACHE_GENERATED`, `ARTIFACT_REGENERABLE`.
- Conditional delete candidates: `GIT_BACKED` only after git status is clean and remote exists; `DATASET_REBUILDABLE` only after source manifests/scripts are verified.
- Never delete automatically: `PROJECT_ROOT`, `KEEP_MANUAL`, `NEEDS_REVIEW`.
- Do not trust names alone. Folder names are hints; `.folder-meta.json` is the cleanup contract.

## Dataset Rule

For datasets, keep code, manifests, captions, indexes, hashes, and rebuild commands.
Bulky images/masks/previews may be removable only when the marker is
`DATASET_REBUILDABLE` and the source-of-truth path is verified.
