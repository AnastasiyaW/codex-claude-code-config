# 30. Gates That Cannot Bootstrap Themselves

A harness check that switches on only when its own artifact is already present protects
every project except the ones that never set it up. That is the opposite of what you want,
and because the check is *designed* to be silent there, nothing ever reports the hole.

This is the failure mode behind "the agent seems to know nothing about this project" — the
harness is installed, the hooks fire, the rules load, and the one directory that most needs
supervision is structurally exempt from all of it.

## The shape

Most opt-in gates are written like this, for good reasons:

```python
if not (project / ".mytool" / "config.json").exists():
    return 0          # not a <mytool> project -- stay silent
```

Silence-when-not-adopted is correct for a tool that would otherwise nag every unrelated
repository. The bug is that **adoption is exactly the thing the gate could have checked**,
and the population that fails the check is precisely the population that needs telling.

Three variants, all observed in one working session:

| Gate | Exemption | What it cost |
|---|---|---|
| Long-run project detector | skipped any directory with more than N project subdirectories, as "an aggregation hub, not one project" | the hub ran for weeks with no context file, no plan and no health check; the detector even self-tested that it stays quiet there |
| Claim-before-edit coordination guard | `allow()` unless `<repo>/.claude/coord/guard.py` already exists | no claim was ever required, so no claim was ever written, so no registry existed, so nothing asked for one — while two sessions edited the same file two minutes apart |
| Handoff reminder | treated any handoff file with a recent **mtime** as proof a handoff was written | a merge that restored months-old handoffs refreshed their mtimes and silenced the reminder for the whole session |

The third is the same disease in a different organ: the gate trusted a signal that ordinary
file operations can forge.

## The inverse failure: a gate so loud it is trained away

The opposite tuning fails just as reliably. A `REQUIRED` reminder whose trigger matched
project *documentation* rather than the command about to run fired on every single command
in any repository whose README happened to mention two common words — `echo hi` included.
Within one session it had been discounted entirely, and then it was silent in the only sense
that matters: nobody was listening when it was right.

A rule that fires when it does not apply spends the credibility it needs on the day it does.

## What to do instead

1. **Separate "does this apply" from "is this adopted".** The first question is about the
   project's shape, the second about its files. A gate may skip work that does not apply; it
   should still speak when work applies and adoption is missing. A hub is exempt from being
   marked as one long-running project — it is not exempt from carrying a context file.
2. **Make the exemption say something.** Where a gate returns early, ask whether the early
   return is knowledge worth reporting once. Cheap form: report the specific missing
   artifacts and where they probably already exist, rather than a generic checklist.
3. **Never infer state from a signal any routine operation can rewrite.** mtimes, file counts
   and directory listings are all forgeable by a merge, a checkout or a sync. Prefer a value
   that is part of the content: a timestamp inside the filename, a hash, a git object.
4. **Gate the trigger on the action, not on the surroundings.** Whether work *is* security
   work is decided by the command being run, not by words in a README that describes the
   project in general.
5. **Verify the gate on a project that has not adopted it.** A self-test that only exercises
   the adopted path proves the quiet case works, which is the case that was never in doubt.

## Relationship to other principles

- Extends **[11 — Documentation Integrity](11-documentation-integrity.md)** and the
  silent-failure rule: presence in a manifest is not behaviour, and *deliberate* silence is
  the hardest absence to notice.
- Pairs with **[02 — Proof Loop](02-proof-loop.md)**: the proof that a gate works is that it
  fired on a project which had not adopted it, not that it stayed quiet on one that had.
- Pairs with **[18 — Multi-Session Coordination](18-multi-session-coordination.md)**: the
  coordination layer is the most likely to carry this bug, because it is adopted per
  repository while the collisions it prevents happen in the shared directories nobody
  adopted it in.
