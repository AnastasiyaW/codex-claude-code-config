#!/usr/bin/env python3
"""Generate the public skills catalog from SKILL.md frontmatter."""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# One parser for this format -- see skill_frontmatter for why two modes exist.
from skill_frontmatter import value as _fm_value  # noqa: E402


_frontmatter_value = _fm_value


FRONTMATTER_RE = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n(?P<body>.*?)\r?\n---[ \t]*\r?\n",
    re.DOTALL,
)



def skill_metadata(skill_md: Path) -> tuple[str, str]:
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return skill_md.parent.name, "No frontmatter description."
    body = match.group("body")
    name = _frontmatter_value(body, "name") or skill_md.parent.name
    description = re.sub(r"\s+", " ", _frontmatter_value(body, "description")).strip()
    return name, description or "No description supplied."


def title(value: str) -> str:
    return value.replace("-", " ").title()


def render(root: Path) -> str:
    skills_root = root / "skills"
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for skill_md in sorted(skills_root.rglob("SKILL.md")):
        relative = skill_md.parent.relative_to(skills_root)
        category = "Core" if len(relative.parts) == 1 else title(relative.parts[0])
        name, description = skill_metadata(skill_md)
        link = relative.as_posix() + "/"
        groups[category].append((name, description.replace("|", "\\|"), link))

    lines = [
        "# Skills Catalog",
        "",
        "This catalog is generated from every `SKILL.md`. Regenerate it with",
        "`python scripts/generate_skills_catalog.py`; verify it with `--check`.",
        "",
        "## Install",
        "",
        "Copy a selected skill directory, not its parent category:",
        "",
        "```bash",
        "# Claude Code",
        "cp -r skills/<category>/<skill-name> ~/.claude/skills/",
        "",
        "# Codex desktop on this setup: synchronize the public source safely",
        "python scripts/sync_skills_to_codex.py --apply",
        "```",
        "",
        "The Codex sync keeps a timestamped backup of changed local skills and does not",
        "delete target-only files. After any source skill edit, regenerate",
        "`skills-lock.json` and run `python scripts/generate_skills_lock.py --check`.",
        "",
        "## Catalog",
        "",
    ]
    ordered = sorted(groups, key=lambda item: (item != "Core", item))
    for category in ordered:
        lines.extend([f"### {category}", "", "| Skill | Description |", "|---|---|"])
        for name, description, link in sorted(groups[category]):
            lines.append(f"| [{name}]({link}) | {description} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repo_root, help="repository root")
    parser.add_argument("--output", type=Path, default=None, help="output path (defaults to skills/README.md)")
    parser.add_argument("--check", action="store_true", help="fail when the committed catalog is stale")
    parser.add_argument("--allow-empty", action="store_true",
                        help="write even when zero skills were found (a real empty tree)")
    args = parser.parse_args(argv)
    output = args.output or args.root / "skills" / "README.md"
    expected = render(args.root)
    if args.check:
        actual = output.read_text(encoding="utf-8") if output.exists() else ""
        if actual != expected:
            print(f"[skills-catalog] DRIFT: {output}")
            print("  Regenerate: python scripts/generate_skills_catalog.py")
            return 1
        print(f"[skills-catalog] OK: {len(list((args.root / 'skills').rglob('SKILL.md')))} skills")
        return 0
    # A catalogue built from zero skills is not an empty catalogue, it is evidence of a
    # wrong root -- and writing it would replace the real one. Same reasoning ESLint used
    # when an unmatched glob became fatal in v5: the likely cause is a bad path, and a
    # green line hides it. Note the field does NOT share a blanket "never write empty"
    # rule (CMake keeps empty outputs so N-to-M mappings stay consistent), so this is
    # scoped to the wrong-root case rather than dressed up as a general principle.
    found = len(list((args.root / "skills").rglob("SKILL.md")))
    if not found and not args.allow_empty:
        print(f"[skills-catalog] no SKILL.md under {args.root / 'skills'} — refusing to "
              f"overwrite {output} with a catalogue of nothing. Check the root, or pass "
              f"--allow-empty if the emptiness is real.", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8")
    print(f"[skills-catalog] wrote {output} ({found} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
