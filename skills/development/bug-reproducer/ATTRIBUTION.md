# Upstream attribution

This skill vendors [`Kappaemme-git/codex-bug-reproducer`](https://github.com/Kappaemme-git/codex-bug-reproducer)
at an immutable audited revision.

- Upstream commit: `52a7a22d463e36d491a4ba4eb31b58a5bd813cc8`
- Retrieved/audited: 2026-09-04
- Upstream license: [LICENSE-upstream](LICENSE-upstream)

The files under `agents/`, `references/`, and `scripts/capture_command.py` are
byte-equivalent to that revision after normalizing CRLF to LF.

Local adaptations are:

- `SKILL.md`: Windows evidence notes, task-authority gates, proportionate-check
  scope, report-location guidance, and deletion/install authority boundaries.
- `scripts/compare_evidence.py`: receipt-backed relevant-check classification
  plus explicit targeted-only scope recording.
- `scripts/generate_report.py`: local relevant-check scope fields.
- `scripts/test_compare_evidence.py`: local entrypoint regression controls;
  this file has no upstream counterpart.
