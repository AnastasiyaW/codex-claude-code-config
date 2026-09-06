---
name: desktop-sessions-discovery
description: Discover, search, and selectively restore Claude desktop app sessions hidden across multiple accountIds. Use when user mentions "missing sessions after account switch", "lost desktop sessions", "where do my old sessions live", or runs multiple Claude accounts on the same machine. Do NOT use for Claude Code CLI session history or resuming work within one session — this only recovers the native desktop app's per-accountId session files; for in-session continuity use handoffs.
---

# Claude Desktop Sessions Discovery Toolkit

Claude desktop app (Mac/Windows native) stores sessions per `<accountId>/<orgId>/`. When you switch accounts, old sessions become invisible in UI — they remain on disk but `LocalSessionManager.loadSessions()` only reads the active accountId folder.

Related reports: [#48511](https://github.com/anthropics/claude-code/issues/48511) was opened
2026-04-15 and is closed as not planned; [#26452](https://github.com/anthropics/claude-code/issues/26452)
was opened 2026-02-18 and remains open as checked 2026-09-06. These are version-specific user
reports, not proof that the installed build has the same cause or that a fix does not exist.

This skill is a community workaround. Use at your own risk — see Caveats.

## Storage paths (reverse-engineered, NOT in official Anthropic docs)

| Install type | Path |
|---|---|
| **Win32 .exe install** | `%APPDATA%\Claude\claude-code-sessions\<acct>\<org>\local_<sid>.json` |
| **Windows MSIX (Microsoft Store)** | `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code-sessions\<acct>\<org>\` — issue [#48362](https://github.com/anthropics/claude-code/issues/48362) reports an atomic-rename failure in a specific environment; verify the current local error before attributing a missing session to it. |
| **macOS** | `~/Library/Application Support/Claude/claude-code-sessions/<acct>/<org>/local_<sid>.json` |
| Legacy (pre-Feb 2026) | same path, but folder name was `local-agent-mode-sessions/` |

Source: bundled JS `.vite/build/index.js` line 771: `const $6t="claude-code-sessions"`. May change in any release.

## Schema of `local_*.json`

```json
{
  "sessionId": "uuid",
  "cliSessionId": "uuid",
  "cwd": "C:\\path\\to\\project",
  "originCwd": "...",
  "createdAt": <unix ms timestamp OR ISO string>,
  "lastActivityAt": <unix ms timestamp OR ISO string>,
  "model": "claude-opus-4-7-...",
  "effort": "default",
  "isArchived": false,
  "title": "Human-readable title shown in UI",
  "permissionMode": "default",
  "remoteMcpServersConfig": [],
  "completedTurns": 12
}
```

NB: timestamp format is inconsistent — some sessions use Unix ms (int), others ISO string. Parser must handle both.

## Four operations

### 1. Registry — interactive HTML browse (recommended starting point)

Script: `scripts/sessions_registry.py`

```bash
python scripts/sessions_registry.py                # generate + auto-open in default browser
python scripts/sessions_registry.py --no-open      # generate only
python scripts/sessions_registry.py --output /custom/path.html
```

Produces a self-contained HTML registry with:
- **Live JS search** by title / cwd / sessionId substring
- **Sort** by recency / turns count / title A-Z / size
- **Filter**: hide 0-turn auto-runs ("Morning digest", "Observer daily analysis"), hide already-restored
- Per-accountId **collapsible sections**, active accountId highlighted green
- **"Restore" button** per session — copies command to clipboard
- **"RESTORED" badge** for sessions already migrated (read from `~/.claude/desktop-migrations.jsonl`)
- Includes BOTH `claude-code-sessions/` (current) AND `local-agent-mode-sessions/` (legacy pre-Feb 2026)

Use when the user wants to browse the archive visually. When the user has already selected
and authorized a specific restore, the agent performs the scoped dry-run, backup/copy and
verification itself through available approved tools; do not assign clipboard/terminal work
to the user. A generated restore command is an input to inspect, not authorization by itself.

### 2. Inventory — full picture (text)

Script: `scripts/sessions_inventory.py`

Scans all `<accountId>/<orgId>/local_*.json`, prints grouped table with title/cwd/size/lastActivityAt sorted by recency. Includes cross-account view (which projects appear in multiple accountIds — useful when same user worked on the same project under different accounts).

### 3. Find — search by title/cwd substring (text)

Script: `scripts/sessions_find.py`

```bash
python sessions_find.py "<query>"                  # substring in title or cwd
python sessions_find.py "<query>" --account <prefix>  # filter by accountId
python sessions_find.py --since 2026-04-01         # date filter
python sessions_find.py --untitled                  # parse-failed or empty
```

Output is top-N matches sorted by recency, with copy-pasteable restore command.

### 4. Restore — selective single-session migration

Script: `scripts/sessions_restore.py`

```bash
python sessions_restore.py <sid8>             # auto-detect active accountId
python sessions_restore.py <sid8> --to <acct> # explicit target
python sessions_restore.py <sid8> --dry-run   # plan only
```

Behaviour:
1. Find source session by sessionId substring (8 chars usually unique)
2. Detect active accountId by latest mtime (heuristic)
3. Copy `local_<sid>.json` into `<targetAcct>/<sameOrgId>/`
4. **Verify** byte-for-byte match before declaring success (proof loop)
5. Append to `~/.claude/desktop-migrations.jsonl` audit log
6. Source kept as backup, never deleted

After a verified copy, inspect the current app's documented reload/restart requirement and
active work before restarting. File parity alone does not prove a session is visible or resumable.
The default target-account detection is an mtime heuristic: inspect the signed-in destination
and use explicit `--to` for an authorized restore; never treat newest mtime as account authority.

## Caveats and risks

### v2.1.9+ regression (issue [#18645](https://github.com/anthropics/claude-code/issues/18645))
Historical reports described machine-origin validation. Same-machine success or cross-machine
failure from those builds does not establish current compatibility. Check the installed version,
actual storage and error before using this workaround; do not predict future validation changes.

### Reported disk-image layout (issue [#54428](https://github.com/anthropics/claude-code/issues/54428))
The linked historical report describes a disk-image storage variant. Discover the installed
layout first; these scripts only support the enumerated JSON layouts. Do not manipulate disk
images or infer an announced roadmap from an issue. An unsupported layout is a measured limit.

### Reported MSIX rename failure (issue [#48362](https://github.com/anthropics/claude-code/issues/48362))
The issue reports EXDEV during atomic rename in a specific MSIX environment. Check current
package version, path and observed error before attributing missing history to it. Do not switch
installation channels or claim all Store sessions fail based on that historical report.

### Mass merge wrecks UI usability
With 700+ sessions in one accountId, the app's session list becomes unreadable. Prefer selective restore one-at-a-time when you actually need a specific thread.

## Recommended long-term

Preserve the project's canonical transcript archive and durable task/handoff state regardless
of UI choice. CLI and desktop have different persistence/restore contracts; neither is a
substitute for verified backups. Choose a runtime from the required capabilities and observed
behavior, not a universal recommendation to move serious work away from desktop.

## Files

- `scripts/sessions_registry.py` — interactive HTML registry, opens in browser
- `scripts/sessions_inventory.py` — full text table (grep-friendly)
- `scripts/sessions_find.py` — substring search
- `scripts/sessions_restore.py` — selective copy with verify and audit log

## macOS specifics

All four scripts detect platform via `sys.platform` and pick the right path automatically — no flags needed on Mac.

- **Storage path**: `~/Library/Application Support/Claude/claude-code-sessions/<acct>/<org>/local_<sid>.json`
- **Legacy path**: `~/Library/Application Support/Claude/local-agent-mode-sessions/<acct>/<org>/local_<sid>.json`
- **HTML auto-open**: uses `open <html>` (system default browser)
- **Different packaging**: the Windows MSIX report does not establish macOS behavior; verify the installed macOS build and observed error independently.
- **Spotlight bonus**: `mdfind -onlyin ~/Library/Application\ Support/Claude/ "<query>"` works on session JSONs (indexes content), faster than `find` for one-off lookups
- **Reveal in Finder** after restore: `open -R ~/Library/Application\ Support/Claude/claude-code-sessions/<acct>/<org>/local_<sid>.json`

## License

Public domain. This is a community session-file discovery and recovery tool; its usefulness depends on the verified local layout and failure, not a universal product-bug diagnosis.

## See also

- claude-sync (CLI only): https://github.com/tawanorg/claude-sync
- claude-session-restore (CLI only): https://github.com/ZENG3LD/claude-session-restore
- CLI multi-account guide: https://medium.com/@buwanekasumanasekara/setting-up-multiple-claude-code-accounts-on-your-local-machine-f8769a36d1b1
