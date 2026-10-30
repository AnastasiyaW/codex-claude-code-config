# Team distribution: Claude Code plugin and Codex update

This repository is a Claude Code plugin named `harness`. A team installs it from a
marketplace and Claude Code keeps it current. Codex has no plugin auto-update, so
Codex users keep a clone and run one update command.

## What the plugin ships

| Component | Source in this repo | How it loads |
|---|---|---|
| Skills | `skills/<name>/` and every category in `.claude-plugin/plugin.json` `"skills"` | `/harness:<skill>` or by description |
| Agents | `agents/*.md` | `harness:<agent>` |
| Workflows | `workflows/*.js` | `/harness:<workflow>` |
| Hooks | `hooks/hooks.json`, generated from `SAFE_DEFAULTS` plus the `PLUGIN_EXTRAS` entries of `EXTRAS` in `scripts/install_hooks.py` | registered at session start |
| Tools | `scripts/` (for example `mutation_probe.py`, `crap_probe.py`, `failure_mine.py`, `harness_improvement_pilot.py`) | run by path under the plugin root |
| Rules | `rules/*.md` | `hooks/plugin-rules-context.py` injects an index at session start; the agent reads a rule file when its topic applies |

A plugin cannot ship `CLAUDE.md` or `rules/` as context (Claude Code docs,
"Add components to a plugin"). The SessionStart index replaces them.

Hook commands use exec form, `python` plus `${CLAUDE_PLUGIN_ROOT}/hooks/<script>`, so
the published file holds no user path. Requirement: the command `python` (3.10+) on
`PATH`. Check it with `python --version` before installing. Without it no hook runs
and the guards fail open (Claude Code reports a hook error and carries on):

- macOS ships only `python3`. Install Python from python.org or Homebrew and make
  `python` resolve, for example `ln -s "$(command -v python3)" /usr/local/bin/python`.
- Windows: if `python` opens the Microsoft Store, install Python from python.org with
  "Add to PATH" and turn off the `python.exe` app execution alias.

### publish-bypass-guard on a teammate's machine

The plugin ships `hooks/publish-bypass-guard.py` (PreToolUse, Bash and PowerShell; see
[publish-bypass-guard.md](publish-bypass-guard.md)). It finds its own helpers
(`pre-push-chain.sh`, `human-confirmation-guard.py`) next to itself, so it works from
the plugin cache. Its approval log is `~/.claude/logs/publish-approvals.jsonl`.

It allows a push only through the global pre-push leak scan, or to a repository that
`gh` confirms PRIVATE or INTERNAL. On a machine without that scan:

- a push to a private repository passes (needs `gh auth login`, so visibility can be read);
- a push to a public repository, or one whose visibility is unknown, is blocked.

The global wrapper `scripts/git-hooks/pre-push` is not yet portable: it requires
`~/.claude/scripts/pre_push_claude_attribution.py`, which is not in this repository,
and on Windows looks for Python only in uv's interpreter folder; it also expects the
scanner in a clone at `~/.claude/claude-code-config`. Installed on another
machine it blocks every push, private ones included, so do not run
`install_hooks.py --git-hooks` there until the wrapper is fixed. Public pushes from such a
machine go through the owner.

### Token savers

The plugin also ships two hooks that cut token spend:

- `hooks/benjamin-plus-inject.py` (SessionStart on startup, resume, clear and compact)
  injects the Benjamin-Plus working habits from `references/benjamin-plus/`. Opt out
  with `CLAUDE_SKIP_BENJAMIN=1` or a `.claude/.skip-benjamin` file in the project.
  If `settings.json` already registers `benjamin-plus-inject.py`, remove that entry
  when installing the plugin, or the text is injected twice.
- `hooks/rtk-plugin-hook.py` (PreToolUse, Bash only) passes the command to
  RTK, which rewrites `git status` into `rtk git status` and compresses the output.
  It acts only when `rtk` on `PATH` matches the pinned hash in
  `scripts/rtk_integration.py` (Windows release 0.43.0); otherwise the command runs
  untouched. Install RTK by [rtk-integration.md](rtk-integration.md) and put the
  verified `rtk.exe` on `PATH`. Skip `install-claude-hook` when the plugin is
  installed, or RTK runs twice on every command. macOS and Linux binaries are not
  pinned yet, so there the hook stays silent.

After a change to `SAFE_DEFAULTS`, `PLUGIN_EXTRAS`, `PLUGIN_ONLY` or `skills/` categories run:

```bash
python scripts/plugin_build.py          # regenerate hooks/hooks.json
python scripts/plugin_build.py --check  # CI runs this; fails on a stale file or an unlisted skill category
```

## Versions and updates

`plugin.json` deliberately has no `version`. Claude Code takes the version from the
marketplace entry, or from the commit SHA when no entry sets one.

- The public marketplace in this repo (`.claude-plugin/marketplace.json`, name
  `aw-harness`) sets no version, so installs follow `main` commit by commit.
- A team marketplace can list this repo with a `github` source pinned by `sha` and
  its own `version`. Its release job raises the version when `main` moves; users
  get the new copy only when the version changes.

Auto-update is off for every third-party marketplace by default. Turn it on with
`"autoUpdate": true` on the marketplace entry under `extraKnownMarketplaces` in the
user settings, or in `/plugin` -> Marketplaces -> Enable auto-update. Claude Code
then refreshes in the background after the first message of an interactive
session and asks for `/reload-plugins`; the new version loads on the next launch
in any case.

## Public install

```bash
claude plugin marketplace add AnastasiyaW/codex-claude-code-config
claude plugin install harness@aw-harness
```

Without a GitHub SSH key set `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` first.

On Windows a long `CLAUDE_CONFIG_DIR` (for example a test profile deep in a temp
folder) makes `marketplace add` fail with `Filename too long`: the clone path
under `plugins/marketplaces/` passes the 260-character limit. Use a short profile
path, or run `git config --global core.longpaths true`.

## Codex: one command

Clone once to the canonical place, then update with one command:

```bash
git clone https://github.com/AnastasiyaW/codex-claude-code-config ~/.claude/claude-code-config
python ~/.claude/claude-code-config/scripts/codex_update.py
```

`codex_update.py` refuses local edits in tracked files, runs `git pull --ff-only`,
`install_hooks.py --codex` and `sync_skills_to_codex.py --apply`, and stops with
exit 1 on the first failed step. `--extras` also registers the opt-in hooks.
Restart Codex sessions afterwards.

To run it daily on Windows:

```powershell
schtasks /Create /SC DAILY /ST 09:00 /TN "harness-codex-update" /TR "python %USERPROFILE%\.claude\claude-code-config\scripts\codex_update.py"
```

On macOS or Linux, a crontab line:

```bash
0 9 * * * python ~/.claude/claude-code-config/scripts/codex_update.py >> ~/.codex/harness-update.log 2>&1
```
