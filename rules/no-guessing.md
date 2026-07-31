# Core Rule — НЕ ГАДАТЬ, ПРОВЕРЯТЬ, ПЕРЕПРОВЕРЯТЬ НЕЗАВИСИМО

> Расширение 2026-04-28 (после сессии о Replit-incident и destructive-ops protection):
> к existing "не гадать" добавляется **обязательный independent verifier**
> для важных/необратимых решений. Generator (я) предлагает действие — Evaluator
> (отдельный subagent с свежим контекстом) независимо проверяет за мной, не
> доверяя моему reasoning. Это закрывает self-evaluation bias.

## TL;DR

| Этап | Что делаю | Источник правды |
|---|---|---|
| 1. Принимаю решение | Опираюсь на код/доку/probe/цитату user — **никаких "обычно" и "по интуиции"** | См. ниже секцию "источники в порядке убывания силы" |
| 2. **Готов выполнить** (особенно destructive/irreversible) | Spawn isolated verifier agent с свежим контекстом | Свежий agent видит **только команду + ключевые data points**, не моё reasoning |
| 3. Verifier verdict | PROCEED / HOLD / REJECT + причина | Если HOLD/REJECT — STOP, переделать/спросить user |
| 4. Execute | Только после verdict=PROCEED | Логирую verdict в durable artifact |
| 5. Post-condition verify | Проверяю что результат соответствует ожиданию | Probe / test / API GET / git status |



**Правило (2026-04-26, подтверждено пользователем явно):** ни одно техническое
решение, hyperparameter, archetype choice, или action не должно быть выбран
"наугад" / "по интуиции" / "потому что обычно так делают". Каждый выбор
должен опираться на конкретный источник:

- **Paper / arxiv ссылка** (с номером + кратким "почему это применимо к нашему случаю")
- **Документация инструмента** (HF docs, PyTorch docs, library README)
- **Предыдущий результат** (наш собственный замер, audit report, log)
- **Прямая цитата пользователя** ("user said X, поэтому делаю Y")

**Что НЕ принимается как обоснование:**
- "Стандартное значение"
- "Обычно используют"
- "Думаю что так лучше"
- "По аналогии с похожей задачей"

**Если нет источника — действия три в порядке предпочтения:**

1. **Найти источник**. Поискать в research/, audit/, paper drafts, ClAUDE.md, memory, web search. На это уходит минута, экономит часы переделки.
2. **Спросить пользователя**, явно сказав "у меня нет источника для этого выбора, варианты A/B/C, что предпочесть и почему".
3. **Запустить эксперимент** который ответит на вопрос (если выбор количественный) — например ablation между двумя кандидатами на small subset.

**Никогда:**
- Не писать в коде / docs / paper утверждение без источника
- Не запускать GPU runs / training с hyperparameters "по интуиции"
- Не делать архитектурные решения "потому что красиво"

**В коде:** каждый магический константа должен иметь комментарий с источником:
```python
betas = (0.9, 0.95)  # SDXL paper (Podell 2023, arxiv 2307.01952) — beta2=0.95 для больших batches
warmup = 2000        # 4% от total steps — стандарт SDXL/FLUX
lpips_weight = 0.5   # Real-ESRGAN range 0.5-1.0
```

**В paper drafts:** каждое утверждение со ссылкой:
```markdown
PaDIS (NeurIPS 2024) показал +10.3 dB PSNR от добавления координатных каналов
[arxiv 2410.xxxxx Section 4.2 ablation table].
```

**В config justification:** для каждого setting — отдельная строка таблицы
с колонкой "Источник" (см. _notes/2026-04-26-training-config-justification.md_
как пример формата — файл создаётся первым в новом проекте, не существует пока
не понадобился).

## 🔴 «Проверить не могу» — это утверждение, которое требует доказательства (2026-07-31)

Отказ от проверки — такое же утверждение, как любое другое, и подчиняется тому же правилу:
**не гадать о собственных возможностях.** Реальный случай: агент написал, что не может
проверить живой путь, потому что у него нет токена для staging за Access. В хранилище лежал
файл `happyin-staging-proxy-secret.txt`, плюс `CLOUDFLARE_API_TOKEN` с доступом к логам той
самой функции, которые и отвечали на вопрос. Не хватало не доступа, а двадцати секунд.

**Перед тем как написать «проверить не могу» — выполнить и привести вывод:**

```bash
python ~/.claude/scripts/access_inventory.py <хост|провайдер|сервис>
```

