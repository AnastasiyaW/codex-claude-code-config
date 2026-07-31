# Silent Failure Detection - Plugin CLI Prerequisites

## Principle

A Claude Code plugin can be `enabled: true` in `settings.json` while
its hooks invoke an external CLI that is not installed on the system.
The hook exits with non-zero status, Claude Code logs it and moves
on. The user gets an **illusion of protection** while the actual
protection layer is a no-op.

This is a specialization of [system-verification-independent.md](system-verification-independent.md):
plugin manifest (`enabled=true`) is not behavior (CLI missing → silent
no-op on every relevant tool call).

## Real case that motivated this rule

`semgrep@claude-plugins-official` was enabled. Its `hooks.json` invokes
`semgrep mcp -k post-tool-cli-scan` on every Write/Edit. On a Windows
machine `shutil.which("semgrep")` returned `None`. Every Write/Edit
for **the entire session** had triggered a missing-CLI failure. No
warnings surfaced. The gap was discovered only by an independent
`where.exe semgrep` check during an unrelated audit.

Similar risk applies to any plugin with an external-CLI dependency:
`gh` for github plugin, `stripe` for stripe plugin, language servers
(`pyright-langserver`, `clangd`, `gopls`, etc.) for the LSP plugins.

## Solution: SessionStart prerequisite verifier

[`scripts/verify_plugin_prerequisites.py`](../scripts/verify_plugin_prerequisites.py)
runs as a SessionStart hook. Algorithm:

1. Read `~/.claude/settings.json` → take `enabledPlugins` (only ids
   with value `true`).
2. For each `plugin_id` in the `PLUGIN_CLI_REQUIREMENTS` map, check
   `shutil.which(cli)` for every required CLI.
3. Print a warning to stdout (visible at SessionStart) for each
   missing plugin↔CLI pair.
4. `exit 0` — informational only, do not block the session.

`shutil.which` is preferred over `where.exe` / shell calls because it
is cross-platform and respects `PATHEXT` on Windows (`.exe`, `.bat`,
`.cmd` all checked).

## How to extend the requirements map

**Do not add entries by guessing.** Before adding a plugin to
`PLUGIN_CLI_REQUIREMENTS`:

1. Open `~/.claude/plugins/cache/<plugin>/<version>/hooks/hooks.json`.
2. Find every `"command":` line in `hooks`.
3. If the command invokes an external binary (not
   `python3 ${CLAUDE_PLUGIN_ROOT}/...` or another bundled script),
   record the binary name.
4. Also inspect `.mcp.json` — an MCP server entry can carry its own
   CLI dependency (e.g. `{"command": "semgrep", "args": ["mcp"]}`).

Example trace for the semgrep plugin:

```jsonc
// hooks/hooks.json
{"command": "semgrep mcp -k post-tool-cli-scan"}   // needs `semgrep`

// .mcp.json
{"mcpServers": {"semgrep": {"command": "semgrep", "args": ["mcp"]}}}
```

→ map entry: `"semgrep@claude-plugins-official": ["semgrep"]`.

## Related rules

- [`system-verification-independent.md`](system-verification-independent.md) — the parent principle ("name ≠ behavior" for control systems).
- [`no-guessing.md`](no-guessing.md) — the claim "this CLI exists" requires verification.
- [`safety.md`](safety.md) — mechanical defence via hooks.

## What this does NOT cover

- **MCP servers bundled inside third-party plugins**: if a Node-based
  MCP server fails to start because Node is missing, Claude Code
  does not surface that explicitly. A separate mechanism is needed
  (probe each `mcp__<server>__*` tool's availability on startup).
  TBD.
- **Hooks failing due to permissions / wrong cwd / missing env**:
  only the missing-binary case is detected. A hook that crashes
  because of a missing env var (`GITHUB_TOKEN`, `STRIPE_API_KEY`,
  etc.) is not flagged. TBD if it becomes a recurring problem.
- **Bundled-Python-script failures**: a plugin that ships its own
  `${CLAUDE_PLUGIN_ROOT}/hooks/foo.py` cannot be diagnosed by this
  approach — that case requires either running each script in a
  dry-run mode or inspecting Claude Code logs.

These gaps are **known and documented here** so the rule does not
give a false sense of protection.
