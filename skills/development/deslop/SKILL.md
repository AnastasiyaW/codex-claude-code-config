---
name: deslop
description: Remove AI-generated code noise from the current diff while preserving behavior. Use for deslop, AI slop cleanup, unnecessary comments, defensive checks, any casts, or needless nesting after an agent-generated change. Do not use as permission for a broad rewrite or when a real bug has not been isolated.
---

# Deslop

Review only the branch diff against its intended base and remove noise that
does not belong in the local code style. Keep the behavior and public contract
unchanged unless a clear, separately verified bug is fixed.

## Review Targets

- comments that narrate obvious code or contradict local conventions;
- defensive checks or catch blocks abnormal for a trusted path;
- `any`, unsafe casts, or optionality used only to silence a type checker;
- deep nesting that can be made clearer with early returns or a named helper;
- one-off wrappers, flags, and branches inconsistent with the surrounding
  module;
- C++ ownership or error-handling scaffolding that is redundant with the
  established RAII/contract boundary.

## Workflow

1. Inspect the base, diff, local style, tests, and ownership boundaries.
2. Classify each candidate as noise, a clear bug, or an intentional contract.
3. Remove only confirmed noise in a focused edit.
4. Run the narrow relevant checks and inspect the final diff.
5. If the structure needs a real redesign, stop deslop and use
   `refactoring-safely`, `architecture-quality`, or
   `thermo-nuclear-code-quality-review`.

Do not delete comments that explain a non-obvious invariant, security boundary,
ABI constraint, workaround with an owner, or externally required behavior.

## Gotchas

- Shorter code is not automatically clearer; preserve names and boundaries that
  carry domain meaning.
- A broad formatter run can hide behavior changes and is not deslop proof.
- Removing a defensive check without proving the trusted-path invariant can turn
  cleanup into a regression.
- In C++, exception and ownership code may look repetitive while protecting an
  ABI or lifetime boundary; inspect callers before removing it.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Cleanup changes a test result | Candidate was behavior, not noise | Revert that candidate and isolate the real contract |
| Diff is too broad | Tool ran over the whole tree | Restrict review to the branch diff and restore unrelated files |
| Comment seems redundant but explains a constraint | Context is outside the file | Read the owning docs/tests before changing it |
| Code remains structurally tangled | Deslop is the wrong scope | Escalate to a planned refactor with characterization tests |

## Source

Adapted from Cursor Team Kit's MIT-licensed `deslop` workflow:
https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/deslop