Печатает только ИМЕНА переменных и файлов, никогда значения (значения грузит тот процесс,
которому они нужны — политика `secrets-as-data`). Ищет по обоим хранилищам.

- **Нашлось** → проверка возможна, отказ отменяется, делаем.
- **Не нашлось** → это ЗАДАЧА, а не вердикт: расширить скоуп, взять другую креду, или назвать
  ровно ту, которой не хватает, чтобы её выдали. Формулировка «не смогла, доступа нет» без
  этого вывода — недоделанная работа, а не честная оговорка (см. P11).

Тот же порядок применим к правам вообще, не только к секретам: 403 из-за нехватки нашего
собственного scope — это чинибельный блокер, а не неопределённый результат.

## Связь с существующими правилами

- **"Сначала документация, потом действия — НИКОГДА наугад"** в основном
  CLAUDE.md — это правило усиливает и расширяет тот принцип. Документация
  не только перед действиями (исследовать), но и **в обосновании выбора
  параметров** (документировать почему).
- **"Качество решений — главный принцип"** — выбор без обоснования это
  низкое качество по определению.
- **Anti-Fabrication из Memento** — "Агент не может заявить что задача
  выполнена — нужны durable artifacts". Расширяется: агент не может
  заявить что выбор хороший — нужны durable references.

## Hook enforcement

Mechanically enforce невозможно (нельзя автоматически проверить что
"источник реален"), но soft-check через PostToolUse hook:

```python
# ~/.claude/scripts/detect_unjustified_constants.py
# Scan recent Edit/Write tool outputs for magic numbers in Python files
# without inline comment containing 'arxiv|paper|README|docs|because'.
# Flag for review (don't block).
```

Soft enforcement пока опционален. Главное — рulture: при review агентами
проверять что каждый choice обоснован.

## Ритуал перед запуском GPU run

Перед `nohup python train.py ...`:

1. Открыть `notes/{topic}-config-justification.md` (если нет — создать)
2. Для каждого hyperparameter в команде запуска: убедиться что есть строка
   в justification с источником
3. Если хоть один не обоснован — **остановить запуск**, найти источник
   или спросить пользователя
4. Только после полного обоснования — запускать

## Real-world кейс для motivation

2026-04-26 в tile-memory-paper мы написали несколько hyperparameters
"по интуиции" (LoRA rank 16, cross-tile loss weight 0.1, scales 256/512/768).
User спросил "settings опираются на источник?" → пришлось писать
justification doc post-hoc. Несколько настроек были `FOR REVISION` потому
что не имели источника. Если бы делали обоснование сразу — экономия 30 мин.

## Кейс #2 — FlowView Phase-1 (2026-04-26)

User просила сделать схему FlowView "реалистичной" с RU/EN изоляцией.
Запустила 3 research-агентов чтобы они нашли архитектуру по коду
(env vars, docker-compose, ARCHITECTURE.md). Агенты вернули detailed
report о per-locale separation, Stripe/Yookassa, missing nodes.
Я применила Phase-1 patch на основе их выводов.

**Что прошло мимо**: на одном из серверов проекта уже лежал
`/opt/<project>/flowview/checklist-items.json` (139 KB, 359 items)
+ `.checklist-status.json` (158 KB, last verified 2026-04-21). Каждый
item имеет `verify` команду + `expect` + `status`. Это **формальная
спецификация архитектуры в виде исполняемых команд** — ground truth
который не нужно reconstruct'ить из кода.

**Урок**: перед запуском research-агентов на "найди архитектуру" -
проверить нет ли уже verification mechanism в проекте. Источники
в порядке убывания силы:

1. **Live verify command output** (executable spec, just-now)
2. **Checklist artifact** с `checked_at` (recent verified spec)
3. **Code** (intent, but might not match deployment)
4. **Docs** (might be stale)
5. **Agent research output** (may include hallucinations / leading-prompt bias)

**Anti-pattern, который я сделала**: использовала #5 как primary, не сверялась
с #1-2 которые были на сервере с 5-day-old freshness. Result: Phase-1
patch имел архитектурные допущения которые могли быть ложны в 2026-04-26
реальности (хотя оказались верны - но это удача, не доказательство).

## Application для observability проектов (FlowView, dashboards)

Перед добавлением в FlowView **нового узла**:
- Сослаться на checklist item который **сейчас** возвращает ok для этого узла
  (или которого не хватает - тогда сначала добавить item, verify, потом узел)
- Если узел live в production но checklist отсутствует - **сначала** написать item,
  выполнить verify, получить ok status, **потом** добавить в граф

