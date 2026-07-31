# 🔴 SAFETY — единый свод (заменяет 11 файлов `safety-*.md`)

Собрано 2026-07-31 из `safety-{destructive,git-destructive,self-harm,test-muting,command-injection,
secrets,api-key-leak,auto-backup,backup-retention,billing,hooks}.md`. Оригиналы целиком —
`rules/_archive/safety-split-2026-07-31/` (там же развёрнутые разборы инцидентов).

**Поведение задаётся хуками, не этим текстом.** Правило можно забыть под нагрузкой контекста,
хук — нет (IAEA defence-in-depth: несколько независимых барьеров). Здесь — объяснение «почему»
и безопасные альтернативы. Таблица ниже сверена с `settings.json` **по факту**, а не по прошлым
докам; при расхождении источник истины — `settings.json`.

## Формат обхода

```
# claude-bypass: <key>
# Reason: <зачем и какое разрешение пользователя>
<команда>
```

`Reason:` обязателен. Env-переменные inline (`FOO=1 cmd`) хук **не видит** — нужен либо маркер,
либо заранее `export`. `all` — только по явной просьбе пользователя.

## Что включено сейчас (сверено с settings.json 2026-07-31)

| Событие | Хук | Ловит | Обход |
|---|---|---|---|
| PreToolUse `Bash` | `destructive-command-guard` | `rm -rf` корней, `DROP`/`TRUNCATE`, `docker system prune`, `mkfs`, `dd` | `destructive` |
| PreToolUse `Bash` | `git-destructive-guard` | `reset --hard`, `push --force`, `branch -D`, `clean -fdx`, `checkout -- .`, `filter-branch` | `git-destructive` |
| PreToolUse `Bash` | `command-injection-guard` | `$(...)` и бэктики с нетривиальным телом | `injection` |
| PreToolUse `Bash` | `human-confirmation-guard` | любое destructive-намерение без подтверждения | маркер `# user-confirmed: "<фраза>" <ts>`, живёт 10 мин |
| PreToolUse `Bash` | `db-snapshot-guard` | обойдённый destructive SQL без снапшота | снимает снапшот сам |
| PreToolUse `Bash` | `git-auto-backup` | перед обойдённой destructive-операцией git | создаёт ветку/stash |
| PreToolUse `Bash` | **`secret-leak-guard`** | чтение секрет-путей **и упоминание их имён в команде** | `CLAUDE_ALLOW_SECRETS=1` |
| PreToolUse `Read\|Write\|Edit\|MultiEdit` | **`secret-leak-guard`** | правка/чтение секрет-файлов | то же |
| PreToolUse `Bash\|PowerShell` | `ssh-connection-guard` | спам подключений, мёртвые маршруты, локауты | `ssh-rate`, `ssh-tunnel`, `ssh-reuse`, `ssh-lockout` |
| PreToolUse `Bash\|PowerShell` | `activity-journal-guard` | мутация общего ресурса без записи в журнал | `journal` |
| PreToolUse `Write\|Edit\|MultiEdit` | `test-muting-guard` | `@pytest.mark.skip/xfail`, `it.skip`, `@Disabled`, `t.Skip`, `#[ignore]`, `.only()` | `test-muting` |
| PreToolUse `Write\|Edit\|MultiEdit` | `github-workflow-security`, `continuity-contract-guard`, `coord-claim-guard` | правки workflow / контракта непрерывности / заявок координации | — |
| PostToolUse | `api-key-leak-detector` | ключи в выводе любого инструмента | предупреждение, не блок |
| PostToolUse | `verify-deleted-guard` | что destructive-операция реально завершилась | — |
| UserPromptSubmit | `self-harm-guard` | рестарт sshd, `killall node/bun/python`, `iptables DROP`, `reboot` | `self-harm` |
| UserPromptSubmit | `keyword-skill-router` | подсказка релевантного скилла | — |
| Stop | `stop-phrase-guard`, `test-gate-stop-hook`, `problems-md-validator`, `kb-validate-gate`, `feature-list-validator` | отговорки, красные тесты, открытые OPEN, рассинхрон KB, WIP>1 | `CLAUDE_SKIP_KB_GATE=1`, `CLAUDE_SKIP_FEATURE_CHECK=1` |
| Stop | `session-handoff-reminder`, `backup-retention-cleanup` | handoff в конце; чистка бэкапов старше 14 дней | — |
| SessionStart | `session-handoff-check`, `session-drift-validator`, `docs-staleness-guard`, `task-inbox-show` | показ handoff, мёртвые ссылки, устаревшие доки, инбокс | — |

