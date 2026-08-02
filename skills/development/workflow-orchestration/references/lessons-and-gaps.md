# Lessons & Gaps - что платформа не даёт, и как мы это закрываем

Источник анализа: практик с 4 собственными оркестраторами (агентные флоу → ai-kod комбайн
с DSL/трейсами → dd-flow для кодинга → гибрид на vanilla codex). Его lessons learned по
тому, чего НЕ хватает в Anthropic dynamic workflows на момент research preview (2026-05-28),
и наши решения конвенциями.

Сначала разделим: **что уже закрыто платформой** (не дублировать), и **что valid gap**.

## Уже закрыто платформой (НЕ изобретать заново)

| «Не хватает» | Реальность |
|---|---|
| документация | Есть: `code.claude.com/docs/en/workflows` (появилась после релиза) |
| retry | Есть, но узко: `schema`-агент авто-ретраит при mismatch валидации |
| observability | `/workflows` live-view (фазы, токены, время, drill-in в агента) + авто-журнал `agent-<id>.jsonl` в transcript dir + авто-персист скрипта под session dir |
| композиция | `workflow(name, args)` - суб-воркфлоу (вложенность 1) |
| quality-паттерны | adversarial verify / judge panel / loop-until-dry задокументированы в спеке инструмента |
| resume | journaling по `agent()` вызовам, resume в той же сессии (кэш-хит на неизменённый префикс) |

## Gap 1 - retry при падении/`null` агента (не schema-mismatch)

Платформенный ретрай только на невалидный schema. Если агент бросил, упёрся в budget, или
вернул `null` (user скипнул) - это твоя забота. В `parallel`/`pipeline` упавший = `null`.

```js
// Обёртка: повторить до n раз при null/throw, варьируя label по попытке (вместо random).
async function withRetry(makeAgent, n = 2, baseLabel = 'task') {
  for (let attempt = 0; attempt <= n; attempt++) {
    try {
      const r = await makeAgent(attempt)        // makeAgent(attempt) → agent(prompt, {label:`${baseLabel}#${attempt}`, ...})
      if (r != null) return r
    } catch (e) {
      if (attempt === n) { log(`${baseLabel}: исчерпаны ретраи (${e?.message ?? e})`); return null }
    }
  }
  return null
}

// Использование внутри parallel:
const results = (await parallel(
  items.map((it, i) => () => withRetry(
    (att) => agent(promptFor(it), { label: `scan:${it.id}#${att}`, schema: S, phase: 'Scan' }),
    2, `scan:${it.id}`
  ))
)).filter(Boolean)
```

Не ретраить бесконечно: ретрай жжёт токены кратно (см. billing). 2 ретрая - разумный дефолт.

## Gap 2 - multisampling (несколько сэмплов одной задачи)

Нет встроенного. Делается через `parallel` с N тонками одной задачи + агрегация (голосование
большинством / медиана / лучший по судье). Варьируй промпт/label по индексу - в скрипте нет
`Math.random()`, разнообразие даёт сам стохастический агент + чуть разный промпт.

```js
async function multisample(makePrompt, n = 3, judge = null, label = 'sample') {
  const samples = (await parallel(
    Array.from({ length: n }, (_, i) => () =>
      agent(makePrompt(i), { label: `${label}#${i}`, schema: SAMPLE_SCHEMA }))
  )).filter(Boolean)
  if (!samples.length) return null
  if (!judge) return majorityVote(samples)        // твоя чистая функция голосования
  const scored = await parallel(samples.map((s, i) => () =>
    agent(judge(s), { label: `judge:${label}#${i}`, schema: SCORE_SCHEMA })))
  return pickBest(samples, scored.filter(Boolean))
}
```

## Gap 3 - error policy для логических ошибок (не сбоев агента)

Сбой агента ≠ логическая ошибка флоу (агент вернул валидный объект, но результат
бессмысленный/противоречивый). Решения:
- **Sentinel-поля в schema**: добавь `confidence` / `blocked` / `needs_human` в schema, и
  ветвись в скрипте по ним. Агент честно помечает «не уверен» вместо галлюцинации.
- **Отдельная цепочка обработки исключений** (паттерн deksden): подозрительные результаты
  (`confidence < 0.5`, противоречия) не выкидывать, а отправлять в отдельную verify-стадию.
- **Fail-closed для side-effects**: если стадия принимает решение о write/deploy - при любой
  неоднозначности дефолт «не делать», эскалировать в отчёт, не в действие.

```js
const judged = await pipeline(findings,
  f => agent(verifyPrompt(f), { schema: VERDICT, phase: 'Verify' }),   // VERDICT: {real:bool, confidence:num}
  (v, f) => {
    if (v == null) return { ...f, status: 'verify-failed' }            // сбой агента
    if (v.confidence < 0.5) return { ...f, status: 'low-confidence' }  // логическая неуверенность → не в confirmed
    return { ...f, status: v.real ? 'confirmed' : 'rejected' }
  })
