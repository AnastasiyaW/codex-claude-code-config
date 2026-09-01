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
# Test the checkout that owns this test.  Pointing through Path.home() silently
# tests an older live source while a branch is under review.
HOOK = Path(__file__).resolve().parent.parent / "hooks" / "keyword-skill-router.py"

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
    ("сделай дашборд заказов: поправь дизайн и адаптивную вёрстку", "ui-design"),
    ("Redesign this React settings form with accessible focus and responsive layout", "ui-design"),
    ("не соглашайся со мной без доказательств, проверь гипотезу", "epistemic-challenge"),
    ("challenge my assumption with evidence, not a devil's-advocate performance", "epistemic-challenge"),
    ("Translate this literal string to Russian: 'Challenge my assumption with evidence.'", None),
    ("привет, как дела", None),
]

PROFILE_CASES = [
    ("shared", "Optimize retouch plugin native C++ tensor memory", "BLOCKED_SKILL_UNAVAILABLE: native-cpp-memory", "REQUIRED: Use skill native-cpp-memory"),
    ("codex", "why error investigate this", "BLOCKED_SKILL_UNAVAILABLE: investigate", "REQUIRED: Use skill investigate"),
    ("claude", "why error investigate this", "/investigate", "BLOCKED_SKILL_UNAVAILABLE"),
    ("codex", "Optimize retouch plugin native C++ tensor memory", "BLOCKED_SKILL_UNAVAILABLE: native-cpp-memory", "REQUIRED: Use skill native-cpp-memory"),
    ("claude", "Optimize retouch plugin native C++ tensor memory", "REQUIRED: Use skill native-cpp-memory", "BLOCKED_SKILL_UNAVAILABLE"),
    ("codex", "Security audit the retouch Photoshop plugin before release", "BLOCKED_SKILL_UNAVAILABLE: retouch-security-audit", "REQUIRED: Use skill retouch-security-audit"),
    ("claude", "Security audit the retouch Photoshop plugin before release", "REQUIRED: Use skill retouch-security-audit", "BLOCKED_SKILL_UNAVAILABLE"),
    ("codex", "проверь SEO сайта и sitemap", "BLOCKED_SKILL_UNAVAILABLE: claude-seo:seo", "/claude-seo:seo"),
    ("claude", "проверь SEO сайта и sitemap", "/claude-seo:seo", "BLOCKED_SKILL_UNAVAILABLE"),
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

for profile, prompt, want, forbidden in PROFILE_CASES:
    ev = json.dumps({"prompt": prompt}, ensure_ascii=False)
    r = subprocess.run([sys.executable, str(HOOK), "--profile", profile], input=ev, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    good = want in out and forbidden not in out
    if not good:
        ok = False
    print(f"  [{'ok ' if good else 'FAIL'}] {profile:6s} {prompt!r:<42} -> {want}")
    if not good:
        print("        got:", out.strip().replace("\n", " ")[:220])

print("\nROUTER:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
