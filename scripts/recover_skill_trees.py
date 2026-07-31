#!/usr/bin/env python3
"""Detect and repair skill trees that a machine/account move left half-copied.

Unlike `sync_skills_to_codex.py`, which deploys this repository (the source of
truth) into one active directory, this script handles the case where the source
of truth is *gone* and several partial copies survive: a home directory moved to
a new account, a profile left behind at a drive root, a copy that created every
directory but none of the files.

It looks for the four failures that hide a skill without ever raising an error:

1. Dangling junctions/symlinks. A tree built from links into another profile
   (`C:\\Users\\<old-account>\\...`, `/home/<old-user>/...`) keeps listing every
   entry after that profile is gone. `ls` and PowerShell still show directories;
   anything that filters on "is a directory" follows the link, gets False, and
   skips them without a word. Enumerate the raw directory entries, never a
   filtered listing, or the diagnosis reports a dead tree as healthy.
2. Empty directory shells. A skill directory with no `SKILL.md` is skipped by the
   loader silently, so the skill vanishes from the session's skill list while
   `ls` still shows the directory. Typically the residue of copying a tree whose
   links already dangled.
3. A UTF-8 BOM before the opening `---`. The frontmatter parser does not strip
   it, so the skill loads with a garbage description (typically the literal
   string `---`). A skill with no usable description is effectively
   un-triggerable, which looks like the model ignoring it.
4. A stale copy that lost its `name:` field. It still loads under its directory
   name, but with degraded metadata.

The repair is a union fill: a skill directory that already carries a `SKILL.md`
is authoritative and is never overwritten, so the script is idempotent and safe
to re-run. Nothing is deleted -- a directory with no donor anywhere is reported
and left in place.

Usage:
    python recover_skill_trees.py --report
    python recover_skill_trees.py --donor /mnt/old-profile/.claude/skills --dry-run
    python recover_skill_trees.py --donor C:/.agents/skills --fix-broken
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

BOM = "\ufeff"

DEFAULT_TREES = [
    Path.home() / ".agents" / "skills",  # shared with Codex
    Path.home() / ".claude" / "skills",  # read by Claude Code
]


def frontmatter(path: Path) -> str | None:
    """Return the YAML frontmatter block, or None if the loader would not see one."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if text.startswith(BOM):
        # Report as absent on purpose: this is what the loader sees.
        return None
    match = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    return match.group(1) if match else None


def field(block: str | None, name: str) -> bool:
    return bool(block) and any(l.lstrip().startswith(f"{name}:") for l in block.splitlines())


def link_target(path: Path) -> str:
    """Best-effort target of a symlink or Windows junction, for the report."""
    try:
        return str(Path(os.readlink(path)))
    except OSError:
        return "unresolved"


def diagnose(skill_dir: Path) -> str:
    if not skill_dir.is_dir():
        # A directory entry that does not resolve: a link into a profile that is
        # gone. This is the case a filtered listing drops silently.
        return "BROKEN_LINK"
    sk = skill_dir / "SKILL.md"
    if not sk.is_file():
        return "EMPTY_SHELL" if not any(skill_dir.iterdir()) else "NO_SKILL_MD"
    if sk.read_bytes().startswith(BOM.encode("utf-8")):
        return "BOM"
    block = frontmatter(sk)
    if block is None:
        return "NO_FRONTMATTER"
    if not field(block, "name"):
        return "NO_NAME"
    if not field(block, "description"):
        return "NO_DESCRIPTION"
    return "OK"


def scan(root: Path) -> dict[str, str]:
    """Diagnose every directory ENTRY, including ones that no longer resolve.

    Deliberately not `iterdir() + is_dir()`: that filter follows a link, so a
    tree of dangling junctions comes back empty and reads as "no problems".
    """
    if not root.is_dir():
        return {}
    result: dict[str, str] = {}
    with os.scandir(root) as it:
        for entry in it:
            if not entry.is_dir(follow_symlinks=False):
                continue
            result[entry.name] = diagnose(Path(entry.path))
    return dict(sorted(result.items()))


