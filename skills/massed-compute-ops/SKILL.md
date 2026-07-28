---
name: massed-compute-ops
description: "Compatibility alias for the provider-specific Massed Compute workflow. Use when the user explicitly invokes massed-compute-ops or asks for legacy Massed Compute recipes; route new or implicit remote GPU/server work to remote-compute-ops. Do not use as the primary workflow for RunPod, owned servers, or bridge/API connection policy."
---

# Massed Compute compatibility alias

The canonical workflow is `$remote-compute-ops`. Use it for all new or implicit
remote-compute work so Massed Compute, RunPod, and
owned servers share the same bridge reuse, bounded API, lifecycle, and handoff
rules.

Keep this skill for explicit legacy invocations and Massed-specific recipes:

1. Read [references/recipes.md](references/recipes.md) for the live Massed MCP
   endpoint and provider-specific recipes.
2. Follow the canonical skill's transport, confirmation, reconciliation, and
   credential rules.
3. Use the Massed MCP adapter only for Massed inventory, billing, instances, and
   SSH-key operations; do not copy its provider-specific tool names into other
   providers' workflows.

## Gotchas

- A legacy invocation does not authorize a new API or SSH connection when an
  existing bridge/session can be reused.
- A timed-out launch may have succeeded; reconcile by instance UUID/name before
  retrying.
- Provider passwords and bearer tokens never belong in chat, this alias, Git, or
  handoff files.

## Troubleshooting

- **The old name is selected for RunPod or an owned server** -> switch to
  `$remote-compute-ops` and load the provider adapter from its references.
- **Massed mutation tools are absent** -> verify key scope; do not compensate with
  repeated ad-hoc requests.
