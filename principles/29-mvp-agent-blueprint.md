# 29 - MVP Agent Blueprint: structured flow для проектирования новых агентов

**Source:** Denis Sergeevitch -- "agents-best-practices" skill (MIT, https://github.com/DenisSergeevitch/agents-best-practices), `references/mvp-agent-blueprint.md`. Адаптировано к нашему стеку.

## Overview

Когда нужно спроектировать **новый** агент для конкретного домена (поддержка, финансы, операции, sales, research, любой workflow automation), большинство практиков начинают с "напишу system prompt и tools". Это **типичная ошибка**: получается работающий-но-хрупкий агент без явных границ автономии, без budget'ов, без approval points, без observability.

Решение: **MVP Agent Blueprint** - structured 15-section output template который пробегается за один проход и даёт ready-to-implement спецификацию первой версии агента.

Принципы 01 (Harness Design) и 02 (Proof Loop) описывают **как агент работает**. Этот принцип описывает **с чего начать когда агента ещё нет**.

---

## Когда применять

- **User говорит**: «build me an agent that does X», «design an agent harness for Y», «create MVP agent for Z domain», «как мне начать делать агента для...»
- **Контекст задачи**: domain не покрыт существующими агентами, или существующий агент решает другую задачу
- **Новый Agent SDK app, custom Python orchestrator, новый Cloudflare Worker с tool calls, новый MCP server**

**Когда НЕ применять**:

- Improvement существующего harness -> use [principle 01 - Harness Design](01-harness-design.md) + harness-audit skill
- Обычная Claude Code session -> harness уже за нас
- Single-turn Q&A или drafting (Level 0 autonomy) - не нужна полная блюпринт-структура

---

## 5-step Domain Intake

Перед output - явно зафиксировать (можно с допущениями если user не указал):

```text
1. Domain         - что за работа
2. Primary user   - кто ставит задачи / читает выход
3. Job-to-be-done - какой одной полезной операции занимается агент
4. Inputs         - откуда берёт данные
5. Outputs        - что считается completed work
```

Если что-то underspecified - **зафиксировать assumption и продолжать**, не блокировать MVP на excessive clarification.

---

## Autonomy Levels (выбрать lowest которое создаёт value)

```text
Level 0: Answer-only          - читает context, отвечает
Level 1: Draft-only           - drafts recommendations, humans commit
Level 2: Approval-gated       - предлагает действия, ждёт approval
Level 3: Policy-bounded auto  - low-risk auto, остальное approval
Level 4: Long-running goal    - measurable objective + budgets + checkpoints
```

Default для новых MVP: **Level 1 или Level 2**. Level 4 - только после того как Level 2 показал measured reliability.

---

## 15-Section MVP Blueprint Template

Output структурирован так:

```markdown
# MVP Agent Harness Blueprint: [domain/use case]

## 1. Objective
[Одна-две фразы. Что и для кого.]

## 2. MVP scope and assumptions
[Smallest useful version + explicit assumptions + non-goals]

## 3. Autonomy and risk level
[Из 5 уровней выше + список risk classes]

## 4. Core agentic loop
[Provider-neutral: model -> tool proposal -> validation -> permission -> execute/deny -> observation -> repeat]

## 5. Context and instruction architecture
[System/developer/user instructions + scoped memory + trust labels (см. rules/context-trust-labels.md)]

## 6. Tool registry
[Минимальный typed registry. Risk class на каждый tool (см. skills/agent-harness-design/references/agent-tool-design.md). Draft/commit для irreversible.]

## 7. Planning behavior
[Когда planning mode активен; что заблокировано; plan artifact format]

## 8. Goal-like loop behavior
[Если применимо. Done condition + budget + checkpoints + stop rules]

## 9. Context, memory, and auto-compaction
[Durable state outside prompt. Compaction triggers. Handoff format.]

## 10. Skills and connectors
[Какие skills нужны. MCP/external connector permissions. Progressive disclosure.]

## 11. Prompt caching and cost-aware context
[Stable prefix design. Cache telemetry. Result-size limits.]

## 12. Safety and approval policy
[Prompt injection handling. Secret isolation. Sandboxing. Human review points.]

## 13. Observability and evals
[Trace fields. Eval cases (включая prompt injection, approval bypass, budget overflow).]

## 14. Minimal implementation path
[Build order: loop -> tools -> permissions -> structured results -> budgets -> tracing -> planning -> ...]

## 15. First release checklist
[Concrete pass/fail checks before limited rollout. См. rules/long-run-harness.md "First Release Checklist".]
```

---

## Build Order (рекомендованная sequence)

```text
1.  manual model-tool-observation loop
2.  strict tool schemas + local validation
3.  runtime permission checks (см. skills/agent-harness-design/references/agent-tool-design.md)
4.  structured tool results + error observations
5.  step/cost/time budgets (см. skills/agent-harness-design/references/agent-budgets.md)
6.  tracing
7.  prompt-cache-aware context ordering + cache telemetry
8.  planning mode для high-risk tasks
9.  context compaction
10. skills для reusable workflows
11. MCP/external connectors с scoped permissions
12. goal-like loops только после passing evals на base loop
13. subagents только когда decomposition improves measured results
14. recurring knowledge-base + entropy cleanup
```

Главный принцип: **simplest solution first, complexity only when measured failure justifies it**. Subagents/connectors/goals - **upgrades**, не starting features.

---

## Связь с другими принципами и правилами

| Этот принцип | Связанные |
|---|---|
| Section 5 (Context) | [context-trust-labels.md](../skills/agent-harness-design/references/context-trust-labels.md) (trust levels), [principle 07](07-codified-context.md) (Codified Context) |
| Section 6 (Tools) | [agent-tool-design.md](../skills/agent-harness-design/references/agent-tool-design.md) (risk taxonomy + permissions), [principle 10](10-agent-security.md) (Agent Security) |
| Section 8 (Goal loop) | [agent-budgets.md](../skills/agent-harness-design/references/agent-budgets.md) (10 budgets), [principle 03](03-autoresearch.md) (Autoresearch) |
| Section 9 (Memory/Compaction) | [principle 04](04-deterministic-orchestration.md) (Deterministic Orchestration), [principle 18](18-multi-session-coordination.md) (Multi-Session Coordination) |
| Section 13 (Evals) | [principle 02](02-proof-loop.md) (Proof Loop), [principle 21](21-knowledge-base-enforcement.md) (Knowledge Base Enforcement) |
| Section 15 (Release checklist) | [rules/long-run-harness.md](../rules/long-run-harness.md) (First Release Checklist) |

---

## Anti-patterns при построении MVP

```text
- one giant prompt вместо typed sections
- one giant tool типа execute_anything()
- unbounded autonomous loop (см. skills/agent-harness-design/references/agent-budgets.md)
- autonomous external sends в первом релизе
- no approval state
- no durable plans/goals
- no compaction strategy
- no prompt-cache telemetry
- все connectors loaded up front
- high-risk tools exposed без policy
- subagents до того как single-agent MVP measured
```

---

## Когда переходить к более сложной архитектуре

После MVP в production:

1. **Measure failure modes** через evals (см. principle 02)
2. **Identify bottleneck** - context, tool selection, planning, validation, permissions, или skill discovery?
3. **Add complexity точечно** для конкретного bottleneck'а (subagent для тяжёлой evaluation, MCP для external system, goal loop для long-running objective)
4. **Re-measure** - стало ли лучше реально, или просто стало больше moving parts?

Этот flow - generalization того что Anthropic описывает в "Building effective agents": **start simple, compose only when proven necessary**.

---

## Composition с другими принципами

- **MVP Builder + Harness Design (01)**: используй MVP Builder чтобы спроектировать первую версию, затем Harness Design (Generator-Evaluator) для следующей итерации когда есть measured quality plateau
- **MVP Builder + Codified Context (07)**: blueprint включает knowledge base layout - section 9 описывает где живут durable artifacts
- **MVP Builder + Agent Security (10)**: section 12 (Safety) обязательно включает defence-in-depth слои из principle 10
- **MVP Builder + Knowledge Base Enforcement (21)**: section 15 (Release checklist) включает "validation signals declared" - это входные данные для KB enforcement workflow

---

## Источник и atribution

Полный skill (MIT licensed, 14 reference files, ~150KB markdown) - в оригинальном репо https://github.com/DenisSergeevitch/agents-best-practices.

Этот principle - **summary** ключевых паттернов плюс mapping к нашему стеку. Для full depth (provider API patterns, complete tool schemas, prompt templates) - читать оригинал.

Локальная установка skill: можно склонировать в `~/.claude/skills/agents-best-practices/` чтобы skill triggered автоматически на «build me an agent» / «design agent harness» phrases.

```bash
git clone --depth 1 https://github.com/DenisSergeevitch/agents-best-practices.git \
  ~/.claude/skills/agents-best-practices
```

После клонирования skill регистрируется в Claude Code automatically (с условием что path matches skills dir).

---

## Когда rule этого принципа неприменим

- Skill `agents-best-practices` уже триггернулся - он покроет всё нужное, не дублировать
- Domain где вы expert и MVP уже в голове - blueprint не добавляет, но **release checklist (section 15) всё равно полезен** перед launch
- Очень узкая утилита (один tool, один input, один output) - blueprint over-structures; достаточно tool spec + permission rule
