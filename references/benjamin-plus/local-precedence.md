LOCAL PRECEDENCE (this machine's canon, appended to benjamin-plus)

The five habits above govern **how you look things up and wait** — recon in one
pass, keyhole inspection, one dependency probe, the task's own check, and not
re-polling a running command. In that lane they hold.

Where their wording touches **what gets built, finished, or recorded**, our canon
wins and they yield:

- **Every connected branch still gets done** (`finish-the-task` P2). "When the
  check passes, stop" means stop polishing that branch — not stop before the
  remaining ones.
- **Quality outranks token savings** (`finish-the-task` P3,
  `quality-over-tokens-independent-verify`). A cheaper session is never a reason
  to leave work undone; complex or irreversible work still gets an independent
  fresh-context verifier.
- **Non-trivial logic still leaves one runnable check** (`quality-code`). "Never
  build a verification harness the task didn't ask for" bans speculative test
  scaffolding — it does not license shipping a branch, parser, or money path
  with nothing that fails when it breaks.
- **"Close with at most two lines" applies to the chat reply only.** Handoffs,
  `PROBLEMS.md` entries, journal records, transfer contracts and evidence stay
  full length — they are durable artifacts, not conversation.
- **A green check is a claim about the shapes someone imagined.** It does not
  close a defect class, and the author of a finding does not certify their own
  fix (`green-suite-proves-imagined-shapes`).

Reading a file whole to edit it, or a dataset whole to transform it, was never
what the keyhole rule limits — it limits inspection.
