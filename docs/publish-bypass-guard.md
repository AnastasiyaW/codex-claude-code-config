# publish-bypass-guard: threat model and residual risk

`hooks/publish-bypass-guard.py` blocks Bash and PowerShell commands that would publish to GitHub
without the global pre-push leak scan (`git config --global core.hooksPath` ->
`pre-push` -> `pre-push-public-repo-scan.py`). The route table and the approval rule live in the
hook docstring.

## What it is for

The guard catches agent mistakes and accidental routes: a `--no-verify` added to get past a slow
hook, a repo whose `core.hooksPath=.githooks` silently replaced the global hooks, a `gh repo edit
--visibility public`, a release upload, an API write. It reads commands as operations after shell
escape removal (bash backslashes, PowerShell backticks) and decodes `-EncodedCommand`.

It does not stop deliberate masking. Text matching cannot win against an adversary; this is the
same stance as `human-confirmation-guard`.

## Repo-local hooks

A repo that sets `core.hooksPath` to its own folder passes only when its `pre-push` is
byte-identical (after CRLF -> LF) to [`hooks/pre-push-chain.sh`](../hooks/pre-push-chain.sh), or
to the global `pre-push` itself. Copy the chain file unchanged; it runs the global pre-push and
refuses the push when the global hook is missing. Any edit, even a comment or an extra `exit`,
makes the push block: deciding "does this script call the scan" by parsing shell was bypassable.

## Not covered (residual risk)

- Interpreters and script files: `python -c` that assembles the command from string pieces,
  `node -e`, `bash x.sh`, a script written to disk and run in a later call.
- Other publishing surfaces: issues and comments (`gh issue create`, `gh pr comment`), GitHub
  Pages, wikis, package registries, non-GitHub hosts.
- Environment carried in from outside the command, such as a shell profile.

The backstop for secrets is GitHub's server-side secret-scanning push protection on the public
repositories. The pre-push leak scan stays the only check for private names and personal data, so
every route above that skips it is blocked unless the owner names the action in chat.
