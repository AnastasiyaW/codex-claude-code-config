---
name: harness-feedback
description: Use when an agent says a test, VM, proof, evaluator, or release gate is overloaded, too strict, blocking staging, or causing false positives; split checks by profile, measure the burden, preserve high-risk evidence, and verify the smallest corrected workflow. Do not use for ordinary test selection, a single test failure, or a full security audit without a harness-scope question.
---

# Harness Feedback

Treat "the harness is too strict" as an engineering finding, not as permission
to disable a safety check. Find the boundary that owns the mismatch and move
the check to the narrowest profile that actually needs its evidence.

## Profiles

Use these profiles unless the project has a more specific, documented contract:

| Profile | Purpose | Typical blocking checks |
|---|---|---|
| `staging-smoke` | Fast proof that the changed build starts and the critical path works | build, focused regression, one stable smoke/contract check |
| `security-proof` | Prove an adversarial or trust-boundary claim | hostile tests, source/collector proof, fresh-context evaluator |
| `release-attestation` | Prove the exact releasable artifact and its identity | signing, Authenticode/tool identity, installer/package checks |
| `nightly-stress` | Find intermittent and capacity failures | race, stress, AV/OS matrix, long-running evals |

`staging-smoke` must not require signing, production credentials, a release
certificate, or a long VM stress run. `security-proof` may run on an unsigned
staging build when its claim is source or runtime behavior. A release check may
remain blocking for release promotion without becoming a per-edit gate.

## Feedback Loop

For every overload signal, record:

1. requested profile and change boundary;
2. gate that blocked or dominated the run;
3. command, elapsed time, failure count, and evidence actually produced;
4. whether the gate was relevant, duplicated, flaky, or misplaced;
5. the smallest profile split or deletion of duplicate coverage;
6. a before/after run of the affected profile and a fresh review of the rule.

Use the deterministic `harness-load-advisor.py` signal as an intake event. It
stores metadata outside the repository and forces the final report to name the
mismatch. Durable policy changes belong in Git; raw session traces do not.

## Required Report

Do not write "overkill" and move on. Report:

```text
Harness feedback: OVERLOAD | CLEAR
Requested profile: staging-smoke | security-proof | release-attestation | nightly-stress
Mis-scoped gate: <name>
Evidence: <command, result, elapsed time, or explicit missing proof>
Correction: <profile split or rule change>
Verification: <before/after commands and result>
Residual risk: <what remains intentionally gated and where>
```

## Gotchas

- A fresh evaluator is an independence control, not a release-signing check.
- A VM can be a reusable execution environment without forcing release identity
  checks into every VM smoke.
- A green fast gate does not prove release readiness; a red release-only gate
  does not invalidate a staging smoke unless the staging claim depends on it.
- Do not replace a misplaced gate with retries, sleeps, or a bypass marker.
- Do not infer overload from one slow run; distinguish environment failure from
  a profile contract error.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Staging smoke asks for signing | Release gate leaked into staging profile | split `release-attestation` and run the smoke on the unsigned staging artifact |
| Security proof blocks on a production VM | Runtime environment and release identity are coupled | keep the VM, remove release-only assertions from the security profile |
| Same gate fails repeatedly | Wrong scope, flaky boundary, or missing fixture | classify the failure and add a focused reproducer; never silently retry |
| Agent says "tests passed" with no profile | Evidence contract is incomplete | require the report fields above and the exact command/result |
| Fix removes a safety check | Causal ownership was not traced | restore the check, document the narrower boundary, and re-verify it there |