```

## Gap 4 - файловая observability с карточками (`.runs/`)

`/workflows` UI эфемерен; журналы `agent-<id>.jsonl` низкоуровневы. Для durable, читаемого
человеком следа (и для git) - конвенция `.runs/`:

```
.runs/<flow>-<runId>/
  inputs.json            # args прогона
  findings/<id>.md       # карточка на каждый косяк: title/severity/file:line/repro/fix
  summary.md             # финальный отчёт
```

`runId` берётся из `args` (в скрипте нет `Date.now()`): таймстемп штампует main-loop ПЕРЕД
вызовом Workflow и передаёт в `args.runId`. Скрипт сам в fs не пишет - **пишет агент**:
завершающая стадия каждого пайплайна получает агента с инструкцией «оформи карточку в
`.runs/<...>/findings/<id>.md`». Детерминированная проверка в скрипте после:

```js
// Не просто доверять, что карточки оформлены - проверить (через агента-аудитора):
const audit = await agent(
  `Сосчитай файлы в .runs/${args.runId}/findings/ и верни их число и список id.`,
  { schema: { type:'object', properties:{ count:{type:'number'}, ids:{type:'array',items:{type:'string'}} }, required:['count','ids'] } })
if (audit && audit.count !== confirmed.length)
  log(`⚠️ карточек ${audit.count}, подтверждённых находок ${confirmed.length} - рассинхрон`)
```

Это реализация принципа «verify behavior independently» (имя ≠ поведение): не верим, что
агент оформил карточки, - считаем их.

## Gap 5 - эвалы для самих флоу

Как отлаживать флоу? Эталонное состояние воркспейса с известными косяками → прогон флоу →
проверка что косяки найдены и правильно оформлены.

```
~/.claude/skills/workflow-orchestration/fixtures/
  deep-review/
    buggy-repo/          # маленький репо с N намеренными косяками
    expected.json        # {findings:[{file,line,kind}], min_recall:0.8}
```

Eval-прогон (отдельный мелкий workflow или ручной): запустить `/deep-review-flow` на
`buggy-repo`, сравнить найденное с `expected.json`, посчитать recall/precision. Гейт:
recall ≥ min_recall И нет ложных «confirmed» вне expected. Это L2/L3 для флоу как продукта.
Запускать после правки логики флоу - флоу это код, регрессии реальны.

## Workspace-конвенция (передача между стадиями)

deksden передавал файлы между шагами + детерминированные проверки их наличия. В нашем API
промежуточное живёт в **переменных скрипта** (это и есть фича - не загрязняет контекст
Claude). Файлы нужны только для: (а) durable артефактов (`.runs/`), (б) данных слишком
больших для возврата агентом (агент пишет в файл, возвращает путь, следующая стадия читает).

```js
// Большой результат - агент пишет в файл, возвращает указатель, не сам контент:
const ptr = await agent(`Спарси X, запиши результат в .runs/${args.runId}/data/x.json, верни путь.`,
  { schema: { type:'object', properties:{ path:{type:'string'}, rows:{type:'number'} }, required:['path'] } })