**Расхождения, найденные при сведении 2026-07-31 (не чинила — это изменило бы поведение):**
- `secret-leak-guard` **включён**, хотя `secrets-as-data.md` и старый `safety-hooks.md` утверждают
  «НЕ wired (intentional)». Он режет не только чтение секрет-файлов, но и команды, где имя такого
  файла встречается **просто как текст** (в этой сессии дважды заблокировал `grep` по репозиторию).
  Это прямо противоречит политике «секреты = рабочие данные». Решение — за владельцем: либо
  отключить хук, либо переписать `secrets-as-data.md` под реальность.
- `precompact-handoff-guard` описан как активный, но события `PreCompact` в `settings.json` нет.
- прежний хук-напоминание журнала, привязанный к конкретному хосту, заменён общим
  `activity-journal-guard` (хостовые маршруты и их журналы — в приватном правиле подключений).

## Деструктивные команды

Блокируется то, что **нельзя откатить без бэкапа**: `rm -rf` корней/`~`/`*`, `DROP TABLE|DATABASE|
SCHEMA`, `TRUNCATE`, `DELETE FROM` без `WHERE`, `docker system prune -a --volumes`, `docker-compose
down -v`, `kubectl delete namespace|--all`, `mkfs`, `dd of=/dev/...`. `rm -rf /tmp/...` проходит.

Не покрывается (осознанный пробел): деструктив внутри скрипта (хук видит только `./script.sh`),
алиасы, `psql -f drop.sql`, вызовы DB-клиента из Python/Node. Здесь спасает только чтение файла
перед запуском.

## Git

| Деструктив | Безопасная замена |
|---|---|
| `reset --hard HEAD` | `git stash` + `git reset --keep` |
| `push --force` | `push --force-with-lease` — падает, если remote ушёл вперёд |
| `branch -D feature` | `branch -d` (падает на unmerged) → смёржить → удалить |
| `clean -fdx` | `git status` + точечный `rm` |
| `checkout -- .` | сначала `git diff`, потом точечный `checkout -- path` |

`--force-with-lease` важнее, чем кажется: он ловит гонку, когда коллега успел запушить между твоим
fetch и force. Обойдённая операция страхуется `git-auto-backup`:

- после `reset --hard` → ветка `claude-backup-<ts>`: `git log claude-backup-<ts>` → checkout/cherry-pick
- после `clean -fdx` → `git stash list` → `git stash pop stash@{N}`
- ветки/stash старше 14 дней чистит `backup-retention-cleanup` на Stop; вручную —
  `python ~/.claude/claude-code-config/hooks/backup-retention-cleanup.py`
- сохранить конкретный бэкап навсегда — переименовать, убрав префикс из паттерна

Не страхуется: force-push (remote уже перезаписан), `gc --prune=now`, `filter-repo`.

## Самоповреждение

Блокируется то, что отрезает агента от хоста или убивает его же процесс: правка
`/etc/ssh/sshd_config`, `systemctl restart sshd`, `killall node|bun|python|claude`, `pkill -f claude`,
`iptables -A INPUT -j DROP`, `ufw default deny`, `reboot`/`shutdown`/`halt`.

**Тест одним вопросом:** «если это сломает — у меня есть второй способ зайти?» Нет второго канала
(SSH/консоль VM/человек рядом) → не выполнять. Особенно коварно на нестандартном SSH-порту: rescue
хостера обычно знает про 22, про свой порт — нет.

## Заглушение тестов

Падающий тест — сигнал; заглушённый — скрытый баг в проде. Блокируются добавления
`@pytest.mark.skip/xfail`, `pytest.skip()`, `@unittest.skip`, `it.skip`/`test.skip`/`describe.skip`,
`xit`/`xdescribe`/`.todo`, **`.only()`** (коварнее всего: сьют зеленеет, реально гоняется одна
функция), `@Ignore`/`@Disabled`, `t.Skip()`, `#[ignore]`.

Легитимно: условный `skipif` по платформе; flaky с `reason=` **и ссылкой на issue**; временное
отключение с TODO и сроком. Тест мёртвой фичи — удалять целиком, а не глушить.

Не покрывается: комментирование файла целиком, изменение матчера в `pytest.ini`, удаление шага
из CI-конфига.

## Command injection

`$(...)` и бэктики исполняются **до** того, как аргумент попадёт в программу. Классика:
`gh issue create --body "текст с $(dropdb prod)"` — задумано как текст, исполнено как команда,
база дропнута. Тривиальные подстановки (`pwd`, `date`, `whoami`, `basename`, `echo`, `git`…)
проходят; деструктивный глагол внутри — жёсткий блок.

