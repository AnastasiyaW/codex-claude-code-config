#!/usr/bin/env python3
"""Build and check the Claude Code plugin: hooks/hooks.json and the skills list.

The plugin and `install_hooks.py --global` register the same safe-default
set, so the list has one home (SAFE_DEFAULTS) and hooks/hooks.json is generated
from it. Commands use exec form with ${CLAUDE_PLUGIN_ROOT}, so no user path and
no shell quoting reach the published file.

A plugin scans only skills/<name>/SKILL.md, so every category folder under
skills/ must be listed in plugin.json "skills"; --check fails on a missing one
instead of silently not shipping it.

    python scripts/plugin_build.py           # write hooks/hooks.json
    python scripts/plugin_build.py --check   # exit 1 if hooks.json is stale or a category is unlisted
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import skill_paths  # noqa: E402
TARGET = REPO_ROOT / "hooks" / "hooks.json"
MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
PLUGIN_ONLY = [
    # Replaces the rules/ and CLAUDE.md context a plugin cannot ship.
    ("plugin-rules-context.py", "SessionStart", None),
    # Token savers (owner 2026-10-30); the matcher re-injects after context-wiping events.
    ("benjamin-plus-inject.py", "SessionStart", "startup|resume|clear|compact"),
    ("rtk-plugin-hook.py", "PreToolUse", "Bash"),
]
# Opt-in hooks the team plugin also ships (owner 2026-10-28); event and matcher come from EXTRAS.
PLUGIN_EXTRAS = ["publish-bypass-guard.py"]


def selection() -> list[tuple[str, str, str | None]]:
    spec = importlib.util.spec_from_file_location("install_hooks", REPO_ROOT / "scripts" / "install_hooks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    extras = [entry for entry in module.EXTRAS if entry[0] in PLUGIN_EXTRAS]
    if {entry[0] for entry in extras} != set(PLUGIN_EXTRAS):
        raise SystemExit(f"PLUGIN_EXTRAS not found in install_hooks.EXTRAS: {PLUGIN_EXTRAS}")
    return list(module.SAFE_DEFAULTS) + extras + PLUGIN_ONLY


def build() -> dict:
    events: dict[str, list[dict]] = {}
    for script, event, matcher in selection():
        if not (REPO_ROOT / "hooks" / script).is_file():
            raise SystemExit(f"hook script missing: hooks/{script}")
        hook = {"type": "command", "command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/" + script]}
        groups = events.setdefault(event, [])
        group = next((g for g in groups if g.get("matcher") == matcher), None)
        if group is None:
            group = {"matcher": matcher, "hooks": []} if matcher else {"hooks": []}
            groups.append(group)
        if hook not in group["hooks"]:
            group["hooks"].append(hook)
    return {"hooks": events}


def unlisted_skill_categories() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    listed = {p.removeprefix("./").rstrip("/") for p in manifest.get("skills", [])}
    missing = []
    for folder in sorted((REPO_ROOT / "skills").iterdir()):
        if folder.is_dir() and not (folder / "SKILL.md").is_file() and any(folder.glob("*/SKILL.md")):
            rel = folder.relative_to(REPO_ROOT).as_posix()
            if rel not in listed:
                missing.append(rel)
    return missing


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        failed = False
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != text:
            print("hooks/hooks.json is stale: run python scripts/plugin_build.py")
            failed = True
        for folder in unlisted_skill_categories():
            print(f'{folder}/ holds skills but is not in .claude-plugin/plugin.json "skills"')
            failed = True
        for problem in skill_paths.broken_references(REPO_ROOT):
            print(problem)
            failed = True

        if "version" in json.loads(MANIFEST.read_text(encoding="utf-8")):
            # The manifest version overrides the marketplace entry and would freeze every install.
            print('.claude-plugin/plugin.json sets "version"; the marketplace entry must own it')
            failed = True
        if not failed:
            print("hooks/hooks.json matches SAFE_DEFAULTS + PLUGIN_EXTRAS; every skill category is listed")
        return 1 if failed else 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
