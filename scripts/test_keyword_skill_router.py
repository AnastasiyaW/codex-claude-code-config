"""Does each decision moment reach exactly the right one of the four?

Nine author-shaped skills competed on the words design / architecture / refactoring /
quality. Four topic skills only help if the router can actually tell them apart, so
every case below is a real UserPromptSubmit event through the real hook.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HOOK = Path.home() / ".claude" / "claude-code-config" / "hooks" / "keyword-skill-router.py"

CASES = [
    # starting / laying out
    ("сделай сайт машинок с бэкендом", "architecture-first"),
    ("новый проект: сервис для очереди задач", "architecture-first"),
    ("спроектируй структуру проекта", "architecture-first"),
    ("build a new service for image jobs", "architecture-first"),
    ("куда положить этот код", "architecture-first"),
    ("сделай новый многостраничный веб-сервис, чтобы код оставался читаемым", "architecture-quality"),
    ("architecture review: frontend стал нечитаемым", "architecture-quality"),
    ("keep the web app readable while adding this feature", "architecture-quality"),
    # capacity / data
    ("выдержит ли это нагрузку", "system-and-data-design"),
    ("какую базу данных выбрать", "system-and-data-design"),
    ("which database should we choose", "system-and-data-design"),
    ("нужно ли шардирование", "system-and-data-design"),
    ("запрос медленный под нагрузкой", "system-and-data-design"),
    # unit quality
    ("отревьюй этот код", "code-complexity"),
    ("этот модуль тяжело читать", "code-complexity"),
    ("too many parameters in this function", "code-complexity"),
    # already too big
    ("разбей main.py, он слишком большой", "refactoring-safely"),
    ("this module is too big, split it", "refactoring-safely"),
    ("вынеси это в отдельный модуль", "refactoring-safely"),
    # unchanged neighbours
    ("упрости этот код", "lean-code"),
    ("почему падает тест, что не так, разберись", "investigate"),
    # testing strategy
    ("составь план тестирования для этой фичи", "testing-strategy"),
    ("which tests should run for this API change", "testing-strategy"),
    ("how should we evaluate the coding agent trajectory", "testing-strategy"),
    ("the VM-harness is overloaded and blocks staging smoke", "harness-feedback"),
    ("слишком жесткий gate блокирует staging smoke", "harness-feedback"),
    ("привет, как дела", None),
]

ok = True
for prompt, expect in CASES:
    ev = json.dumps({"prompt": prompt, "hook_event_name": "UserPromptSubmit"},
                    ensure_ascii=False)
    r = subprocess.run([sys.executable, str(HOOK)], input=ev, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if expect is None:
        good = "skill-router" not in out
    else:
        good = expect in out
    if not good:
        ok = False
    print(f"  [{'ok ' if good else 'FAIL'}] {prompt!r:<44} -> {expect or '(no route)'}")
    if not good:
        print("        got:", out.strip().replace("\n", " ")[:170])

print("\nROUTER:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
