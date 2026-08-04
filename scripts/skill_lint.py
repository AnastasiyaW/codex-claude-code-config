#!/usr/bin/env python3
"""skill-lint — deterministic SKILL.md smell checker (Agent Skills whitepaper, Google May 2026).

Flags the whitepaper's "skill smells" mechanically, in the shift-left spirit (a check, not prose):
  - description missing a "when NOT to use" negative boundary  (over-trigger risk)
  - vague description opener ("a helpful skill for…", "helps with…")  (routing is the description)
  - no positive trigger phrase ("use when …")  (under-trigger risk)
  - SKILL.md body over the word budget (default 5000)  (token-budget / context rot)
  - skill name not kebab-case  (naming convention)
  - body references nothing (no scripts/ / references/ / assets/ link) AND is short  (= a system-prompt line, not a skill)

Advisory by design: prints findings, exits 0 unless --strict. NOT a blocker.
Run:  python skill_lint.py <skills_root> [<skills_root> ...] [--strict] [--max-words N]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VAGUE_OPENERS = [
    r"^\s*a?\s*helpful skill", r"^\s*helps? (you )?with", r"^\s*a skill (that|for|to help)",
    r"^\s*this skill helps", r"^\s*utility (for|to)", r"^\s*helper for",
]
NEGATIVE_BOUNDARY = [
    r"do ?n['’]?t use", r"do not use", r"\bnot for\b", r"not used? for", r"when not to use",
    r"avoid (using|when)", r"не использ", r"не для\b", r"не применя", r"не подходит",
    r"skip (it|this) (for|when)", r"\bnot? for\b",
]
POSITIVE_TRIGGER = [
    r"\buse (this )?(skill )?when\b", r"\buse when\b", r"\btrigger", r"\bwhen the user\b", r"\buse for\b",
    r"использова(ть|нии)", r"использу", r"применя", r"вызыва",
]
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict-ish, body). Minimal YAML: name + description (incl. block scalar)."""
    fm, body = {}, text
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return fm, text
    head, body = m.group(1), m.group(2)
    # name:
    nm = re.search(r"^name:\s*(.+?)\s*$", head, re.MULTILINE)
    if nm:
        fm["name"] = nm.group(1).strip().strip("\"'")
    # description: either inline or a `|` block scalar spanning indented lines
    dm = re.search(r"^description:\s*([|>][-+]?\s*)?\n?(.*?)(?=^\w[\w-]*:|\Z)", head, re.MULTILINE | re.DOTALL)
    if dm:
        raw = dm.group(2)
        # if it was a block scalar (| or >), dedent+join; if inline, the first line holds it
        if dm.group(1):
            desc = " ".join(l.strip() for l in raw.splitlines() if l.strip())
        else:
            desc = raw.splitlines()[0].strip() if raw.strip() else ""
        fm["description"] = desc.strip().strip("\"'")
    return fm, body


def _hit(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def lint_skill(path: Path, max_words: int) -> list[str]:
    findings = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [f"unreadable: {path}"]
    fm, body = parse_frontmatter(text)
    name = fm.get("name", "")
    desc = fm.get("description", "")

    if not desc:
        findings.append("no `description` in frontmatter (the routing algorithm is missing)")
    else:
        if _hit(VAGUE_OPENERS, desc):
            findings.append("vague description opener ('helps with…' / 'a helpful skill for…') — name the trigger, inputs, output")
        if not _hit(NEGATIVE_BOUNDARY, desc):
            findings.append("description has no 'when NOT to use' boundary — over-trigger risk")
        if not _hit(POSITIVE_TRIGGER, desc):
            findings.append("description has no explicit positive trigger ('use when …') — under-trigger risk")
    if not name:
        findings.append("no `name` in frontmatter (needed for registration / portability)")
    elif not KEBAB.match(name):
        findings.append(f"skill name '{name}' is not kebab-case")

    words = len(re.findall(r"\S+", body))
    if words > max_words:
        findings.append(f"SKILL.md body is {words} words (> {max_words}) — move detail into references/")

    # references-nothing smell: short body, no link to bundled resource
    has_resource_link = bool(re.search(r"\b(scripts|references|assets)/", body))
    if not has_resource_link and words < 150:
        findings.append("short body that references no scripts/references/assets — may just be a system-prompt line, not a skill")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("roots", nargs="+", help="dirs to search for */SKILL.md")
    ap.add_argument("--max-words", type=int, default=5000)
    ap.add_argument("--strict", action="store_true", help="exit 1 if any finding")
    ap.add_argument("--allow-empty", action="store_true",
                    help="treat 'no SKILL.md found' as success instead of a wrong path")
    args = ap.parse_args()

    skill_files = []
    for r in args.roots:
        skill_files += sorted(Path(r).rglob("SKILL.md"))
    if not skill_files:
        # Zero inputs is an error, not a clean run. ESLint made exactly this change in
        # v5 -- a glob matching no files became fatal -- because the overwhelmingly
        # likely cause is a wrong path or a typo, and reporting success for it hides the
        # mistake behind a green line. The permissive behaviour is an explicit flag
        # there, and here.
        print("no SKILL.md found under:", ", ".join(args.roots), file=sys.stderr)
        print("nothing was linted, so nothing was proven; check the path or pass "
              "--allow-empty", file=sys.stderr)
        return 0 if getattr(args, "allow_empty", False) else 2

    total_findings = 0
    clean = 0
    for sf in skill_files:
        findings = lint_skill(sf, args.max_words)
        label = sf.parent.name
        if findings:
            total_findings += len(findings)
            print(f"\n[{label}]  {sf}")
            for f in findings:
                print(f"   - {f}")
        else:
            clean += 1
    print(f"\n=== {len(skill_files)} skills · {clean} clean · {total_findings} findings ===")
    return 1 if (total_findings and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
