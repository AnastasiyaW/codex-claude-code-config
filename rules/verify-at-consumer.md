---
paths:
  - "**/__rule_on_demand__/**"
---

# Rule — Проверять у получателя, не у отправителя

> Специализация **[no-guessing.md](no-guessing.md)** для интеграций между системами
> (webhook, API, queue, RPC). Idea credit: a collaborator's parallel Claude session,
> добавлено 2026-04-28 после реального инцидента (см. ниже "Real-world кейс").

## Triggers

Применять это правило когда работа касается:

- **Webhook integration** (sender → receiver через HTTP POST)
- **API call** где обе стороны код можно прочитать
- **Queue / pub-sub** (BullMQ, Kafka, NATS) — producer и consumer
- **RPC call** (gRPC, JSON-RPC)
- **Любой contract** между двумя кусками кода которые независимо меняются
- **Event-driven архитектура** где event shape определяется sender'ом, читается receiver'ом

Не применять когда:
- Код в одном файле / module (нет boundary)
- Используется готовая библиотека где обе стороны сделаны вместе (e.g. `pgmq`, `Sidekiq`)

## Правило

**Spec ≠ implementation.** Spec (документация, schema, OpenAPI) показывает _intent_ — какие поля есть, какие типы. Но НЕ показывает:
- **Wrapping / nesting**: site может ждать `body.data.url`, spec пишет `{url, filename, ...}`
- **Field aliasing**: receiver может читать `body.eventData?.url` пока sender пишет `data: {url}`
- **Type coercion**: spec говорит `string`, receiver делает `parseInt()` без validation
- **Optional fields**: spec помечает поле optional, receiver crash'ится без него

**Code — authoritative ground truth.** Spec — approximation. Когда spec и code расходятся — побеждает code (потому что code это то что выполняется). Поэтому:

> **Правда об интеграции живёт в коде получателя, не в spec doc и не в коде отправителя.**

**HTTP 200 ≠ correctness.** Receiver может вернуть 200 и silently drop event:
- Webhook handler с `try { ... } catch { return 200 }` — нет error propagation
- Async queue — sender'у возвращается 200 как ack приёма, но обработка падает позже
- "Webhook delivered" в логах sender'а — это proof что letter был отправлен, **не** что его прочитали

**Generator blind spot.** Когда я (или другой агент) пишет integration code, я смотрю на spec и думаю "у меня правильно". Я **не вижу** как consumer фактически парсит — это в его коде, который я могу не trace'ить. Self-review не ловит этот класс багов потому что я применяю те же mental models что использовала при написании.

## Solution: verifier-first integration

До shipping любого integration кода (webhook payload, API request body, queue message format):

1. **Прочитать код consumer'а** (file:line), не только spec doc
2. **Trace exact field paths** что receiver actually reads:
   - `body.data?.url` — wrapped в data
   - `payload.event.payload.data` — двойное nesting
   - `msg.body.toString()` + parse — string requires JSON.parse
3. **Spawn isolated agent в fresh context**:
   ```
   "Read consumer code at <file:line>. List exact field paths the
   consumer reads from payload. Compare with my proposed sender
   payload: <paste>. Verify match.
   Verdict: MATCH / MISMATCH / AMBIGUOUS + 2-3 строки почему."
   ```
4. **End-to-end test** проверяет outcome у receiver (UI render / DB write
   / queue job picked up), **не только sender log**

## Real-world кейс — file_uploaded event (2026-04-28)

| Layer | What we saw |
|---|---|
| **Spec** | `file_uploaded { url, filename, size, prompt_id }` |
| **Sender log** | `[file_uploaded] HTTP 200` ✓ |
| **Reality (consumer code)** | `services/chat/.../webhook.ts:592` reads `body.data?.url` |
| **Result if shipped without verifier** | Все события дропаются silently, UI молчит, debug 4 часа |
| **Verifier agent fresh context (15 min)** | Read webhook.ts → найдено `data?.url` → fix `data: {}` wrapping → ship clean |

**Ключевая lesson**: sender log "HTTP 200" + spec "field exists" = false confidence. Receiver code — единственная ground truth. Без verifier-агента fresh-context я бы залили в prod, потеряли часы на debug "почему UI ничего не показывает".

## Anti-patterns

❌ **"Spec доку прочитала, payload собрала по схеме — должно работать"**
Spec не описывает wrapping. Receiver уже работает по реальному формату, который может отличаться.

❌ **"HTTP 200 пришёл — значит доставлено"**
Receiver мог поймать exception в try/catch и вернуть 200 чтобы избежать retry.

❌ **"Я же сам(а) код consumer'а тоже писала — значит знаю"**
Через 2 недели после написания — не знаю, и self-review предвзят.

❌ **"OpenAPI/JSON-Schema валидирует payload, всё ок"**
Schema валидирует **shape**, не семантику. `{data: {url: "X"}}` valid, `{url: "X"}` тоже valid. Какой формат actually читается — известно только consumer code.

❌ **End-to-end test = sender side test**
"Webhook отправлен" — проверка sender'а. Нужно проверять что **receiver обработал**: row в БД, UI render, queue job processed.

❌ **"Receiver вернул HTTP 200 + я отправила событие повторно — должно работать"**
Если payload shape wrong, retry дропается так же silently. HTTP 200 при втором/третьем delivery — та же ошибка, не fix. Retry без diagnosis = waste времени.

## Mechanical enforcement (TBD)

### Hook idea: PreToolUse при git commit

При commit, если diff содержит integration code (webhook payload constructor, API request builder, queue producer):

```python
# ~/.claude/scripts/integration_verifier_reminder.py
# Detect: edit к файлу с keywords webhook/dispatch/produce/publish/POST
# Suggest: "Spawn verifier? Read consumer code at <hint>"
# Soft warn, не block.
```

Implementation TBD. Сейчас — convention.

### Slash command idea

`/verify-at-consumer <consumer-file:line>` — автоматизирует spawn isolated agent с template prompt'ом для cross-check sender vs consumer field paths.

Implementation TBD.

## Связь с другими правилами

- **[no-guessing.md](no-guessing.md)** — общий принцип "every claim needs verifiable source". Этот rule = специализация: "источник для integration code = consumer code, не spec doc".
- **Independent Verifier Agent** (in no-guessing.md) — exactly the pattern который сработал. Verifier в fresh context = independent evaluator не предвзятый собственным reasoning.
- **practice_proof_loop.md** — durable artifact (logs у consumer, DB rows, UI screenshot), не self-claim sender'а.
- **practice_structured_reasoning.md** — factory premises (что код делает) + execution trace (что receiver видит) → conclusions.

## Источники в порядке убывания силы для integration tasks

1. **Receiver code** (`grep` по field name в consumer repo) — primary ground truth
2. **Live trace / network capture** — что reality передаётся
3. **Recent commit history у receiver** — что недавно изменилось в parser
4. **OpenAPI / JSON-Schema** — approximation, может быть out-of-date
5. **README / docs** — может быть out-of-date
6. **My memory of "how it usually works"** — useless, rebuild from receiver code
