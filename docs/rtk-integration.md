# RTK Integration

RTK (Rust Token Killer) is adopted here as an optional, measured output
compression layer. It is not a replacement for destructive-command guards,
Git source-of-truth checks, tests, or full-output verification.

## Decision

Use RTK `v0.43.0` when its executable passes the pinned SHA-256 check. Wire its
native `hook claude` processor into Claude Code for `Bash` and `PowerShell`.
On Windows the generated hook command deliberately uses a `C:/...` executable
path: Claude invokes the command through a shell, where bare backslashes are
escape characters and can collapse the path into a nonexistent file name.
Codex uses the upstream-supported instruction-level integration (`AGENTS.md`);
there is no transparent Codex command-rewrite hook in the upstream integration.

The executable is deliberately not stored in this public repository. Install it
from the official Windows release, verify it, and keep it in a private local
tool directory.

Pinned release:

- Asset: `rtk-x86_64-pc-windows-msvc.zip`
- Version: `0.43.0`
- Release ZIP SHA-256: `7c5e4a2ef816a4d4ed947ddd74ca3df851fc39ea87d49a3ca2bf3abc515a016b`
- Extracted `rtk.exe` SHA-256: `a715e989bcebfc208f388cf5adaaa9953cbf1127b081bc09c4ef02e7d7fea39f`
- Source: `https://github.com/rtk-ai/rtk/releases/tag/v0.43.0`

## Install And Verify

Place the verified executable in a private path, then run:

```powershell
python scripts/rtk_integration.py verify-archive --archive C:\downloads\rtk-x86_64-pc-windows-msvc.zip
python scripts/rtk_integration.py verify --binary C:\private-tools\rtk.exe
python scripts/rtk_integration.py install-claude-hook `
  --binary C:\private-tools\rtk.exe `
  --settings $HOME\.claude\settings.json `
  --apply
```

The archive and executable checks are separate because the GitHub digest covers
the ZIP, not an individual file inside it. The installer is idempotent, creates
a `.bak` before changing settings, and does not download or execute anything by
itself.

## Safe Usage Policy

Good candidates are repetitive diagnostic output: `git status`, `git diff`,
`git log`, `cat`/`read`, `rg`, directory listings, and test runners with stable
failure summaries. Use `rtk proxy <command>` or `RTK_DISABLED=1` when the exact
raw output is evidence, when inspecting a novel tool, or when a log's ordering
and every line matter.

The existing safety hooks remain authoritative. RTK hooks must fail open: a
missing binary, invalid input, or rewrite failure leaves the original command
untouched. RTK must never be used as permission to delete, force-push, drop
data, or skip a test.

## Measured Local Proof

On 2026-07-13, the pinned Windows binary was verified against its release digest
and run against the private `chat-archive` checkout:

- `rtk git status --short`: exit `0`, same empty output as raw Git on a clean tree.
- `rtk git log --oneline -10`: exit `0`, intentionally no extra compression because
  the input was already compact.
- `rtk read README.md`: exit `0`; readable output remained intact.
- `rtk test python -m unittest tests.test_archive_system`: exit `0`, `11 tests`
  and `OK` preserved in the filtered output.
- `rtk err cmd /c exit 7`: exit `7`; failure status was preserved and surfaced.
- `rtk grep` could not resolve `grep` on this Windows host. The native `rtk rg`
  path worked, so the integration must not assume a Unix `grep` binary exists.

The numbers advertised by RTK are estimates, not acceptance criteria. Adoption
is justified by preserved exit codes, readable failures, and the ability to
restore raw output, not by a claimed percentage alone.
