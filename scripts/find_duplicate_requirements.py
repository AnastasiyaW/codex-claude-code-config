"""Same requirement in a rule AND a skill? That is the expensive kind.

Rules load on every session; skills load on demand. A requirement written in both means
the rule already covers it and the skill copy is dead weight that can drift out of
agreement with the thing that actually governs. Worse than two skills repeating each
other, because one of the two is always in context and the other only sometimes.

Scans four corpora: rules/, principles/, skills/**/SKILL.md, skills/**/references/.
"""
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path.home() / ".claude" / "claude-code-config"

MODAL = re.compile(
    r"\b(must|never|always|do not|don't|required|forbidden|prefer|avoid|"
    r"обязан|нельзя|всегда|никогда|запрещено)\b", re.I)
FILLER = re.compile(r"\b(the|a|an|and|or|of|to|in|for|with|on|is|are|be|it|that|this|"
                    r"your|you|we|our|its|their|as|by|at|from|then|than|so|if|when)\b", re.I)


def requirements(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^\s*\|.*\|\s*$", " ", text, flags=re.M)
    for raw in re.split(r"(?<=[.!?])\s+|\n[-*]\s+|\n\d+\.\s+", text):
        s = " ".join(raw.strip().lstrip("-*# ").split())
        if 45 <= len(s) <= 240 and MODAL.search(s):
            yield s


def shape(s):
    s = re.sub(r"`[^`]*`|\[[^\]]*\]\([^)]*\)|\d+", " ", s)
    s = FILLER.sub(" ", s.lower())
    s = re.sub(r"[^a-zа-я ]+", " ", s)
    return " ".join(sorted(set(w for w in s.split() if len(w) > 3)))


CORPORA = {
    "rule": sorted((R / "rules").glob("*.md")),
    "principle": sorted((R / "principles").glob("*.md")),
    "skill": sorted((R / "skills").rglob("SKILL.md")),
    "reference": sorted(p for p in (R / "skills").rglob("references/*.md")),
}

items = []
for kind, files in CORPORA.items():
    for p in files:
        label = p.parent.name if kind in ("skill",) else p.stem
        if kind == "reference":
            label = f"{p.parent.parent.name}/{p.stem}"
        for s in requirements(p.read_text(encoding="utf-8-sig", errors="replace")):
            sh = shape(s)
            if len(sh.split()) >= 6:
                items.append((kind, label, s, sh))

for k in CORPORA:
    print(f"  {k:<12} {sum(1 for i in items if i[0] == k):>4} requirements "
          f"from {len(CORPORA[k])} files")
print()

used, groups = set(), []
for i, (ka, la, ta, sa) in enumerate(items):
    if i in used:
        continue
    hit = [(ka, la, ta)]
    for j in range(i + 1, len(items)):
        if j in used:
            continue
        kb, lb, tb, sb = items[j]
        if (ka, la) == (kb, lb):
            continue
        if SequenceMatcher(None, sa, sb).ratio() >= 0.74:
            hit.append((kb, lb, tb))
            used.add(j)
    if len({(k, l) for k, l, _ in hit}) > 1:
        groups.append(hit)

cross = [g for g in groups if len({k for k, _, _ in g}) > 1]
print(f"=== repeated across DIFFERENT corpora (rule vs skill etc): {len(cross)} ===")
for g in sorted(cross, key=len, reverse=True)[:12]:
    print(f"\n  {' + '.join(sorted({k for k, _, _ in g}))}")
    for k, l, t in g[:3]:
        print(f"      [{k}:{l}] {t[:112]}")

same = [g for g in groups if len({k for k, _, _ in g}) == 1]
print(f"\n=== repeated within one corpus: {len(same)} ===")
for g in sorted(same, key=len, reverse=True)[:8]:
    print(f"\n  {g[0][0]} x{len(g)}: {', '.join(sorted({l for _, l, _ in g}))[:100]}")
    print(f"      {g[0][2][:112]}")