Защита без хука: **одинарные кавычки** (`'$(...)'` = литерал), heredoc с `<<'EOF'` (кавычки вокруг
EOF отключают подстановку), `--body-file`/stdin вместо inline.

Хук разбирает бэктики и в markdown-тексте, поэтому длинное описание со скиллами в бэктиках он
блокирует. Обход — писать текст файлом и добавлять его питоном, а не воевать с heredoc.

## Секреты

Политика владельца (`secrets-as-data.md`): **секреты — рабочие данные**, читаем и используем
свободно; единственная жёсткая граница — ничего секретного не уходит в **публичный** репозиторий
(pre-push `pre_push_public_repo_scan.py`, приватные репо проходят без скана). Не сваливать
plaintext-секреты в один общий дамп.

Реальность хуков расходится с политикой — см. блок расхождений выше.

`api-key-leak-detector` (PostToolUse) — детектив, не превентив: ловит в выводе `sk-ant-*`,
`sk-*`/`sk-proj-*`, `gh[pousr]_*`, `github_pat_*`, `AKIA|ASIA*`, `sk|rk|pk_live|test_*`, `xox[baprs]-*`,
`AIza*`, PEM-блоки, JWT, длинный `Bearer`. Он не блокирует (вывод уже в контексте) — он громко
предупреждает, чтобы можно было среагировать.

**Если ключ реально утёк наружу:** ротировать в сервисе → `git log -p --all -S '<фрагмент>'` на
предмет коммита → считать сессию скомпрометированной → убрать источник (hardcode → env/секрет-менеджер).
По политике владельца ротация нужна **только при реальной утечке наружу**, а не по умолчанию.

## Биллинг — молчаливые переключения тарифа

Четыре класса. Первые два переключают сессию с подписки на pay-as-you-go **без предупреждения**;
задокументированные счета: $152, $187, $200.98.

1. **`hermes.md` в истории git** ([#53262](https://github.com/anthropics/claude-code/issues/53262)).
   Строка `hermes.md` в commit-сообщениях, именах файлов или веток подхватывается системным
   промптом через git status → сессия молча уходит на extra-usage поверх Max. Проверка в новом репо
   **до** запуска: `git log --all --pretty=format:'%s %an' | grep -i hermes`, то же по
   `--name-only` и `git branch --all`. Найдено → `git filter-repo --path hermes.md --invert-paths`
   (или переписать сообщения) до новых сессий.
2. **`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` в окружении**
   ([#53728](https://github.com/anthropics/claude-code/issues/53728),
   [#39903](https://github.com/anthropics/claude-code/issues/39903)). Ключ из чужого `.env`
   (Supabase, бэкенд) молча побеждает OAuth-подписку; субагенты наследуют окружение. Проверка в
   новом shell — PowerShell: `if ($env:ANTHROPIC_API_KEY) { $env:ANTHROPIC_API_KEY = $null }`;
   bash: `[ -n "$ANTHROPIC_API_KEY" ] && unset ANTHROPIC_API_KEY`. Если ключ нужен другому сервису —
   переименовать в `<SERVICE>_ANTHROPIC_API_KEY`.
3. **Авто-пополнение на API-аккаунте.** console.anthropic.com → отключить auto-recharge, поставить
   жёсткий лимит, включить алерты.
4. **Dynamic workflows — кратный расход.** До 1000 субагентов за прогон (16 параллельно): не
   silent override, но лимит выгорает в N раз быстрее. Запускать только по явному согласию;
   оценивать fan-out **до** старта; в циклах guard `while (budget.total && budget.remaining() > 50_000)`
   (без проверки `budget.total` `remaining()` = Infinity → цикл до потолка в 1000); рутинные стадии —
   на модели поменьше; остановка — `/workflows` → `x`, завершённые агенты не теряются.

**Восстановление:** снять auth-переменную и выйти из сессии → проверить историю на `hermes.md` →
отключить авто-пополнение → тикет в support со ссылкой на issue → проверить остальные проекты.

## Related
- `deletion-confirm-and-verify.md` — подтверждение до удаления и проверка после.
- `secrets-as-data.md` — политика секретов (сейчас расходится с включённым хуком).
- `connections.md` — маршруты подключений, локауты, дисциплина SSH.
- `activity-journal-and-state-registry.md` — журнал мутаций общего ресурса.
- `no-claude-attribution.md` — защита от harness-detection в коммитах.
- `rules/_archive/safety-split-2026-07-31/` — исходные 11 файлов целиком.
