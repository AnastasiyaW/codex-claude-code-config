---
paths:
  - "**/*api*.py"
  - "**/*post*.py"
  - "**/*webhook*"
  - "**/vikunja_task.py"
---

# API UTF-8 Posting — non-ASCII (Cyrillic / CJK / etc) в любой API

## Принцип

При POST/PUT любого API с **non-ASCII телом** (комментарии в issue trackers, чат-сообщения в TG / Slack / Discord, GitHub PR/issue body, любой webhook) — НЕ использовать **inline curl + bash heredoc** на Windows. Это encoding boundary leak: байты UTF-8 теряются в цепочке Claude harness → bash subprocess → cp1251/cp1252 console codepage → curl `-d`.

**После каждого non-ASCII POST'а — GET back и проверить mojibake**. Если хранилище вернуло `?????` вместо букв — сразу repost через правильный путь.

## Recurring symptom

Stored body после POST выглядит так:

```
"comment": "<p>@some_user ??????! ????? ?? ????????? <strong>??????????? events</strong>...</p>"
```

ASCII (английский, code spans `<code>foo</code>`, теги) сохранены, **только non-ASCII → литеральные `?` (0x3F)**. Это **storage-level corruption**, не render/font issue (font fallback дал бы `□` или Unicode replacement `�`).

**Verify via API GET** (не через browser — browser может также скрывать font issue):

```bash
curl -s -H "Authorization: Bearer $API_TOKEN" "$API_BASE_URL/path/$RESOURCE_ID" | \
python -c "import sys,json,io; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8');
data = json.load(sys.stdin); print(data.get('body', data)[:500])"
```

Если в output literal `?` где должен быть non-ASCII текст → corruption stored.

## Root cause analysis

Pipeline точек где UTF-8 ломается на Windows:

| Где | Почему ломается | Fix |
|---|---|---|
| **Inline `curl -d '{"text":"Привет"}'`** в Bash tool на Windows MSYS2 | bash subprocess наследует Windows console codepage cp1251/cp1252; UTF-8 байты в command line → re-encoded → `?` | `--data-binary @file.json` (UTF-8 файл) или Python urllib |
| **`subprocess.run([...], text=True)`** без `encoding="utf-8"` | Python на Windows default text mode = `locale.getpreferredencoding()` = cp1252 | Всегда `encoding="utf-8"` явно |
| **`open(path, "r")`** без `encoding="utf-8"` | Тот же default cp1252 на Windows | Всегда `encoding="utf-8"` явно |
| **`python -c "print('Привет')"`** inline | Source bytes уже могли corrupt'ся в bash command line | Записать в `.py` файл с UTF-8 BOM или явный encoding |
| **PowerShell `Invoke-WebRequest -Body $json`** | PowerShell default = UTF-16 LE → UTF-8 transcoding ошибки | `-ContentType "application/json; charset=utf-8"` + `[System.Text.Encoding]::UTF8.GetBytes($json)` |

## Mandatory pattern: Python urllib с explicit UTF-8

Минимальный inline pattern:

```python
import json, os, urllib.request

body_text = "<p>Привет, @recipient...</p>"  # full UTF-8 string
data = json.dumps({"comment": body_text}, ensure_ascii=False).encode("utf-8")  # ← critical: encode("utf-8")

req = urllib.request.Request(
    f"{os.environ['API_BASE_URL']}/path/{resource_id}",
    data=data,
    method="PUT",
    headers={
        "Authorization": f"Bearer {os.environ['API_TOKEN']}",
        "Content-Type": "application/json; charset=utf-8",
    },
)
with urllib.request.urlopen(req, timeout=15) as r:
    result = json.loads(r.read().decode("utf-8"))
print("posted, id:", result.get("id"))
```

Запускать через `python script.py` (не `python -c "..."`). Если нужен inline — сохранить в temp `.py` файл, запустить, удалить.

`ensure_ascii=False` важно: без этого `json.dumps` escapes non-ASCII в `\uXXXX` sequences (валидно, но не human-readable в storage); с `False` — UTF-8 bytes inline.

