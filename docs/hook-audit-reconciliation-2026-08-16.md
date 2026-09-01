# Hook-audit reconciliation — 2026-08-16

This note corrects the numerical claim in the original round-seven receipt.
That receipt listed twelve commands but stated "190 checks across thirteen
suites". Its own listed totals sum to 178, so neither number was a valid
measurement. Historical receipt files are preserved; this is the replacement
measurement and its executable source. The table below is updated when the
executable corpus gains a suite; it is not the historical round-seven claim.

## Current guard corpus

Run:

```text
python -B hooks/tests/run_guard_regressions.py
```

The runner fixes `HOOKS_DIR` to the hook tree under test, runs these fourteen
suites, and derives the total from their actual `all N … correct` output:

| Suites | Checks |
|---:|---:|
| rounds 1–6 | 118 |
| round 7 | 18 |
| shared matcher / transfer / delivery / PowerShell / live smoke | 55 |
| dynamic PowerShell data-to-code guard | 24 |
| proof-executor permission boundary | 12 |
| **total** | **227** |

Round seven now permanently covers the measured redirect/group bridges that
must remain blocked: write-to-file then `bash`, process substitution, group
pipe to a shell, `tee` then `bash`, and a grouped remote here-doc. Its six
inert controls remain part of the same corpus.

## Source-of-test invariant

Each suite resolves the sibling `hooks/` directory by default and accepts an
explicit `HOOKS_DIR` override. A worktree run consequently tests that worktree,
not the installed `~/.claude` copy; the old delivery test's direct reference to
the legacy `~/.claude/hooks` tree has been removed.

## Tree-drift invariant

`hook-tree-drift-check.py` still reads `settings.json` as the authority for
which entry script runs. It also now compares `safety_common.py` across the
canonical/legacy hook-tree pair: the matcher is imported rather than directly
registered and was therefore the precise class of live-versus-shadow drift that
the first version missed. Its self-test includes that dependency shadow. Private
and utility script trees are intentionally outside this comparison because a
same-named local helper is not evidence that it shares the guard contract.

## Task loop invariant

`hooks/task-cycle-controller.py` is documented, contract-tested, and paired
with a `findings.json` task template. A recurring worker calls `reconcile`,
then follows exactly the JSON decision from `next`: a focused test, a real
runtime trace, and independent fresh review for internal work; or a timestamped
external recheck. Static prose cannot qualify as an idle state.
