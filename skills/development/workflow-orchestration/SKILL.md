---
name: workflow-orchestration
description: "Написание и запуск Claude Code dynamic workflows (JS-оркестратор субагентов). Use when пишешь или запускаешь workflow, видишь keyword workflow в запросе, нужен fan-out на десятки-сотни агентов, codebase-wide аудит/миграция, cross-checked research, competency-review, batch-обработка списка элементов через стадии. Покрывает: примитивы phase/agent/parallel/pipeline/workflow, pipeline vs parallel, schema, budget, resume, quality-паттерны (adversarial verify, judge panel, loop-until-dry), и наши добавки к платформе (accounting, bounded retry, error policy, .runs observability, eval-harness, billing-дисциплина). Триггеры: workflow, воркфлоу, оркестратор, fan-out, ultracode, deep-research, 1000 агентов, детерминированный скрипт агентов. Do NOT use to design the agent/Generator-Evaluator architecture itself (use harness-design) or for a single one-shot subagent/review where no deterministic multi-stage script is needed; this writes the JS orchestrator, it is not for ad-hoc one-off agent calls."
metadata:
  version: "1.0.0"
  source: "code.claude.com/docs/en/workflows + Workflow tool spec + deksden lessons (4 оркестратора)"
  created: "2026-05-30"
---

# Workflow Orchestration

Claude Code **dynamic workflows** - JS-скрипт, который оркестрирует
недетерминированных субагентов. Скрипт = «рельсы» (loop, branching, промежуточные
результаты в переменных); агенты = «поезда». Надёжность даёт код вокруг агентов, а не
агенты сами. Сейчас они generally available; нужен Claude Code v2.1.154+.

Этот skill - наш свод поверх официального API: что платформа уже даёт, и что мы
добавляем сами для задач, где нужна доказуемая полнота batch-результата.

