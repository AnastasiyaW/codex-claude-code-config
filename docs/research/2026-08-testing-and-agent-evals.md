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

## Sources In English

- Martin Fowler, “The Practical Test Pyramid”:
  https://martinfowler.com/articles/practical-test-pyramid.html
- Google Testing Blog, “Test Sizes”:
  https://testing.googleblog.com/2010/12/test-sizes.html
- Anthropic, “Harness design for long-running application development”:
  https://www.anthropic.com/engineering/harness-design-long-running-apps
- Anthropic, “Demystifying evals for AI agents”:
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
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
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation?hl=zh-cn
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
| L4 | Smoke/release/eval | User journey, release claim, high-risk or long-running agent |

The active Stop hook enforces the red/green fast gate only for Git-visible code
or test changes. `.claude/test-policy.json` can provide `fast`, `integration`,
and `release` commands. The latter is not run on every edit. `test-muting-guard`
remains a hard guard against hiding failures; `bug-reproducer` and `proof-verify`
remain specialized workflows rather than global gates.

## Rejected As Overkill

- Installing a second generic “test everything” plugin: it would duplicate the
  existing Stop gate, test-muting guard, review, and proof-verify workflows.
- Making an LLM judge the only release oracle: use deterministic tests and
  artifact checks first, then semantic/trajectory scoring for agent behavior.
- Running full E2E, mutation, load, and security suites after every edit: use
  risk-based triggers and CI/nightly schedules.