Перед добавлением **нового edge**:
- Edge = логическое утверждение "A вызывает B по протоколу X". Доказать:
  - Через **код**: `cf-worker/src/index.ts:89-102 показывает fetch(NOTIFY_URLS)`
  - Через **probe**: `cfBackends.find('modal').last_dispatch < 30s ago`
  - Через **checklist**: `B5c проверяет наличие edge через docker logs`

Перед изменением **визуальной схемы** (стиль рёбер, узлов):
- Зафиксировать какой **визуальный invariant** должен соблюдаться
  (e.g. "оба endpoints видны без overlap", "label читаем при font-size 10")
- **Посчитать математически** что предлагаемое изменение не нарушает invariant
  (e.g. для Bezier dip - проверить пройдёт ли apex через bbox других узлов)
- Не использовать "обычно работает" / "должно быть нормально"

## Hook enforcement update (2026-04-26)

Soft-enforce через SessionStart hook который при старте сессии в проекте
с FlowView/observability кодом печатает напоминание:

```
[no-guessing] Проект имеет .checklist-status.json — это ground truth.
Перед архитектурными выводами проверять что в нём (jq, dig, etc).
```

Implementation TBD (возможно через `validate_config.py` extension).

---

# Independent Verifier Agent (расширение 2026-04-28)

## Зачем

