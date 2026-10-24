---
paths:
  - "**/__rule_on_demand__/**"
---

# Independent System Verification — control systems и functions verify behavior независимо

## Принцип (2026-05-13, после real case watchdog v1)

Если делается система которая должна:
- **(а)** что-то отключить / убить / остановить (kill switches, deadlines)
- **(б)** за чем-то следить (watchdogs, monitors, health checks)
- **(в)** выполнить специфическое поведение (functions с side effects)

→ Необходима **независимая verification** что система реально делает что заявлено, **не self-evaluation**.

Аналогично для **любого куска кода / функции**: имя функции ≠ гарантия её behavior. Должна быть проверка что код реально делает что предполагалось.

## Real case (motivation, 2026-05-13)

**Что я написала**: `overnight_watchdog.sh` для "закроет обучение в 8 утра strict"

**Что watchdog v1 реально делал**:
```bash
while true; do
    if [ "$current_hour" -ge $DEADLINE_HOUR ]; then
        log "Deadline reached, stopping watchdog"
        break  # ← exits loop, НО НЕ KILLS trainings!
    fi
    sleep 300
done
```

**Silent failure**: watchdog "stops" но trainings продолжают running. Я не заметила пока user explicitly не спросил "проверь что watchdog не умрёт и реально остановит" — только тогда reread code и нашёл bug.

**Если бы NOT caught**: trainings ran past 8 AM deadline, GPU temps растущие, energy waste, possible thermal damage если something went wrong.

**Fix v2**: добавил `hard_kill_trainings()` с `pkill -TERM` + `pkill -KILL` fallback, heartbeat log entries, verify count after kill.

**Lesson**: function/script name (`overnight_watchdog`, `kill_at_deadline`) **не гарантирует** behavior. Must read code line by line OR test через independent agent.

## When applies (categories)

| Category | Example | Risk if не verify |
|---|---|---|
| Kill switches | watchdog stop at deadline | Resource leak (running past expected) |
| Monitors / health checks | thermal watchdog | Silent failure to detect issue |
| Schedulers / cron | overnight backup | Job не запустится, data loss |
| Auto-cleanup | cache eviction | Disk fills up |
| Safety mechanisms | rate limiters | Brute force succeeds |
| Side-effect functions | `delete_old_files()` | Wrong files deleted OR none deleted |
| Idempotent ops | "ensures X" | Doesn't actually ensure X |

## How to verify (3 layers, Defence-in-Depth)

### Layer 1: Read code line by line (basic, always do)

After writing the code, **re-read it** with skepticism:
- Does control flow match description?
- Each side effect verified?
- All branches handled?
- Edge cases (empty list, timeout, ENOENT)?

Best when **done by different person/agent** than writer. Self-review has confirmation bias.

### Layer 2: Test dry-run / mock execution (medium effort)

Run the code in safe mode:
- Watchdog with deadline 1 минута from now → does it actually kill после minute?
- Kill switch with mock target → does it select correct process?
- Schedule с test timestamp → fires correctly?

Use simulated environment чтобы не damage real system.

### Layer 3: Spawn isolated agent (recommended для critical systems)

Per `no-guessing.md` Independent Verifier pattern:

```
Agent prompt:
"Read file /path/to/watchdog.sh (or function X в code Y).
Describe in plain English what it ACTUALLY does, step by step.
Compare to expected behavior: [description here].
List any discrepancies between what it does and what it should do.
Verdict: MATCH / MISMATCH / AMBIGUOUS + reasoning."
```

Fresh-context agent has no halo bias от seeing my reasoning. Reads code as pure logic.

**This is what user did в watchdog case** — by asking specific question, prompted me к independent re-read. External questioning = external verification.

## Anti-patterns (fabrication)

| Anti-pattern | Why fails |
|---|---|
| "Function `kill_X()` kills X by name" | Function name aspirational, behavior may differ |
| "Watchdog stops trainings at deadline" | "Stops" может mean exit loop OR kill processes — ambiguous |
| "Tested locally, works" | Local test ≠ production conditions, watchdog timing may differ |
| "Script has nohup, survives shell exit" | nohup ignores SIGHUP, but PPID may не be 1 → vulnerable к other signals |
| Self-review of own code | Confirmation bias, halo from writing it |
| Trust function description | Description в comment может drift от actual code |

## Specific examples by category

### Watchdog / monitor / kill switch
- [ ] When does it trigger? (exact condition checked в code, not in description)
- [ ] What does it do when triggered? (kill code present, not just log)
- [ ] Verify kill happened? (pgrep count = 0 after)
- [ ] Survives parent shell exit? (PPID = 1)
- [ ] Heartbeat present? (else "alive" is unknown after first poll)

### Auto-cleanup / deletion
- [ ] Filter correct? (test on dry-run sample)
- [ ] Idempotent? (re-run doesn't fail)
- [ ] Records what was deleted? (audit trail)
- [ ] Confirms deletion? (file no longer exists)

### Scheduler / cron
- [ ] Time zone explicit? (UTC vs local)
- [ ] Survives reboots? (registered via cron/systemd, не just nohup)
- [ ] Logs each fire? (можно verify when it ran)
- [ ] Handles failure? (retry, alert)

### Side-effect functions
- [ ] Return value reflects actual effect? (not just "true")
- [ ] Errors propagate? (not silently swallowed)
- [ ] Atomicity? (partial state on failure?)

## Connection с другими правилами

- **`~/.claude/rules/no-guessing.md`** Independent Verifier Agent — same pattern, this rule = specific application к control systems и code functions
- **CLAUDE.md Anti-Fabrication** — function name ≠ behavior is form of fabrication
- **CLAUDE.md Generator-Evaluator Pattern** — independent evaluator catches self-bias
- **`~/.claude/rules/verify-at-consumer.md`** — verify behavior at receiver, не declared by sender
- **`~/.claude/rules/no-pre-existing-evasion.md`** — "tested OK" without artifact = evasion

## Mechanical enforcement (TBD)

Hook idea: PostToolUse on Edit/Write for `.sh`, `.py` files matching watchdog/monitor/scheduler patterns:
```python
# ~/.claude/scripts/system_verification_reminder.py
# Detect: edit к file with name *watchdog*, *monitor*, *cleanup*, *killer*
# Print reminder: "This is control system. Did you verify behavior matches description?"
# Suggest spawning isolated agent for verification.
```

Implementation deferred. Currently — culture + this rule.

## Practical workflow

1. **Write the system/function**
2. **Document expected behavior** в comment / docstring
3. **Re-read code with skepticism** — does it match documentation?
4. **For control systems / critical functions**: spawn isolated verifier agent
5. **For optional confidence**: dry-run test
6. **If verifier finds mismatch**: fix, re-verify

User catch (как в watchdog v1 case) считается **good external verification** — это успешный pattern из этого правила. User asking "проверь что X делает Y" = Layer 3 в действии.

## Sources

- Real case 2026-05-13: overnight_watchdog v1 missing kill logic, caught by user explicit query
- Anthropic Engineering "Harness Design for long-running agents" — Generator-Evaluator pattern
- `no-guessing.md` Independent Verifier Agent
- Memento Anti-Fabrication pattern