## Anti-pattern (НЕ делать)

```bash
# ❌ ВСЕ варианты ломаются на Windows с non-ASCII:
curl -X PUT -d '{"text":"Привет, @recipient"}' "$URL"
curl -X PUT --data "$(cat <<'EOF'
{"text":"Привет, @recipient"}
EOF
)" "$URL"
echo '{"text":"Привет"}' | curl -X PUT --data-binary @- "$URL"
python -c "import urllib.request, json; urllib.request.urlopen(...)"  # inline + non-ASCII literal
```

## Mandatory verification step (post-write contract)

После любого POST/PUT с non-ASCII body — **GET back и assert no-mojibake**. Это **proof loop**: post = generator, GET = verifier. Без verify — post считается failed.

Helper для quick check:

```python
def assert_no_mojibake(text: str, label: str = "stored body"):
    """Raise if `?` density looks like UTF-8 corruption."""
    # Heuristic для Cyrillic; адаптировать под ваш alphabet (CJK / Arabic / etc)
    cyrillic_chars = sum(1 for c in text if 0x0400 <= ord(c) <= 0x04FF)
    qmarks = text.count("?")
    # Если ожидался non-ASCII но в тексте 0 non-ASCII chars + много `?` → corruption
    if cyrillic_chars == 0 and qmarks > 5:
        raise RuntimeError(f"MOJIBAKE detected in {label}: 0 non-ASCII chars, {qmarks} '?'")
```

Применять сразу после `urlopen`:

```python
posted = json.loads(response.read().decode("utf-8"))
assert_no_mojibake(posted.get("comment", ""), f"resource id={posted.get('id','?')}")
```

## Recovery когда mojibake уже произошёл

1. **Не удалять** corrupt resource (есть audit trail кто/когда напортачил)
2. **Repost через правильный путь** — см. mandatory pattern выше
3. **В новом сообщении**: `@-mention` recipient + ссылка на context: "сообщение выше пришло с broken encoding (см. id=NNN), правильная версия здесь"
4. **Optional**: PATCH старый ресурс с notice "[corrupted — see updated id=MMM]" если API позволяет
5. **Записать**: добавить inline в текст "first attempt id=NNN had mojibake, this is corrected" чтобы recipient знал

## Hot-fix protocol — когда user в реальном времени flag'ит mojibake

Сигнал: user пишет "опять кракозябры", "почему `???`", "encoding broken", скриншот с `?????`.

Этот случай — операционный, минимизировать time-to-fix:

1. **НЕ извиняться, НЕ обсуждать root cause** в чате — repost немедленно (1 минута через Python pattern лучше 5 минут диалога о причине)
2. **Repost через mandatory pattern выше** (Python urllib explicit UTF-8) — НЕ retry того же broken curl
3. **GET back с `assert_no_mojibake` helper** — обязательно verify результат. Если повторный POST тоже corrupt — escalate (искать второй encoding boundary, который пропустила)
4. **Только после verification** — confirm пользователю "перепостила, теперь читается"
5. **Записать в session memory / handoff**: какой пайплайн вызвал mojibake — новый случай или повторение известного? Если повторение того же pattern в той же сессии = убрать broken путь из tool palette на остаток сессии.

Анти-паттерн: повторить broken POST с минорной правкой ("может теперь сработает") — encoding bug deterministic, retry того же пути даёт тот же `?????`.

## Mechanical enforcement (TODO)

Hook идея для будущего: `PostToolUse` на Bash, ловит curl/wget с `-d`/`--data` containing non-ASCII bytes — block + suggest Python pattern. Не реализовано (не блокировал бы все случаи: subprocess из Python тоже ломается). Пока — **culture + verification step** как primary, hook опциональный.

## Related

- `no-guessing.md` — root cause перед fix; здесь root cause = encoding boundary
- `verify-at-consumer.md` — проверять у получателя, не отправителя; assert_no_mojibake = частный случай этого pattern
