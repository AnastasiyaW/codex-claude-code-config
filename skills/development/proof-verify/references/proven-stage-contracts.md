# Proven Stage Contracts

For the rationale, scope boundary, and a walkthrough of the model, see
[A Passing Test Is Not a Release](../../../../docs/a-passing-test-is-not-a-release.md).

Use this pattern when proof from one stage becomes an input to another: a module
must be accepted before packaging, an artifact before integration, or a local
candidate before a VM, signer, account, or production-like environment can use it.
It prevents two opposite mistakes:

- rerunning or reopening already-proven code because a later external prerequisite
  is absent;
- calling an old test result proof after its contract, source, or inputs changed.

## The Minimal Model

| Status | Meaning | May a later stage consume it? |
|---|---|---|
| `VERIFIED` | Scoped behavior passed at an exact identity. | No. It is a result, not yet a hand-off. |
| `SEALED` | Verified stage with immutable identity, dependencies, outputs, and fresh verdict. | Yes, by exact output digest only. |
| `BLOCKED` | A named prerequisite outside this stage is missing. | No. It says what is missing without erasing upstream proof. |
| `SUPERSEDED` | A changed contract, source, or input replaced this stage. | No. Follow `superseded_by`. |

`SEALED` is a promotion boundary, not a claim that the whole release is ready.
A release can have sealed source and artifact stages while the final environment
is honestly `BLOCKED` on a signer account or a clean VM.

## Ledger

Put the ledger in the project's existing durable proof location:
`.proof/stage-ledger.json` or its documented equivalent. Keep sensitive logs and
credentials outside Git; store safe paths and digests only.

```json
{
  "schema_version": 1,
  "stages": [
    {
      "id": "phase-a-authority",
      "status": "SEALED",
      "scope": ["src/authority", "tests/authority"],
      "contract_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
      "source": {
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "tree": "89abcdef0123456789abcdef0123456789abcdef"
      },
      "inputs": [
        {"name": "acceptance-contract", "sha256": "2222222222222222222222222222222222222222222222222222222222222222"}
      ],
      "outputs": [
        {"name": "authority-artifact", "sha256": "3333333333333333333333333333333333333333333333333333333333333333"}
      ],
      "fresh_verdict": {
        "status": "PASS",
        "path": ".proof/verdicts/phase-a.md",
        "sha256": "4444444444444444444444444444444444444444444444444444444444444444"
      },
      "invalidates_on": ["contract_sha256", "source.commit", "inputs[].sha256"]
    },
    {
      "id": "phase-b-cms",
      "status": "BLOCKED",
      "scope": ["release/cms"],
      "blocked_on": [
        {"kind": "external-service", "name": "production CMS signer account"}
      ],
      "requires": [
        {"stage": "phase-a-authority", "output_sha256": "3333333333333333333333333333333333333333333333333333333333333333"}
      ]
    }
  ]
}
```

The values above are illustrative placeholders. Real values must be actual
cryptographic digests and Git object IDs.

Validate structure and downstream consumption with:

```text
python skills/development/proof-verify/scripts/validate_stage_ledger.py \
  .proof/stage-ledger.json
```

The validator checks contract shape and parent-output matching. It does not claim
that an external signer, VM, or deployment is healthy; that remains the explicit
proof of the relevant stage.

## Promotion Rules

1. Freeze the stage's acceptance contract before build. Record its digest.
2. Run the smallest focused proof that can disprove the stage.
3. Get a fresh verifier for high-risk or release-directed work.
4. Seal only after the verifier passes. A command exit code without a verdict is
   not a receipt.
5. A child stage references the parent's output digest exactly. Do not rebuild the
   parent merely to move it to another environment.
6. If the child needs unavailable infrastructure, leave it `BLOCKED` with the
   owner/requirement. The parent remains sealed.
7. If an invalidation key changes, create a new stage and mark the old one
   `SUPERSEDED`. Never edit historical evidence to describe a later candidate.

## Scope Guard

Do not create a ledger for docs-only work, a small local function, or a one-step
experiment. GitHub advises against generating attestations for every frequent test
build; the same cost discipline applies here. Use the ledger for real hand-offs
between independently verifiable stages.

## Research Basis

- [SLSA Provenance](https://slsa.dev/spec/v1.2/provenance) defines provenance as
  verifiable information connecting an artifact to its build and source inputs.
- [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
  show build provenance should be verified, not merely generated; GitHub also
  advises signing releasable artifacts rather than every frequent test build.
- [Google Cloud Deploy promotion](https://cloud.google.com/sdk/gcloud/reference/deploy/releases/promote)
  promotes an existing release to the next target, rather than treating every
  environment as a new unrelated build.
- [NIST SSDF](https://csrc.nist.gov/projects/ssdf) includes collecting and sharing
  provenance information for release components.

These sources support immutable promotion and traceability. They do not prove a
stage is secure or usable by themselves; the contract's focused test and the
fresh verdict remain necessary.