const next = await agent(`Прочитай ${ptr.path} и сделай Y.`, { schema: Y })
```

## Подводный камень рантайма: сканер детерминизма работает подстрокой, не AST

Рантайм отвергает скрипт, если в ИСХОДНИКЕ встречаются подстроки запрещённых
недетерминированных API - **даже в строковых литералах и комментариях**, где они не
вызываются. Реальный случай (2026-05-30): демо-workflow отвергнут, потому что в тексте
промпта агенту эти API перечислялись как «проверь на эти anti-patterns». Сам скрипт был
полностью детерминированным, но naive substring-scan кода от строк не отличает.

**Правило:** в workflow-скрипте (включая промпты агентов и комментарии) описывай
недетерминизм словами («системные часы», «генератор случайных чисел»), не точными именами
API. Наш `scripts/validate.mjs` ловит это до запуска (FAIL на эти подстроки в исходнике).

## Грабли из боевого прогона (2026-05-30, /deep-review-flow на большом C++ desktop-проекте)

- **Невалидный `agentType` → тихий фейл с 0 токенов.** `agentType: 'code-reviewer'` (голый) НЕ
  резолвится - валиден неймспейс-вариант `feature-dev:code-reviewer`. `agent()` с невалидным
  типом мгновенно падает БЕЗ запуска модели (0 токенов, transcript-dir не создаётся), а в
  результате это выглядит как невинные «0 находок». Диагностика по usage: `agent_count > 0`,
  но `subagent_tokens = 0` и нет transcript-dir → тип не резолвится. Лечение: точный
  неймспейс-тип, либо вообще без `agentType` (дефолтный workflow-агент отлично ревьюит по промпту).
- **`withRetry` обязан логировать ТЕКСТ ошибки**, не голое «ретраи исчерпаны» - иначе тихий
  фейл (невалидный agentType, rate-limit) неотличим от «реально 0 находок». Лови `e.message`.
- **Запись `.md` report-файлов агентом может блокироваться** средой workflow (наблюдалось:
  summary-агент не смог записать `.runs/.../summary.md`). Наш `.runs/` паттерн: писать `.json`
  (не `.md` report), либо возвращать содержимое в результате скрипта (надёжнее для синтеза).
- **`args` может не дойти при запуске через `scriptPath`** (наблюдение: `target`/`base`/`runId`
  остались дефолтными при `Workflow({scriptPath, args})`). Надёжнее: для разовой задачи -
  inline-скрипт с зашитыми значениями; для сохранённой команды - залогировать `args.*` первой
  строкой и убедиться, что применился.

- **schema-агент может завершиться БЕЗ вызова StructuredOutput → находка ТЕРЯЕТСЯ.**
  Наблюдение (тот же прогон): 23 из 24 verify-агентов «completed without calling StructuredOutput
  after 2 nudges». Особенно когда промпт провоцирует длинный текстовый разбор - агент пишет эссе
  и «забывает» вызвать инструмент. `schema` авто-ретраит НЕВАЛИДНЫЙ вывод, но НЕ спасает от
  «вообще не вызвал tool». В parallel/pipeline такой агент = throw → item дропается в `null` →
  данные теряются тихо. Митигация: (а) краткий промпт без приглашения к эссе; (б) явно «верни
  ТОЛЬКО через structured output, без развёрнутого текста, обязательно заверши вызовом
  инструмента»; (в) считать долю успешных и при низкой - перезапустить потерянные.
  ВАЖНО (проверено на живом C++ review): промпт-форс (б) дал лишь 23/24→22/24 fail -
  почти НЕ помог. Вероятная причина - тяжёлый read-контекст (verify-агент читает 5 C++
  файлов перед выводом → «забывает» tool). Реальная митигация: УЗКИЙ контекст verify-агенту
  (одна цитата/один файл, не «перечитай всё»), либо multi-vote мелкими агентами, либо принять
  низкий yield + resume потерянных (resume дёшев: review из кэша, 0 токенов).

## Anti-patterns (ловит этот reference)

- ❌ `parallel` там, где нужен `pipeline` - барьер ждёт самого медленного, простаивают быстрые.
- ❌ Парсить текст агента регэкспом вместо `schema`.
- ❌ Забыть `.filter(Boolean)` → `null` ломает следующую стадию.
- ❌ `Date.now()`/`Math.random()` в скрипте → бросает, ломает resume.
- ❌ Бесконечный retry/loop без `budget`-гарда → 1000-агентный потолок, спалённый лимит.
- ❌ Dedup в loop-until-dry против `confirmed` вместо `seen` → не сходится.
- ❌ Доверять, что агент «оформил карточки/записал файл» без независимого подсчёта.
- ❌ Запустить большой флоу без opt-in user и обсуждения billing.