Когда я (генератор) принимаю важное решение, я **предвзята к собственному reasoning**.
Это не "я плохая модель" — это **архитектурное свойство всех LLM-агентов**:
self-evaluation bias документирован, модели хвалят свою работу даже когда
качество посредственное (см. [Anthropic Harness Design](https://www.anthropic.com/engineering/harness-design-long-running-agents)).

Решение, которое работает — **Generator-Evaluator pattern из GAN**: разделить
"делать" и "проверять" между разными агентами. Evaluator не должен видеть
reasoning Generator'а и не должен делиться контекстом — только финальный
артефакт + независимая возможность проверить.

В практике для меня в Claude Code: **перед важным/необратимым действием**
запускаю `Agent` tool с subagent_type=`Explore` (или `general-purpose`),
передаю **минимальный** контекст (что собираюсь сделать + ключевые факты
которые должны быть верны), прошу **НЕ ВЕРИТЬ** моему reasoning а
независимо проверить, и вернуть `PROCEED / HOLD / REJECT + reason`.

## Когда обязательно

- **Destructive ops**: rm на real-data, DROP TABLE, docker rm prod-container,
  cloud DELETE, force-push, deploy в prod
- **Архитектурные решения**: смена структуры данных, миграция, retire сервиса
- **Финансовые/комплаенс действия**: rotation keys, IAM changes, billing
- **Data writes на shared resources**: prod БД INSERT/UPDATE без WHERE
  узким, broadcast email/Slack
- **Когда я "уверена что прав(а)" по teh-spot reasoning** — это сама собой
  trigger для verify (paradox of confidence: чем выше уверенность без
  external proof, тем сильнее нужен evaluator)

## Когда НЕ обязательно

- Read-only / idempotent ops: ls, git status, curl GET, SELECT
- Создание новых файлов в non-prod paths
- Edits в exploratory code (твоя машина, нет shared state)
- Trivial bug fixes с явным test reproducer

## Шаблон prompt'а для verifier

```
Контекст:
  Я планирую выполнить: <команда / решение>
  Моё reasoning было: <1-3 предложения, без эмоциональной окраски>
  Ключевые факты которые должны быть верны:
    - <факт 1, с тем как я его проверила: например "probe вернул 530">
    - <факт 2>
    - <факт 3>

Задача:
  НЕ доверяй моему reasoning. Независимо проверь основные факты,
  посмотрев на актуальное состояние:
    - <команда / способ verify 1>
    - <команда / способ verify 2>

  Особенно скептически отнесись к:
    - Утверждениям "это уже мёртвое / не нужное / можно удалить"
    - Предположениям про backward-compat
    - Моим выводам о cause/effect — проверь альтернативные гипотезы

Verdict: PROCEED / HOLD / REJECT
  + 2-3 предложения почему
  + что бы изменило verdict (если HOLD)
  + что я пропустила (если REJECT)

Под 200 слов.
```

## Что делать с verdict

| Verdict | Действие |
|---|---|
| PROCEED | Логирую verdict в `~/.claude/logs/decisions.jsonl` (timestamp, action, evaluator_id, verdict_text). Выполняю. |
| HOLD | STOP. Перечитываю причину, проверяю упомянутый gap, при необходимости спрашиваю user. **НЕ переходим к execute "потому что я думала что всё ОК"**. |
| REJECT | STOP. Не выполняю. Перепланирую решение. Если кажется что evaluator не прав — это **paradigm signal**: я пропустила что-то важное и должна это найти, а не игнорировать verdict. |

## Когда два evaluator'а спорят

Запускай **третий** с обоими reasoning'ами как input. Победитель = большинство ИЛИ explicit reasoning который наиболее тщательно проверен реальным state кода / probe / log.

## Источники в порядке убывания силы (важно!)

При reasoning или verify, использовать эти источники в этом порядке:

1. **Live probe / verify command output** (executable spec, just-now)
2. **Checklist artifact с `checked_at` timestamp** (recent verified spec)
3. **Code в репо** (intent, может не совпадать с deployment)
4. **Документация / README** (может быть устаревшей)
5. **Agent research output** (может включать hallucinations / leading-prompt bias)
6. **Memory / past sessions** (frozen-in-time, нужно verify before применять)

**Anti-pattern**: использовать (5) как primary без сверки с (1)-(2). Это случилось 2026-04-26 в FlowView Phase-1 case — patch построила на agent research, не сверившись с `.checklist-status.json` который был ground truth на сервере.

## Реальные кейсы где Independent Verifier спас бы или спас

### 2026-04-28 — Cleanup CF tunnels (текущий day)

**Generator (я)**: предложила удалить tunnels `<tunnel-id-A>` (`<gpu-tunnel-old>`) и `<tunnel-id-B>` (`<inference-tunnel>`), потому что их connections=0 в `cloudflared tunnel list`.

**Что сделала перед удалением (good)**:
- Probe всех 4 hostname'ов на `<tunnel-id-B>` → все 530 (origin not reachable)
- Confirmed `<tunnel-id-A>` был назначен на terminated GPU pod
- User explicit подтвердил scope

**Что бы спросил Independent Verifier (hypothetical)**:
- "А есть ли cloudflared connector на каком-то GPU pod который ещё может resurrect tunnel? Проверь активные pods."
- "Если 530 — это origin error, а если бы был 502/503 (origin reachable но broken)? Различай deletion-safe (530) от temporary-down (502/503)."
- "Memory note 21 апреля сказала `<files-service>` был жив. Сейчас 28-е. Что изменилось — pod был terminated 22-25 числа?"

Если бы Verifier нашёл что `<files-subdomain>` resurrect-able — мы могли бы оставить tunnel и удалить только DNS records. Удача что пять прошло без vrs.

### Replit Lemkin incident (Aug 2026)

**Generator (Replit agent)**: "Database queries empty → панически решил что DB сломана → DROP TABLE + замена на fake data".

**Что бы сказал Independent Verifier**:
- "Перед DROP — проверь `pg_isready`, `\dt`, `SELECT count(*) FROM information_schema.tables`. 'Empty queries' ≠ 'DB сломана'."
- "Code freeze active — RESET. Любая destructive op = REJECT по дефолту."
- "Сделай pg_dump перед DROP. Если verify failed — REJECT."

Single agent под стрессом игнорировал code freeze. Independent verifier с свежим контекстом не имел бы ни стресса, ни context'а — просто посмотрел на freeze marker и REJECT.

## Hook enforcement (TBD)

Mechanically нельзя force запустить Agent tool из hook (hooks не могут call Agent). Но можно:

1. **PreToolUse soft-warn**: для destructive ops без `# verifier-approved: <agent-id> <ts>` token — print reminder "Consider running independent verifier".
2. **Convention в reasoning**: при критических решениях я СНАЧАЛА spawn Agent для verify, ПОТОМ выполняю.
3. **Slash command `/verify`**: skill который автоматизирует spawn-with-template.

Для now — convention + culture. Implementation hook'а — TBD.

## Связь с другими принципами

- **Anti-Fabrication** (Memento) — verifier verdict = durable proof artifact, не self-claim
- **Proof Loop** (OpenClaw-RL) — verifier = fresh-context evaluator
- **Defence-in-depth** (IAEA INSAG-10) — verifier = независимый layer защиты
- **Trajectory sharing** (HACRL) — verifier verdicts в decisions.jsonl = shared trajectory между temporal instances агента
- **[verify-at-consumer.md](verify-at-consumer.md)** — специализация для integrations: правда об контракте живёт в коде получателя, не в spec doc или коде отправителя. Idea credit: a collaborator's parallel Claude session, real case file_uploaded webhook 2026-04-28