**Текущая опора (проверено 2026-09-06):** [официальная документация](https://code.claude.com/docs/en/workflows),
[официальный разбор](https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code)
и [официальный cookbook](https://platform.claude.com/cookbook/claude-agent-sdk-08-dynamic-workflows).
Дата обновления docs/cookbook на странице не указана; blog датирован 2026-06-02.

## Когда workflow, а когда нет

| | Subagent | Skill | Agent Team | **Workflow** |
|---|---|---|---|---|
| Что | воркер, спавнится разово | инструкции для Claude | сварм, коллаборация | **скрипт, исполняет runtime** |
| Кто решает что дальше | Claude, ход за ходом | Claude по промпту | Claude + обмен между агентами | **скрипт (детерминизм)** |
| Где промежуточные результаты | контекст Claude | контекст Claude | контекст Claude | **переменные скрипта** |
| Масштаб | пара задач/ход | как subagent | х2-х10 агентов | **десятки-сотни, лимит 1000** |
| Прерывание | рестарт хода | рестарт хода | рестарт хода | **resumable в той же сессии** |

**Бери workflow когда:** задаче нужно больше агентов, чем удержит один контекст; нужна
повторяемая оркестрация как читаемый скрипт; нужен repeatable quality-паттерн
(агенты adversarially проверяют находки друг друга перед тем как их вернуть).

**Практический тест:** бери workflow, когда работа больше контекста одного агента или один
и тот же шаг надо повторить по множеству независимых элементов, а orchestration полезно
сохранить и повторить. Для 1--3 одноразовых делегаций бери subagent. Это не правило «все
три условия», а выбор масштаба и повторяемости.

**НЕ бери workflow когда:** хватает 1-3 субагентов на ход (бери subagent); задача -
следование инструкции (skill); нужен интерактивный sign-off в середине (кроме permission
prompts, run не принимает mid-run input; каждый этап с sign-off = свой workflow).

**Opt-in обязателен.** Workflow tool вызывается только когда user явно дал согласие
(keyword `workflow`/`workflows` в запросе, ultracode on, или прямая просьба). Иначе -
обычные субагенты. Это и наше правило, и поведение платформы.

## Анатомия (точный API)

```js
export const meta = {                       // ПЕРВЫМ. Pure literal — без переменных,
  name: 'my-flow',                          // вызовов функций, спредов, интерполяции.
  description: 'one-liner для диалога approve',
  phases: [{ title: 'Scan', detail: '...' }, { title: 'Fix' }],  // = phase() вызовам
  whenToUse: '...',                         // опц., в списке /workflows
}
// тело — обычный async JS + примитивы:
phase('Scan')                               // группа прогресса; agent() ниже в неё
const r = await agent('prompt', {schema: S, label, phase, model, isolation, agentType})
const all = await parallel(items.map(x => () => agent(...)))   // БАРЬЕР, ждёт всех
const out = await pipeline(items, stageA, stageB)              // fan-out, БЕЗ барьера
const sub = await workflow('deep-research', {question})        // суб-воркфлоу, вложен. 1
log('сообщение пользователю')
```

- **`agent(prompt, opts?)`** → без `schema` возвращает финальный текст (string); со `schema`
  (JSON Schema) форсит StructuredOutput tool и возвращает **валидированный объект** (модель
  ретраит при mismatch); `null`, если агент остановлен в ходе run или случилась невосстановимая
  API-ошибка. opts: `label`, `phase` (явная
  группа - юзать внутри parallel/pipeline, не глобальный phase()), `model` (опускать -
  наследует модель сессии; ставить только когда уверен), `isolation:'worktree'` (дорого -
  только когда агенты параллельно мутируют файлы), `agentType` ('Explore', 'code-reviewer'...).
- **`parallel(thunks)`** - массив **функций** `()=>Promise`, барьер. Результат агента может
  быть `null`. `.filter(Boolean)` допустим только для представления уже учтённых результатов;
  для явного batch сначала свяжи каждый `null` с исходным item и верни его как pending.
- **`pipeline(items, ...stages)`** - каждый item независимо через все стадии, БЕЗ барьера
  между ними (item 2 на стадии 3, item 4 ещё на стадии 1). Если стадия даёт `null`, следующие
  могут быть пропущены; после pipeline восстанавливай состояние по исходному item. **Дефолт
  для многостадийной работы.**
- **`budget`** `{total: number|null, spent(), remaining()}` - токен-таргет хода. `total`
  null если не задан. Хард-потолок: при достижении `agent()` бросает.
- **`args`** - значение, переданное в Workflow, дословно (для параметризованных команд).

## Золотые правила (L1 корректности)

1. **pipeline по умолчанию.** parallel-барьер - ТОЛЬКО когда стадия N реально нужна ВСЕ
   результаты N-1 разом (dedup по всему множеству, early-exit по总count, «сравни с
   остальными находками»). «Надо сначала flatten/filter» - делай это ВНУТРИ стадии pipeline.
2. **Никогда `Date.now()` / `Math.random()` / argless `new Date()`** - бросают (ломают
   journaling/resume). Таймстемпы - через `args`; «случайность» - варьируй prompt/label по `idx`.
3. **Скрипт НЕ имеет fs/shell.** Читают/пишут/запускают команды только агенты (у них Bash,
   Read, Write). Скрипт лишь координирует и передаёт данные через переменные.
4. **schema для всего, что обрабатываешь кодом.** Текст парсить нельзя надёжно - schema
   даёт валидированный объект + авто-ретрай.
5. **Явный batch не теряет identity.** Не фильтруй `null` до ledger: `finder:<input>` /
   `verify:<finding>` /
   `card:<finding>` / `sample:<input>` / `judge:<input>` / `card-audit` остаётся pending.
   Card audit доказывает one-to-one set equality (count, distinct IDs, membership), не только
   count. `COMPLETE` только когда полный set доказан; иначе верни `INCOMPLETE` и named pending.
6. **meta - pure literal.** Любая вычисляемая часть = parse error.
7. **Permission mode не фиксирован skill-ом.** Subagents применяют permission rules сессии;
   agent permission prompts могут приостановить run. До long run подготовь нужный allowlist,
   но не заявляй `acceptEdits` или автоодобрение без проверки текущего режима.

## Подтверждённые текущие limits

До 16 concurrent agents (меньше на CPU-limited host) · до 4,096 items в одном `parallel()`
или `pipeline()` · 1,000 agents total на run. Dynamic workflows требуют Claude Code v2.1.154+;
bundled `/workflow-authoring` для редактирования saved script требует v2.1.248+. Остальные
числа из старого community research не используй как current contract: см.
`references/research-findings-2026-05-30.md` только как исторические заметки.

## Quality-паттерны (повышают доверие к результату)

- **Adversarial verify** - на каждую находку N независимых скептиков, промпт «опровергни,
  по умолчанию refuted=true». Убить если большинство опровергло. Ловит правдоподобно-неверное.
- **Perspective-diverse verify** - когда находка может сломаться по-разному, дай каждому
  верификатору свою линзу (correctness/security/perf/repro), не N одинаковых.
- **Judge panel** - N независимых попыток под разными углами → параллельные судьи оценивают
  → синтез из победителя + лучшие идеи из остальных. Бьёт «одна попытка, итерируем».
- **Loop-until-dry** - для discovery неизвестного размера: спавнить finders пока K раундов
  подряд не дадут ничего нового. Dedup против `seen` (всё виденное), НЕ против `confirmed` -
  иначе отклонённые находки возвращаются каждый раунд и не сходится.
- **Multi-modal sweep** - параллельные агенты, каждый ищет своим способом (по контейнеру / по
  контенту / по сущности / по времени). Каждый слеп к находкам других.
- **Completeness critic** - финальный агент «что упущено - не пройденная модальность,
  непроверенный claim, непрочитанный источник?». Найденное = следующий раунд.

Масштабируй под запрос: «найди баги» - пара finders, single-vote. «Тщательно проверь» -
больше finders, 3-5-голосный adversarial, стадия синтеза.

## Выбор паттерна оркестрации

5 структурных паттернов (детали + safety в
[references/orchestration-patterns.md](references/orchestration-patterns.md)):
sequential · operator · **split-and-merge** (наш основной fan-out) · agent teams · headless.

Принцип: **начинай проще, чем кажется; усложняй только когда измеримо упёрся.**
- **Error amplification** - в мультиагенте плохой output одного каскадит через других до того,
  как поймают. Контрмеры: schema-контракты между стадиями, adversarial verify ДО того как
  находка «folds in», fail-closed + sentinel-поля (`confidence`/`needs_human`).
- **Headless** (`claude -p` / Agent SDK / bypass) - бери ПОСЛЕДНИМ: только после интерактивной
  обкатки на выборке входов, с узким allowlist, fail-loud states, checkpoints на необратимое.
- **Model-tiering**: рутинные стадии на меньшей модели (`agent(p, {model:'sonnet'})`),
  judgment (architecture/security/debug) - дефолт сессии.
- Эффективность прогонов (resume, узкий контекст, фильтрация, тихие фейлы) - в
  `~/.claude/workflows/EFFECTIVE-AGENTS.md`.

## Наши добавки к платформе (закрытие gaps)

Платформа НЕ даёт из коробки: retry при падении агента (не schema-mismatch), multisampling,
error policy для логических ошибок, файловую observability с карточками, эвалы для самих
флоу. Мы закрываем это конвенциями - детали и готовый код в
[references/lessons-and-gaps.md](references/lessons-and-gaps.md), аннотированный рабочий
шаблон в [references/workflow-template.js](references/workflow-template.js).

Кратко:
- **`withRetry(fn, n)`** - ретрай только явно пойманного throw в ограниченном бюджете; `null`
  не ретраить вслепую, поскольку он означает остановку или unrecoverable API error. Сохрани
  исходную identity как pending. Платформенный ретрай - только на schema-mismatch.
- **`.runs/` workspace** - агенты пишут артефакты (карточки находок, промежуточные JSON) в
  `.runs/<flow>-<runId>/` через Write; `runId` приходит из `args` (в скрипте нет `Date.now`).
  Это durable observability сверх `/workflows` UI и `agent-<id>.jsonl` журналов.
- **Карточка на каждый косяк** (идея deksden) - verify не только выдаёт вердикт, но агент
  оформляет карточку `findings/<id>.md` с repro/severity/fix. Детерминированная проверка
  в скрипте: «число карточек == число подтверждённых находок».
- **Eval-harness для флоу** - эталонный `fixtures/<flow>/` (репо/датасет с известными
  косяками) → прогон флоу → проверка что косяки найдены и оформлены. См. reference.

## ⚠️ BILLING - машина по истреблению токенов

Workflow спавнит до 1000 агентов; расход кратный. Если в один поток лимит уходит за 4 часа,
х7-агентов сделает это за ~35 минут. **Дисциплина (см. `rules/safety-billing.md` Риск 4):**
- Перед большим прогоном - `/model` (на маленькой модели рутину), оценить число агентов.
- Демо/проверка флоу - 2-4 агента, read-only.
- `budget`-guard в loop-флоу: `while (budget.total && budget.remaining() > 50_000)`. Без
  `budget.total`-гарда `remaining()` = Infinity → цикл до 1000-агентного потолка.
- На Pro workflows off по дефолту (жжёт быстро) - включается в `/config`.
- НЕ запускать большой workflow без явного OK user на расход.

## Наши workflow-команды (`~/.claude/workflows/`)

- **`/scrape-batch`** - аудит+диспетч парсинг-флота по сайтам (probe → workers Up →
  Drive-sync → вердикт). Под jewelry/fashion проект. Pipeline-кейс.
- **`/deep-review-flow`** - competency-review (security/perf/arch/concurrency/...) с
  adversarial-верификацией + карточка на косяк. Перенос skill `deep-review` на рельсы.
- **`/research-cn-ru`** - research с обязательными китайскими (Alibaba/Tencent/DeepSeek,
  ModelScope) и русскими (Хабр, TG) углами, не только англо-веб. Наше правило ресерча.
- **`/dataset-validate`** - pipeline проверки датасета перед обучением (целостность картинок,
  манифест, дубликаты). Под ML-pipeline.

## Чеклист перед запуском workflow

1. Opt-in от user есть? (keyword / ultracode / прямая просьба)
2. Нужные агентам команды (ssh/rclone/git) - в tool allowlist? (иначе промпт в середине)
3. `node --check` скрипта прошёл (L1)? meta - pure literal?
4. Размер оценён, billing обсуждён если расход существенный?
5. Явный batch имеет ledger pending/completed и `COMPLETE` возможен только после card-audit?
6. Долгий прогон → промежуточное пишется в `.runs/` (resume только в той же сессии)?

## Если workflow недоступен

Не объявляй исходную работу заблокированной. Выполни её доступными авторизованными средствами
в текущей сессии; workflow остаётся необязательной формой оркестрации, а не условием результата.

## Связь с нашими правилами

- `principles/04 Deterministic Orchestration` - философская база (рельсы > настроение агента).
- `principles/06 Multi-Agent Decomposition` - когда декомпозировать.
- `rules/no-guessing.md` Independent Verifier = adversarial verify паттерн.
- `rules/safety-billing.md` Риск 4 - токен-дисциплина workflows.
- skill `agent-harness-design` / `agents-best-practices` - общая агентная архитектура.
- skill `deep-review` - ручной предшественник `/deep-review-flow`.
