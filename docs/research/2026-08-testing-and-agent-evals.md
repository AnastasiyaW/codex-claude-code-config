# Testing And Agent-Evaluation Research

Date: 2026-08-03
Status: adopted for the shared Claude Code + Codex configuration

## Findings

1. The classic test pyramid remains useful as a portfolio rule: many fast,
   low-level checks, fewer boundary checks, and a small number of broad
   end-to-end checks. Its more important rule is to avoid duplicate coverage;
   move a failing high-level case down when a lower-level test can prove the
   same contract.
2. Agent evaluation is not the same as model benchmarking. A useful agent
   evaluation records the task, trajectory/tool calls, environment, outcome,
   recovery behavior, and safety constraints. A final answer alone is too weak.
3. Test generation is useful as a filter only when the generated test is
   grounded in the issue and can be shown red before the fix and green after it.
4. A harness must make the proof loop executable: acceptance criteria, change
   scope, deterministic checks, evidence, and independent verification for the
   cases where self-review is not reliable.
5. Property-based, mutation, performance, security, and long-running agent
   evaluations are valuable, but they are periodic or risk-triggered layers;
   putting all of them on every edit creates latency and encourages bypasses.
6. Test profiles and execution environments must be separate. A VM is only one
   possible compatibility environment: other projects may need a GPU, another
   OS/ABI, a browser matrix, hardware, a performance runner, or no specialized
   environment at all. A harness overload is a measurable routing defect when
   a higher-cost or specialized gate blocks a lower-risk claim.
7. Feedback must include the requested profile, blocking gate, observed cost or
   failure, evidence produced, and the smallest correction. The shared hook
   records this metadata and forces the final report to expose it.

## Sources In English

- Martin Fowler, “The Practical Test Pyramid”:
  https://martinfowler.com/articles/practical-test-pyramid.html
- Google Testing Blog, “Test Sizes”:
  https://testing.googleblog.com/2010/12/test-sizes.html
- Anthropic, “Harness design for long-running application development”:
  https://www.anthropic.com/engineering/harness-design-long-running-apps
- Anthropic, “Demystifying evals for AI agents”:
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- OpenAI, “Inside OpenAI's in-house data agent”:
  https://openai.com/index/inside-our-in-house-data-agent/
- GitHub Docs, “Deployments and environments”:
  https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- SWE-bench paper:
  https://arxiv.org/abs/2310.06770
- SWT-Bench, testing and validating real-world bug fixes with code agents:
  https://arxiv.org/abs/2406.12952
- Hypothesis property-based testing:
  https://hypothesis.readthedocs.io/
- Mutmut mutation testing documentation:
  https://mutmut.readthedocs.io/en/latest/

## Sources In Chinese

- Google Cloud, “智能体评估” (Agent Evaluation), Chinese documentation:
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-agents?hl=zh-CN
- 中国工业互联网研究院, “智能体约束工程（Harness）评测正式启动”:
  https://www.china-aii.com/jgdt/202507015.jhtml
- Thoughtworks China, “用测试金字塔指导数据应用的测试”:
  https://www.thoughtworks.com/zh-cn/insights/blog/agile-engineering-practices/testing-pyramid-guide-data-application-test
- AgentBench paper (authors include Chinese research groups):
  https://arxiv.org/abs/2308.03688

## Adopted Local Policy

The shared system uses five practical layers:

| Layer | Name | Default trigger |
|---|---|---|
| L0 | Scope/acceptance | Every non-trivial code task |
| L1 | Fast deterministic gate | Every code/test change |
| L2 | Focused behavior/regression | Changed behavior or confirmed bug |
| L3 | Boundary/contract | API, DB, filesystem, queue, serialization, auth, concurrency |
| L4 | Smoke/candidate/eval | User journey, candidate claim, high-risk or long-running agent |

The active Stop hook enforces the red/green fast gate only for Git-visible code
or test changes. `.claude/test-policy.json` can provide `fast`, `integration`,
and `release` commands. The latter is not run on every edit. `test-muting-guard`
remains a hard guard against hiding failures; `bug-reproducer` and `proof-verify`
remain specialized workflows rather than global gates.

## Candidate-State Test Sequence (Canonical)

This is a universal testing rule, not a VM or release-only rule. Do not turn
every edit into a full-matrix rehearsal. The working sequence is:

1. **Focused local slice** — run the smallest deterministic checks that exercise
   the changed behavior or reproduced bug. Repeat these while iterating.
2. **Independent review** — for a boundary or high-risk change, use a fresh
   context/evaluator and record its verdict against the exact changed surface.
3. **Full matrix once at the candidate boundary** — run the project's complete
   matrix once when the candidate is ready for its commit/merge/release
   boundary. This is candidate evidence, not a per-commit edit tax.
4. **Conditional specialized-environment proof** — only when the acceptance
   criteria or risk actually depends on a VM, GPU, OS/ABI, browser, hardware,
   performance, stress, or another specialized environment, run that proof
   against the exact candidate identity. If no such environment is relevant,
   record `N/A: no specialized compatibility requirement` instead of inventing
   a VM step. If the candidate changes, all candidate-bound evidence is invalid
   and must be regenerated, including the full matrix and specialized proof.

The compact form is:

```text
focused slice -> risk-based review -> one full matrix -> conditional specialized proof
```

The Stop hooks enforce the first two boundaries without pretending they are the
last two. `test-gate-stop-hook.py` runs `fast` for source changes and adds
`integration` only for high-risk boundaries; it deliberately does not auto-run
the full/candidate matrix. Its high-risk path requires independent review
evidence keyed to the changed paths. `harness-load-advisor.py` catches the
opposite mistake: a costly or specialized gate accidentally blocking a lower-
risk smoke, and requires a profile split instead of a bypass. A project must
expose its full matrix and any relevant specialized-environment commands as
explicit candidate workflow steps.

## Profile Contract And Overload Feedback

The adopted profile contract is:

| Profile | Blocking evidence |
|---|---|
| `staging-smoke` | fast build, focused regression, one stable smoke or contract path |
| `security-proof` | hostile tests, trust-boundary proof, fresh-context evaluator |
| `compatibility-proof` | only the relevant VM/OS/ABI/GPU/browser/hardware proof |
| `candidate-matrix` | complete project matrix on one immutable candidate |
| `release-attestation` | exact artifact, signing, Authenticode/tool identity, installer/package proof |
| `nightly-stress` | race, stress, OS/AV matrix, long-running evaluation |

The `harness-load-advisor.py` Stop hook is deliberately narrow. It fires only
when the final assistant message reports overload, false positives, or a
costly/specialized gate blocking a lower-risk smoke. It writes metadata to
`~/.claude/harness-feedback/events.jsonl` and blocks the close long enough to
require a user-visible diagnosis. It never disables the named gate.

This is consistent with the research: Anthropic separates generator and
evaluator roles and relies on structured artifacts for long-running work;
Google's Chinese agent-evaluation documentation evaluates both final answers
and tool-call trajectories; classic testing guidance keeps broad, expensive
checks few and avoids duplicate coverage. The local implementation makes the
same boundary mechanical.

## Rejected As Overkill

- Installing a second generic “test everything” plugin: it would duplicate the
  existing Stop gate, test-muting guard, review, and proof-verify workflows.
- Making an LLM judge the only release oracle: use deterministic tests and
  artifact checks first, then semantic/trajectory scoring for agent behavior.
- Running full E2E, mutation, load, compatibility, and security suites after every edit: use
  risk-based triggers and CI/nightly schedules.
