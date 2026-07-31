# Rule - Verify the code is current BEFORE acting on it

Global rule, every repository. A specialization of [no-guessing.md](no-guessing.md): the ground
truth is what is actually deployed and what `origin` actually holds, never the local working copy
and never memory.

## Rule

**Any work in a git repository starts by establishing where the local copy stands** — relative to
`origin`, and relative to what is actually running. Before the first edit, diagnosis, or deploy.
Not "later, if something looks odd".

### Mandatory pre-flight

```bash
git fetch --all --prune
git status -sb                       # branch, ahead/behind
git log --oneline -1 HEAD
git rev-list --left-right --count HEAD...origin/<main-line>
```

If the work concerns a deployed service, also establish which commit is actually running, rather
than which commit the repository holds:

```bash
docker inspect <container> --format '{{json .Config.Labels}}' \
  | tr ',' '\n' | grep -i 'working_dir\|config_files'
# then, in that working_dir:
git log --oneline -1
```

Compare the running commit against `origin/<main-line>`. **Production behind origin is a deploy
problem, not a code problem** — do not rewrite code to fix a deployment gap.

### If the local copy is stale

1. Synchronize first (`git stash -u` your work → checkout the live line → `pull --ff-only`), then
   build on top of current code.
2. Never deploy a stale branch — that silently rolls production back.
3. Check whether the task is already solved in the newer commits
   (`git log <running>..origin/<main>` plus `git grep` on the key terms) before writing your own.

## Source hierarchy

Strongest to weakest. Never use a weaker source as primary without checking it against a stronger one:

1. **The commit actually running** in production
2. **`origin/<main-line>` after a fetch**
3. **The local working directory** — may sit on a stale or unrelated branch
4. **Memory and previous sessions** — frozen in time; branch names and deploy paths change, verify

## Beyond deploys: any tool that copies one tree over another

The same check applies to config sync, template installers, vendoring scripts, and anything else
that overwrites files in bulk. Such a tool usually copies in one direction and has no notion of
which side is newer, so running it from a stale tree silently destroys newer work on the other side
— and it reports that as an ordinary "updated" line, not as a warning.

**Before running any bulk copy: fetch, confirm the local tree is not behind, and read the dry-run
diff.** Treat a large deletion in the report as a stop, not as a detail.

## Real cases

- **Stale branch, wasted session.** Work proceeded on a local branch without an initial `git fetch`.
  Production was running a different branch entirely and `origin` had moved dozens of commits ahead;
  the problem being debugged had already been fixed there, more correctly. The root-cause analysis
  was built on code that no longer existed. Thirty seconds of `git fetch` would have prevented it.
- **A sync run from a stale tree.** A one-way config sync, executed with the local copy several
  commits behind, proposed reverting the two newest commits on the other side, cutting 162 lines
  from a documentation tree, and replacing a deliberately anonymized credit line with a real
  person's name in a public repository. The privacy scanner passed it, because its markers listed
  hosts and paths, not names. It was caught only by reading the diff before committing.

## Anti-patterns

- Opening a file and editing it without `git status` / `git fetch`.
- Deploying your branch without checking what is actually running.
- Building a root-cause analysis on a local copy you have not confirmed is current.
- Trusting memory for branch names and deploy paths without verification.
- Running a bulk-copy tool and reading only its summary line instead of its diff.

## Related
- [no-guessing.md](no-guessing.md) — verifiable ground truth; this is its git specialization
- [verify-at-consumer.md](verify-at-consumer.md) — the same logic for integrations
- [safety.md](safety.md) — pre-flight checks when entering an unfamiliar repository
