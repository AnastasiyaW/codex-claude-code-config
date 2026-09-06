# Research: Claude Workflows beyond official docs (CN/RU/community, 2026-05-30)

> **Historical research, not a current runtime contract.** Community/RU/ZH observations below
> were collected on 2026-05-30 and may be stale or unsupported. Do not copy their numeric
> limits, performance figures, activation paths, or permission behavior into an active workflow.
> Current primary sources checked 2026-09-06: [workflows docs](https://code.claude.com/docs/en/workflows),
> [Anthropic article](https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code),
> [Agent SDK cookbook](https://platform.claude.com/cookbook/claude-agent-sdk-08-dynamic-workflows).
> The docs/cookbook page does not state an update date; the article is dated 2026-06-02.

Источник: наш `/research-cn-ru` прогон (4 агента, 73 hits → 31 unique → 26 novel; zh/en/ru).
Фокус — чего НЕТ в официальной англо-доке. Каждое утверждение со ссылкой + язык.

## 1. Недокументированная активация (НЕ стабильный API)

- Env var `CLAUDE_CODE_WORKFLOWS=1` перед `claude` (Win: `SET ...`), триггер-слово `ultrawork`,
  build-флаг `WORKFLOW_SCRIPTS` (true с v2.1.150). **НЕ подтверждено Anthropic — не для прода.**
  [CN aivi.fyi, rain.tips]
- `ultracode` = «xhigh reasoning effort» **+** standing-permission на спавн workflows (две
  ортогональные вещи в одном флаге). [RU vc.ru]

## 2. Historical community constants (not confirmed current limits)

| Параметр | Значение | При нарушении |
|---|---|---|
| Lifetime agent() calls | **1000** | throws `WorkflowAgentCapError` |
| Concurrency | **min(16, max(2, cores−2))** | избыток в очередь |
| Script size | **512 KB (524288 B)** | отклоняется до парсинга |
| Per-agent stall | **180000 ms**, override `stallMs` | до 5 retry → abandon |
| VM sync timeout | **30000 ms** | — |
| Nesting | **1 уровень** | вложенный workflow() throws |
| agent() cache key | **(schema, model, isolation, agentType)** | смена любого → re-run вызова |

[EN github.com/ray-amjad/claude-code-workflow-creator + api-reference.md]

## 3. On-disk persistence / resume (reverse-eng)

- Скрипт + 6 транскриптов агентов + journal + metadata → `~/.claude/projects/<encoded-cwd>/`.
  Скрипты — **`.mjs` ES-модули**, редактируемы вручную (interop: дёргать Codex/Antigravity из
  шага). Journal-resume официально не задокументирован. [CN csdn, 80aj.com]

## 4. Historical cache / billing hypotheses (not current performance claims)

- **Cache-busting при resume** ← ОБЪЯСНЯЕТ наш resume-прогон на 976k: attachment-блоки (skills
  list, MCP, deferred tools, hooks) должны быть в `messages[0]`; при resume «уплывают» в поздние
  сообщения → fingerprint `cc_version` меняется → system prompt меняется → **кэш инвалидируется**,
  выжигая недельную квоту за день. [CN zhihu/2025177567188001484]
- **Standalone-binary молча отключает prompt caching** → пересчёт статики каждый запрос, 10-20x
  дороже. [RU thecode.media]
- **stable prefix / dynamic suffix**: статика (tool-defs, инструкции) первой в детерминированном
  порядке; volatile (timestamps) — в конец, иначе ломает кэш. [RU vc.ru/2945685]
- **MCP tool discipline**: 200K контекст схлопывается до ~70K при избытке tools. Правило: ≤10
  активных MCP, ≤80 активных tools (конфигурить можно 20-30, включать мало). [RU habr/987094]

## 5. Детерминизм (throw-bans)

- `Math.random()`, `Date.now()`, argless `new Date()`/`Date()`, fs/require/process — **throw на
  исполнении** (журналирование agent() для resume). Обход: timestamps через args, «случайность»
  индексом. [EN alexop.dev]. (RU habr/1041460 ошибочно считает determinism «нерешённым» — на деле
  рантайм форсирует через throw; сигнал, что не все знают про hard-ban.)

## 6. Historical community guidance on script shape / prompts

- **`meta` — чистый object-literal, ПЕРВЫЙ statement**. Поля: name(req), description(req),
  whenToUse(opt), phases:[{title, detail?, model?}]. **`phases[].model` — ЛЕЙБЛ для permission-
  диалога; реальная модель только в `model` опции каждого agent().** [EN SKILL.md raw]
- **5-частный промпт**: role, goal, scope, workflow (как декомпозировать), review output. Pitfall:
  «Starting too broad (`Improve this app`) → расплывчатые субагенты и диффы». Хорошие находки
  называют файлы/функции/команды/тесты. [EN sagnikbhattacharya.com]
- **Historical three-condition heuristic**: this was a community opinion, not an official
  selection rule. Current docs frame the choice around scale, repeated fan-out, and whether the
  orchestration should be saved and rerun; do not require all three conditions. [EN claudefa.st]

## 7. Historical cost anecdotes (not a forecast)

- 62 Opus-субагента выжгли 5-часовой cap за **18 минут**; «довольно мелкий пакет» → 90 агентов
  упёрлись в Max; Java→C# миграция ~**2 млрд токенов**. [EN HN 48311705]
- «5 параллельных субагентов = 5x расход» (N субагентов = N разговоров с моделью). [RU dtf.ru]

## 8. Historical fan-out anecdotes (not measured current guidance)

- **Выигрыш только при истинной независимости юнитов**: 5 агентов на 1 модуль = 5 конфликтующих
  вариантов, не ускорение. [RU habr/1030832]
- **Return Control** против вложенности: nested-оркестрация схлопывается после 3-4 уровней;
  фикс — оркестратор выходит → worker через Task → возобновление по отчётам. [RU habr/976078]
- **Stale-decay**: агенты/skills устаревают каждые 2-3 нед (API-изменения), поддержка ~5ч/нед. [RU habr/1017110]
- **Context-isolation метрики**: оркестратор стабилен на 10-15K токенов vs 50K+ монолит. [RU habr/974448]

## 9. Качество вывода — предупреждение

- **Bun rewrite**: ~99.8% pass rate, НО агенты **тихо подогнали тесты** + bug-tracker наполнился
  новыми багами. **99.8% pass ≠ идентичное поведение** — метрика прогресса, не корректности.
  [RU habr/1040860]. (Совпадает с нашим уроком: verify ≠ correctness.)

## Что это меняет в нашем skill

- Active `SKILL.md` uses only current primary-source limits: 16 concurrent agents, 4,096
  input items per `parallel()`/`pipeline()`, and 1,000 agents total; it does not promote this
  report's reverse-engineered values to a contract.
- These observations remain leads for a separately receipted live investigation, not proof of
  cache behavior, costs, activation, or permission semantics in a current environment.
