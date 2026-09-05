# Research-built skill lifecycle: from routed gap to maintained capability

**Question.** When no installed or reviewed third-party skill covers a routed
capability, how do we avoid replacing the gap with a thin local `SKILL.md` while
still avoiding size-driven over-engineering?

## Local evidence

The v2 skill-gap contract accepted `CREATE_LOCAL` after the same six generic
checks used for an existing candidate. It did not require a research artifact,
a baseline comparison, held-out behavior, independent review, live discovery,
or an owner/update contract. Therefore a structurally valid one-file skill could
mechanically close the gap without proving that it improves the original task or
can be kept current.

## Primary-source findings

| Source | Observed recommendation | Adopted consequence |
|---|---|---|
| [Agent Skills: creator best practices](https://agentskills.io/skill-creation/best-practices) (accessed 2026-09-05, primary specification project) | Start from hands-on work, corrections, project artifacts and real failures; refine against complete execution traces. Large exhaustive entry points can reduce performance. | Require real local evidence plus current primary research, accepted/rejected consequences, and progressive disclosure. Do not score quality by file size. |
| [Agent Skills: evaluating output quality](https://agentskills.io/skill-creation/evaluating-skills) (accessed 2026-09-05, primary specification project) | Run realistic cases in fresh contexts and compare with no skill or the previous version; grade observable assertions and preserve evidence. | Require baseline/candidate results, held-out cases, objective assertions, and an independent fresh-context review record. |
| [Agent Skills: optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions) (accessed 2026-09-05, primary specification project) | Test both positive triggers and close negative examples; keep a fixed train/validation split to avoid overfitting. | Require trigger positives, near-miss negatives and held-out routing cases before the new skill is accepted. |
| [Agent Skills specification](https://agentskills.io/specification) (accessed 2026-09-05, primary specification) | `SKILL.md` carries bounded activation metadata and core instructions; detailed references and reusable scripts load progressively. | Validate the skill entry point and use focused references/scripts only when the observed workflow needs them. |
| [OpenAI: equipping the Responses API with a computer environment](https://openai.com/index/equip-responses-api-computer-environment/) (2026-03-11; accessed 2026-09-05, official primary product source) | Its reference implementation retrieves skill metadata, fetches a selected versioned bundle, and runs a deterministic setup sequence. | Keep the skill artifact versioned and make runtime discovery/loading observable. |
| [OpenAI Skills API reference](https://developers.openai.com/api/reference/go/resources/skills) (accessed 2026-09-05, official API reference) | Skill versions are immutable resources and the skill's default version is an explicit pointer that can be updated. | Record version ownership, freshness/update triggers, live discovery proof, and rollback instead of relying on an unversioned folder. |
| [OpenAI Codex hooks](https://learn.chatgpt.com/pt-BR/docs/hooks) (accessed 2026-09-05, official Codex documentation) | `spawn_agent` is exposed to `PreToolUse`/`PostToolUse` through matcher alias `Agent`; pre-hooks can inspect/rewrite function inputs and post-hooks receive tool results. `SubagentStop` includes `agent_id` and the last message. | Insert the task contract before launch, bind the post-launch `agent_id` to that route, and reject an unbound final disposition. |

## Accepted design

1. Replace the ambiguous `CREATE_LOCAL` terminal label with
   `BUILD_RESEARCHED`; contract v4 rejects the old label and records the actual
   receiving client plus usable and missing skill sets separately.
2. Keep the existing skill-gap receipt/controller. For `BUILD_RESEARCHED` only,
   require readable local skill, research, eval, maintenance and independent
   review records.
3. Mechanically inspect the records for the fields that make the proof
   reproducible: per-source authority and dates, content-addressed local evidence,
   accepted/rejected recommendations mapped to exact skill lines, numerical
   baseline/candidate and held-out results recomputed from case observations,
   distinct builder/reviewer identities, owner/version/freshness/update/rollback,
   and intended-harness discovery.
4. Bind Codex delegation at `PreToolUse(Agent)` and map its `PostToolUse` result
   to `agent_id`; a routed child cannot close as `NO_MATCH`.
5. Resume the original user task only after this evidence passes, and require a
   digest-bound terminal task receipt. The created skill is a means to complete
   that task, not a replacement deliverable.

## Rejected designs

- **Make every local skill large.** Official guidance warns that exhaustive
  instructions compete with the task context. Completeness is measured by
  demonstrated workflow coverage, not words or files.
- **Accept structural validation as quality proof.** Frontmatter validity cannot
  show correct triggering, useful execution, or improvement over the baseline.
- **Automatically copy a third-party skill.** Search candidates first, but
  provenance, permissions, conflicts and behavior still require the existing
  supply-chain review.
- **Create a second lifecycle controller.** The current receipt already owns the
  transition; a decision-specific evidence addendum closes the causal gap with
  less drift.

## Proof boundary

The hook can prove that the named local evidence exists, its trace hashes match,
case-level observations mechanically yield the recorded metrics, the candidate
beats baseline, reviewer identity differs from author, original-task evidence is
disjoint from skill-build evidence, and a Codex final disposition matches the
client-specific route captured at launch. It cannot
prove that a cited source is truthful or that two different identity strings
represent truly independent people/contexts. Focused regression fixtures cover
the mechanical boundary; real skill creation still requires source inspection
and a genuinely fresh-context reviewer.
