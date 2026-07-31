# Skill Tree Recovery — when the обвязка survives the move but the skills do not

Tags: обвязка, wiring, harness, skills, account-migration, silent-failure

A machine or account move can leave the wiring intact and the skills gone, with
nothing anywhere reporting a problem. The client starts, the hooks fire, the
skill directories are all still listed — and most of the catalog is simply not
offered to the model. This note describes the failure, how to confirm it, and
how to repair it.

## What it looks like

The only symptom is a short skill list. The user notices skills they know they
installed are not being suggested. Every mechanical check looks fine:

- the skill directories exist and `ls` counts them correctly;
- the client reports no error, because "no `SKILL.md` here" is not an error;
- `settings.json` is unchanged and every hook still runs.

This is the agent-legibility failure in its purest form: what the loader cannot
read is operationally absent, and nothing in the system is obliged to say so.

## The four causes, in the order they bite

**1. Dangling junctions or symlinks.** A tree assembled from links into another
profile keeps listing every entry after that profile is gone. On Windows a
junction to `C:\Users\<old-account>\...` still shows as a directory in
`Get-ChildItem`; on Linux the same holds for a symlink into a removed `/home`
user. The trap is in the diagnosis, not the filesystem: any check shaped like
`for d in root.iterdir() if d.is_dir()` **follows** the link, gets `False`, and
drops the entry without a word — so a tree that is 100% dead links is reported
as "no problems, 0 broken". Enumerate raw directory entries
(`os.scandir(..., follow_symlinks=False)`) and classify non-resolving ones
explicitly.

**2. Empty directory shells.** Copying a tree whose links already dangled
produces the directories and none of the files. The loader skips a directory
without `SKILL.md` silently. This is usually the largest bucket, and the
timestamps give it away: all shells share one creation minute.

**3. A UTF-8 BOM before the opening `---`.** The frontmatter parser does not
strip it, so the skill loads with a garbage description — typically the literal
string `---`. The skill is present but effectively un-triggerable, which reads
like the model ignoring it. Read `SKILL.md` with `utf-8-sig` when validating, or
the BOM cases stay invisible to your own checker too.

**4. A stale copy that lost its `name:` field.** It still loads under its
directory name, with degraded metadata and no disambiguation against
neighbouring skills.

## Confirming it

```bash
python scripts/recover_skill_trees.py --report
python scripts/recover_skill_trees.py --tree /path/to/suspect/tree --report
```

The report separates `BROKEN_LINK` (and prints where each link pointed),
`EMPTY_SHELL`, `BOM`, `NO_FRONTMATTER` and `NO_NAME`. A tree that has never been
moved should come back all-loadable; anything else names the cause.

Cross-check with the shell, because the two disagree in exactly the informative
way: a filtered listing that follows links will report fewer entries than a raw
one. That gap **is** the count of dead links.

## Repairing it

```bash
python scripts/recover_skill_trees.py --donor /path/to/old-profile/skills --dry-run
python scripts/recover_skill_trees.py --donor /path/to/old-profile/skills --fix-broken
```

The repair is a **union fill**: any skill directory that already carries a
`SKILL.md` is authoritative and is never overwritten, so the run is idempotent
and safe to repeat after the next move. Nothing is deleted — a directory with no
donor anywhere is reported and left alone, and a dead link blocks its own repair
rather than being silently replaced, because removing it is a deletion and that
stays a human decision.

## Merging two live trees — do not pick a side

When both trees have been edited independently (`~/.claude/skills` read by Claude
Code, `~/.agents/skills` shared with Codex), some files will differ. Resolve them
per file, on evidence; neither tree is automatically newer. In a real recovery of
32 diverged skills the split ran both ways:

- the shared tree held richer frontmatter (added "Do NOT use …" disambiguation),
  while the client tree held newer bodies referencing skills added later;
- the shared tree had also had a blind product-name search/replace applied, which
  invented a nonexistent npm package and broke every `~/.claude/scripts/...` path
  it touched. Wholesale-copying that side would have shipped fiction.

Two mechanical rules make the rest cheap: if the bodies are byte-identical, take
the longer frontmatter; and a skill that references its own `scripts/` directory
must keep the path of the tree it sits in, so never propagate that line.

## Preventing the next one

- Prefer copies over cross-profile links for anything the agent must read. A link
  saves disk and costs the whole catalog the day the profile is renamed.
- Validate with `utf-8-sig` and raw directory enumeration, or your validator
  inherits the same blind spots as the loader.
- Treat "count of directories" as meaningless on its own. The number that matters
  is how many carry a readable `SKILL.md`, and only a check that follows through
  to the frontmatter can report it.

## Related

- [runtime-wiring.md](runtime-wiring.md) — which client reads which directory, and
  the proof command for each.
- `scripts/sync_skills_to_codex.py` — the other direction: deploy this repository
  into an active skills directory when the repo *is* the source of truth.
- `rules/silent-failure-detection.md` — the general principle: presence in a
  manifest is not behaviour.
