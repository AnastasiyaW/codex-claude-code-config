#!/usr/bin/env python3
"""SessionStart hook for the plugin install: inject an index of the shipped rules.

A Claude Code plugin cannot ship CLAUDE.md or rules/ as context, so this hook
lists every rule in the plugin's rules/ with its heading and absolute path. The
agent reads a rule file when its topic comes up. The index stays well under the
hook output limit (about 10 000 characters) so it is injected, not spilled to a
file.

    python plugin-rules-context.py            # SessionStart: print the hook JSON
    python plugin-rules-context.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

LIMIT = 9000
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(env) if env else Path(__file__).resolve().parent.parent


def heading(text: str) -> tuple[str, bool]:
    """Return (first '# ' heading, whether the rule is path-conditional)."""
    conditional = False
    match = FRONTMATTER.match(text)
    if match:
        conditional = re.search(r"^paths\s*:", match.group(1), re.M) is not None
        text = text[match.end():]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip(), conditional
    return "", conditional


def user_rules_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "rules"


def build_index(root: Path, user_rules: Path | None = None) -> str:
    """Rules the user already has under the same name in their own rules folder are loaded by
    Claude Code itself; listing them again only duplicates context (teammate install 2026-10-28: 30 of 37)."""
    rules_dir = root / "rules"
    own = {p.name.lower() for p in user_rules.glob("*.md")} if user_rules and user_rules.is_dir() else set()
    lines = [
        "Team harness rules (plugin `harness`). Claude Code does not load plugin rules on its own, "
        "so this is the index. When a topic below applies to the task, read that file before acting. "
        "Rules marked (topic) apply only to matching files or tasks.",
        f"Rules folder: {rules_dir.as_posix()}/",
    ]
    skipped = []
    for path in sorted(rules_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        if path.name.lower() in own:
            skipped.append(path.name)
            continue
        title, conditional = heading(path.read_text(encoding="utf-8", errors="replace"))
        mark = " (topic)" if conditional else ""
        lines.append(f"- {path.name}{mark}: {title or path.stem}")
    if skipped:
        lines.append(f"Not listed, already in your own rules folder {user_rules.as_posix()}/: " + ", ".join(skipped))
    text = "\n".join(lines)
    if len(text) > LIMIT:
        text = text[:LIMIT].rsplit("\n", 1)[0] + "\n- (index cut at the hook output limit; list the rules folder for the rest)"
    return text


def self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "rules").mkdir()
        (root / "rules" / "README.md").write_text("# readme\n", encoding="utf-8")
        (root / "rules" / "a.md").write_text("# Always rule\nbody\n", encoding="utf-8")
        (root / "rules" / "b.md").write_text("---\npaths:\n  - '**/x'\n---\n\n# Topic rule\n", encoding="utf-8")
        index = build_index(root)
        checks = {
            "lists always rule": "a.md: Always rule" in index,
            "marks conditional rule": "b.md (topic): Topic rule" in index,
            "skips README": "readme" not in index,
        }
        own = root / "own-rules"
        own.mkdir()
        (own / "A.md").write_text("# mine\n", encoding="utf-8")
        deduped = build_index(root, own)
        checks["skips a rule the user already has"] = "- a.md" not in deduped and "b.md (topic)" in deduped
        checks["names the skipped rule"] = "already in your own rules folder" in deduped and "a.md" in deduped
        (root / "rules" / "c.md").write_text("# " + "x" * (LIMIT * 2) + "\n", encoding="utf-8")
        checks["respects limit"] = len(build_index(root)) < LIMIT + 200
    failed = [name for name, ok in checks.items() if not ok]
    print("self-test:", "FAIL " + ", ".join(failed) if failed else "PASS")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    root = plugin_root()
    if not (root / "rules").is_dir():
        print(f"plugin-rules-context: no rules folder at {root}", file=sys.stderr)
        return 0
    payload = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": build_index(root, user_rules_dir())}}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