def strip_bom(path: Path) -> bool:
    raw = path.read_bytes()
    marker = BOM.encode("utf-8")
    if not raw.startswith(marker):
        return False
    path.write_bytes(raw[len(marker):])
    return True


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", action="append", type=Path, default=None,
                    help="a live skills tree to repair (repeatable); defaults to "
                         "~/.agents/skills and ~/.claude/skills")
    ap.add_argument("--donor", action="append", type=Path, default=[],
                    help="a read-only tree to pull missing skills from, e.g. an "
                         "abandoned profile (repeatable)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true", help="diagnose only, change nothing")
    ap.add_argument("--fix-broken", action="store_true",
                    help="also strip BOMs, and refresh a copy that lost its name: "
                         "field from a sibling tree that still has one")
    args = ap.parse_args()

    trees = args.tree or DEFAULT_TREES
    trees = [t for t in trees if t.is_dir()]
    if not trees:
        print("no existing skills tree given", file=sys.stderr)
        return 2
    dry = args.dry_run or args.report

    states = {t: scan(t) for t in trees}
    donors = {d: scan(d) for d in args.donor if d.is_dir()}

    print("== diagnosis ==")
    for t in trees:
        counts: dict[str, int] = {}
        for state in states[t].values():
            counts[state] = counts.get(state, 0) + 1
        ok = counts.pop("OK", 0)
        tail = "  ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no problems"
        print(f"  {t}\n      loadable={ok}  {tail}")
    for d in donors:
        healthy = sum(1 for s in donors[d].values() if s == "OK")
        print(f"  donor {d}\n      usable={healthy}")

    if args.report:
        rows = sorted({(n, s, t) for t in trees for n, s in states[t].items() if s != "OK"})
        if rows:
            print("\n== not loadable ==")
            for name, state, tree in rows:
                extra = f"  -> {link_target(tree / name)}" if state == "BROKEN_LINK" else ""
                print(f"  {state:<16} {name}{extra}")
            if any(s == "BROKEN_LINK" for _, s, _ in rows):
                print("\n  BROKEN_LINK means the entry points into a profile that no longer")
                print("  exists. The content is not here; find a surviving copy and pass it")
                print("  with --donor. The dead links must be removed by hand -- this script")
                print("  never deletes.")
        return 0

    # Union fill: every name that is healthy somewhere becomes available everywhere.
    sources: dict[str, Path] = {}
    for tree in trees:
        for name, state in states[tree].items():
            if state == "OK":
                sources.setdefault(name, tree / name)
    for donor, found in donors.items():
        for name, state in found.items():
            if state == "OK":
                sources.setdefault(name, donor / name)

    filled, fixed, refreshed, blocked = [], [], [], []
    for name, src in sorted(sources.items()):
        for tree in trees:
            dst = tree / name
            if states[tree].get(name) == "OK" or dst == src:
                continue
            if states[tree].get(name) == "BROKEN_LINK":
                # Writing through a dangling junction would fail or, worse, land
                # somewhere unintended. Removing it is a deletion, so it stays a
                # human decision.
                blocked.append(f"{name} ({tree.name})")
                continue
            if not dry:
                shutil.copytree(src, dst, dirs_exist_ok=True)
            filled.append(f"{name} -> {tree.name}")

    if args.fix_broken:
        for tree in trees:
            for name, state in states[tree].items():
                sk = tree / name / "SKILL.md"
                if state == "BOM" and sk.is_file():
                    if dry or strip_bom(sk):
                        fixed.append(f"{name} ({tree.name})")
                elif state in {"NO_NAME", "NO_FRONTMATTER"} and name in sources:
                    src = sources[name]
                    if src != tree / name:
                        if not dry:
                            shutil.copytree(src, tree / name, dirs_exist_ok=True)
                        refreshed.append(f"{name} ({tree.name})")

    tag = "[dry-run] " if dry else ""
    print(f"\n{tag}filled from a healthy copy : {len(filled)}")
    for line in filled[:20]:
        print(f"    {line}")
    if len(filled) > 20:
        print(f"    ... and {len(filled) - 20} more")
    if args.fix_broken:
        print(f"{tag}BOMs stripped              : {len(fixed)}  {', '.join(fixed) or '-'}")
        print(f"{tag}stale copies refreshed     : {len(refreshed)}  {', '.join(refreshed) or '-'}")
    if blocked:
        print(f"{tag}blocked by a dead link (remove it by hand, then re-run): {len(blocked)}")
        print("    " + ", ".join(blocked[:20]) + (" ..." if len(blocked) > 20 else ""))

    orphans = sorted({n for t in trees for n, s in states[t].items()
                      if s != "OK" and n not in sources})
    if orphans:
        print(f"{tag}no donor anywhere (left in place, never deleted): {len(orphans)}")
        print("    " + ", ".join(orphans))

    if len(trees) > 1:
        a, b = trees[0], trees[1]
        diverged = [n for n in sorted(set(states[a]) & set(states[b]))
                    if (a / n / "SKILL.md").is_file() and (b / n / "SKILL.md").is_file()
                    and digest(a / n / "SKILL.md") != digest(b / n / "SKILL.md")]
        if diverged:
            print(f"\n{tag}content differs between {a.name} and {b.name}: {len(diverged)}")
            print("    " + ", ".join(diverged))
            print("    Resolve these per file, on evidence -- neither tree is automatically")
            print("    newer. See docs/skill-tree-recovery.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
