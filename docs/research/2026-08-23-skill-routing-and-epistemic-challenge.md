# Skill routing and epistemic challenge: research to adopted controls

**Question.** Ensure that a delegated agent receives the procedural skill that
matches its task, and make critical responses evidence-led rather than
automatically agreeable.

## Observed starting point

`hooks/keyword-skill-router.py` already recognizes high-confidence phrases,
but only advises the parent at `UserPromptSubmit`. Its result did not travel
into a later Claude `Task` prompt. Therefore a subagent could begin a RunPod,
native, or harness task without receiving the procedure the parent had been
shown. This is a propagation gap, not a missing catalog.

## Research findings

| Finding | Evidence | Adopted consequence |
|---|---|---|
| Skills scale through progressive disclosure: metadata routes, then the selected body and focused resources load. | [Anthropic](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills), [Agent Skills specification](https://agentskills.io/specification) | Keep the full catalog out of the child brief; name the selected skill and require its `SKILL.md` before action. |
| Skill selection itself is a high-leverage failure point. The Chinese-language SkillRouter research reports large routing degradation when only names/descriptions are considered in a large overlapping catalog. | [SkillRouter](https://www.alphaxiv.org/zh/abs/2603.22455v3) | Reuse our curated, high-confidence routes and select a minimal set. Do not create a second untested semantic catalog or dump all skills into every agent. |
| Sycophancy is not merely tone: assistants can change correct answers after a social challenge, and preference data can favor agreeing prose over truth. | [Sharma et al.](https://arxiv.org/abs/2310.13548) | A user assertion, repetition, and the author's confidence are not evidence. Require a falsifiable claim and an observation that could change the verdict. |
| Factored independent checks reduce hallucinations better than a draft simply rereading itself. | [Chain-of-Verification](https://aclanthology.org/2024.findings-acl.212/) | The criticality skill requires a distinct check of the decisive claim, preferably without the proposed conclusion. |
| Positive user feedback and ordinary offline metrics can miss over-agreeable behaviour; model launches need dedicated behavioral evaluation and qualitative signals. | [OpenAI postmortem](https://openai.com/index/expanding-on-sycophancy/), [GPT-5 system card](https://deploymentsafety.openai.com/gpt-5/account-level-enforcement) | Add routed criticality guidance and regression fixtures. Do not claim a system-prompt wording change alone solves sycophancy. |
| Codex `SubagentStart` can add context to a child but receives no parent-task prompt and cannot stop the launch. | [Codex Hooks](https://learn.chatgpt.com/docs/hooks.md) | Use it to inject universal minimum-skill and source-required discipline; retain the task-bound contract only where a client exposes the needed task event. |

## Adopted design

1. Before dispatch, `agent-skill-contract.py --task` reuses
   `keyword-skill-router.py` and derives the smallest assignment: all explicitly
   required routes, otherwise one primary route. It also renders an explicit
   no-high-confidence-match result. A Claude `Task` must carry one complete
   contract bound by SHA-256 to the exact child prompt; raw keyword matching at
   the hook boundary is deliberately avoided because quoted/literal text creates
   false positives.
2. The contract requires the child to read each named `SKILL.md` before action,
   to base a decision on a live/retrieved source, and to return `INCONCLUSIVE`
   or `BLOCKED_SKILL_UNAVAILABLE` rather than inventing a basis or pretending a
   missing skill was used. Memory is a lead to re-check, not confirmation.
3. Codex's native subagent API does not emit Claude's `Task` hook event. The
   same renderer is available for coordinator integration, but it is not a
   task-specific automatic Codex control. `subagent-skill-context.py` uses the
   documented Codex `SubagentStart` event to put the smallest-skill and
   source-required decision rule into every child. The event has no task prompt
   and cannot block a launch, so it does not pretend to validate route accuracy.
   `subagent-evidence-receipt.py` uses the documented `SubagentStop` final
   message to require a structured decision basis and evidence anchor, with one
   repair pass. It verifies the receipt's shape and excludes memory as a stated
   basis; it does not establish the truth of a cited source. This boundary is
   explicit rather than falsely claiming a Claude hook governs Codex.
4. `epistemic-challenge` is a routed skill, not an always-on argument persona.
   It requires evidence, counterevidence, a proof boundary, and one falsifier.
   For high-consequence work it connects to the existing fresh evaluator rule.

## Rejected alternatives

- **Always attach all skills.** It defeats progressive disclosure and makes
  route failures harder to see.
- **Always disagree / mandatory devil's advocate.** It creates performative
  contrarianism and has no truth criterion.
- **Trust self-critique alone.** The verifier must have a separate check of
  the key claim; the author cannot certify its own conclusion.
- **Treat this as a prompt-only safety control.** Prompt text guides the model,
  while the dispatch contract and regression tests make the routing boundary
  observable. Behavioral effectiveness still needs scenario evaluation.

## Verification and remaining boundary

`scripts/test_agent_skill_contract.py` covers missing, wrong, correct, and
not-applicable contracts through real hook events. The keyword router fixtures
cover the new criticality trigger. These prove routing and contract behavior,
not that a future model always reasons correctly. A model-behavior rollout must
add paired false-premise and justified-agreement scenarios, measure unsupported
agreement, and retain failures as regression cases.
