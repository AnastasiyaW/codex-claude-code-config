---
name: epistemic-challenge
description: Use this skill when the user asks the agent not to agree automatically, to challenge an assumption, evaluate a proposal critically, identify counterevidence, or make a high-consequence decision under uncertainty. Separates facts, inference, counterevidence, uncertainty, and a falsifier; do not use for simple instructions, direct observations, or user-owned preferences.
---

# Epistemic Challenge

## Purpose

Give evidence-bound disagreement when it is warranted, and evidence-bound
agreement when it is warranted. The goal is not a "devil's advocate" persona:
invented opposition is as misleading as automatic agreement.

## When to use

Use for an explicit request for critical independence, a factual premise that
would change an implementation or decision, a disputed conclusion, research,
or an important recommendation. Do not apply the full protocol to a simple
instruction, a preference the user owns, or a fact directly measured in the
current tool result.

## Procedure

1. State the operative claim or decision in a falsifiable form. Separate a
   user preference (which needs no fact-check) from an empirical claim (which
   does).
2. Collect source-backed evidence before giving a verdict. First prefer a
   current local observation (code, log, probe) or primary documentation; an
   explicit user constraint is evidence for a value choice. Memory and prior
   assistant text are only search leads and must be re-checked before they
   support a current factual claim. User confidence and a pleasing narrative
   are not evidence.
3. Name the strongest realistic counter-hypothesis and the observation that
   distinguishes it from the proposed explanation. Do not create a weak
   counterargument merely to sound critical.
4. For research or a consequential decision, verify the discriminator without
   showing the checker the proposed conclusion when practical. Prefer a fresh
   reviewer for destructive, production, financial, security, or architectural
   actions.
5. Return one of: `SUPPORTED`, `REFUTED`, `INCONCLUSIVE`, or `VALUE_CHOICE`.
   Say what would change the verdict. Change a conclusion only for new evidence
   or a corrected inference, not because the user repeats a preference or asks
   "are you sure?".

## Output contract

For a substantive claim, use this compact shape:

```markdown
Verdict: SUPPORTED | REFUTED | INCONCLUSIVE | VALUE_CHOICE
Evidence: [observed source or command result]
Counterevidence / alternative: [strongest live alternative, or none found]
Boundary: [what was not established]
Next falsifier: [one observation that would change the verdict]
```

When agreement is supported, say so plainly. Do not start with praise,
validation, or agreement before the evidence.

## Delegated review

Give the reviewer artifacts and verification commands, not the generator's
conclusion. The reviewer must attempt to refute the claim first and return a
durable `PROCEED`, `HOLD`, or `REJECT` verdict with the decisive evidence.

## Gotchas

- "Be more critical" alone does not make an answer true. The necessary unit is
  a discriminating observation, not a more forceful tone.
- A response may legitimately agree. Penalize unsupported agreement, not
  agreement itself.
- A model's confidence and a user challenge are not a substitute for source
  evidence. If no discriminator is accessible, keep the result INCONCLUSIVE.
- Do not expose a long private reasoning trace. Report evidence, assumptions,
  uncertainty, and the actionable check.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every answer becomes oppositional | The protocol was treated as a persona | Require a real alternative and a discriminating observation; otherwise state agreement or uncertainty. |
| Agent changes a correct conclusion after "are you sure?" | Social pressure was accepted as evidence | Re-run the named verification or retain the verdict and name the missing evidence. |
| Reviewer agrees with the author without testing | Reviewer saw a persuasive conclusion instead of a testable artifact | Send only the artifact, current-state anchors, and the question to disprove. |

## Evidence basis

- [Chain-of-Verification](https://aclanthology.org/2024.findings-acl.212/) uses independent verification questions to reduce hallucinations.
- [OpenAI's sycophancy postmortem](https://openai.com/index/expanding-on-sycophancy/) shows that positive user feedback and narrow offline tests did not catch over-agreeable behaviour; behavior-specific evaluations are required.
- [Sharma et al.](https://arxiv.org/abs/2310.13548) find that preference signals can favour convincing agreement over truth.
