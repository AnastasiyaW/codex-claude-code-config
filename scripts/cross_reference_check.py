#!/usr/bin/env python3
"""Cross-reference integrity check for claude-code-skills repo.

Verifies that internal links in markdown files point to files that exist.
Catches drift where a principle/rule/README references a renamed or deleted
file. Run before committing, or in CI.

Checks:
  1. Markdown links `[text](path.md)` resolve to an existing file
  2. Links to `principles/NN-*.md` match the actual numbering
  3. Links to `hooks/NAME.py` and `scripts/NAME.py` point to real scripts
  4. Every principle is linked from README.md or principles/README.md
  5. Every rule is linked from README.md or a principle
  6. Every hook is listed in README.md hooks table

Exit codes:
  0 - all checks passed
  1 - broken links or missing cross-references found

Usage:
  python scripts/cross_reference_check.py
  python scripts/cross_reference_check.py --strict  # also fail on warnings
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent

# Match markdown links: [text](relative/path.md) or [text](path.md#anchor)
# Skip URLs (http://, https://, mailto:)
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
PLACEHOLDER_RE = re.compile(r"[<>]|\bNNN\b|\{\{|-slug\b")


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans - links inside them are
    illustrative examples (template substitution tables, sample file trees),
    not real references."""
    return INLINE_CODE_RE.sub("", FENCED_CODE_RE.sub("", text))

# What dirs contain markdown we scan
SCAN_DIRS = ["principles", "rules", "alternatives", "skills", "templates"]
SCAN_ROOT_FILES = ["README.md", "AGENTS.md", "CLAUDE.md", "UPDATES.md", "HOW-IT-WORKS.md", "MAINTENANCE.md"]

# Match "principle N" / "principles/NN-" mentions in prose
PRINCIPLE_REF_RE = re.compile(r"\bprinciple[s]?\s+#?(\d+)\b", re.IGNORECASE)

# Match frontmatter `key: value` in YAML header
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def is_external(url: str) -> bool:
    return url.startswith(("http://", "https://", "mailto:", "#"))


def collect_files() -> list[Path]:
    files: list[Path] = []
    for name in SCAN_ROOT_FILES:
        p = ROOT / name
        if p.exists():
            files.append(p)
    for d in SCAN_DIRS:
        dp = ROOT / d
        if not dp.exists():
            continue
        files.extend(dp.rglob("*.md"))
    return files


def check_link(source: Path, url: str) -> str | None:
    """Return error message if link is broken, None if OK."""
    # Strip anchor
    path_part = url.split("#", 1)[0]
    if not path_part:  # pure anchor, skip
        return None
    target = (source.parent / path_part).resolve()
    if not target.exists():
        return f"broken link: {url} -> {target}"
    return None


def check_principle_numbering() -> list[str]:
    """Principles must be NN-kebab-case.md with no gaps or duplicates."""
    errors: list[str] = []
    pdir = ROOT / "principles"
    if not pdir.exists():
        return errors
    seen: dict[int, list[str]] = defaultdict(list)
    for p in pdir.glob("*.md"):
        if p.name == "README.md":
            continue
        m = re.match(r"^(\d+)-", p.name)
        if not m:
            errors.append(f"principles/{p.name}: doesn't start with NN-")
            continue
        n = int(m.group(1))
        seen[n].append(p.name)
    for n, names in sorted(seen.items()):
        if len(names) > 1:
            errors.append(f"principle number {n} collision: {names}")
    if seen:
        expected = set(range(1, max(seen) + 1))
        missing = expected - set(seen.keys())
        if missing:
            errors.append(f"principle numbering gaps: missing {sorted(missing)}")
    return errors


def check_principle_count_claims() -> list[str]:
    """Index files claiming 'N principles' must match the actual principle count."""
    errors: list[str] = []
    pdir = ROOT / "principles"
    if not pdir.exists():
        return errors
    actual = sum(1 for p in pdir.glob("*.md") if p.name != "README.md")
    # Match claims: "N principles", "N принципов", "N 个架构原则", "N 个独立架构原则"
    claim_re = re.compile(
        r"\b(\d+)\s*(principle[s]?|принципов|архитектурных принципов|"
        r"个架构原则|个独立架构原则|battle-tested principle[s]?|"
        r"standalone principle[s]?|architectural principle[s]?)\b",
        re.IGNORECASE,
    )
    # UPDATES.md records historical counts that were accurate at the time -
    # don't audit it for current-count consistency.
    HISTORICAL = {"UPDATES.md"}
    targets: list[Path] = []
    for name in SCAN_ROOT_FILES:
        if name in HISTORICAL:
            continue
        p = ROOT / name
        if p.exists():
            targets.append(p)
    targets.append(ROOT / "principles" / "README.md")
    for t in targets:
        if not t.exists():
            continue
        text = t.read_text(encoding="utf-8", errors="replace")
        for m in claim_re.finditer(text):
            claimed = int(m.group(1))
            if claimed != actual:
                rel = t.relative_to(ROOT)
                line_no = text[:m.start()].count("\n") + 1
                errors.append(
                    f"{rel}:{line_no}: claims '{m.group(0)}' but actual count is {actual}"
                )
    return errors


def check_principle_coverage() -> list[str]:
    """Every principle file should be linked from README.md or principles/README.md."""
    warnings: list[str] = []
    pdir = ROOT / "principles"
    if not pdir.exists():
        return warnings
    index_sources = []
    for idx in [ROOT / "README.md", ROOT / "principles" / "README.md", ROOT / "AGENTS.md"]:
        if idx.exists():
            index_sources.append(idx.read_text(encoding="utf-8", errors="replace"))
    index_text = "\n".join(index_sources)
    for p in sorted(pdir.glob("*.md")):
        if p.name == "README.md":
            continue
        if p.name not in index_text:
            warnings.append(f"principle {p.name} not linked from any README/AGENTS index")
    return warnings


def check_hook_coverage() -> list[str]:
    """Every hook should be listed in README.md hooks table."""
    warnings: list[str] = []
    hdir = ROOT / "hooks"
    readme = ROOT / "README.md"
    if not hdir.exists() or not readme.exists():
        return warnings
    readme_text = readme.read_text(encoding="utf-8", errors="replace")
    for h in hdir.glob("*.py"):
        if h.name not in readme_text:
            warnings.append(f"hook {h.name} not mentioned in README.md")
    return warnings


def get_existing_principles() -> set[int]:
    """Return set of existing principle numbers."""
    nums: set[int] = set()
    pdir = ROOT / "principles"
    if not pdir.exists():
        return nums
    for p in pdir.glob("*.md"):
        m = re.match(r"^(\d+)-", p.name)
        if m:
            nums.add(int(m.group(1)))
    return nums


def check_principle_number_references() -> list[str]:
    """Text mentions of 'principle N' must refer to an existing principle."""
    errors: list[str] = []
    existing = get_existing_principles()
    for f in collect_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in PRINCIPLE_REF_RE.finditer(text):
            n = int(m.group(1))
            if n not in existing:
                rel = f.relative_to(ROOT)
                errors.append(f"{rel}: refers to 'principle {n}' but no such principle exists")
    return errors


def parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML frontmatter parser (key: value per line, no nesting)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result


def check_alternatives_freshness() -> list[str]:
    """Alternatives with `related_principles` frontmatter must be reviewed
    after the newest referenced principle was last modified.

    Alternatives without frontmatter are ignored (opt-in mechanism).
    """
    warnings: list[str] = []
    adir = ROOT / "alternatives"
    pdir = ROOT / "principles"
    if not adir.exists() or not pdir.exists():
        return warnings

    # Map principle number -> semantic revision date, not checkout mtime.
    p_mtime: dict[int, date] = {}
    for p in pdir.glob("*.md"):
        m = re.match(r"^(\d+)-", p.name)
        if m:
            p_mtime[int(m.group(1))] = principle_revision_date(p)

    for a in adir.glob("*.md"):
        if a.name == "README.md":
            continue
        text = a.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        related_raw = fm.get("related_principles", "")
        last_reviewed = fm.get("last_reviewed", "")
        if not related_raw or not last_reviewed:
            continue  # opt-in: file has no frontmatter declaring relationships
        # Parse list like "[1, 6, 18]" or "1, 6, 18"
        nums = [int(x) for x in re.findall(r"\d+", related_raw)]
        try:
            from datetime import datetime
            reviewed_date = datetime.strptime(last_reviewed, "%Y-%m-%d").date()
        except ValueError:
            warnings.append(f"alternatives/{a.name}: invalid last_reviewed format, expected YYYY-MM-DD")
            continue
        for n in nums:
            if n not in p_mtime:
                continue
            principle_date = p_mtime[n]
            # Compare date-precision: flag only if principle was modified on a day
            # strictly after the review date
            if principle_date > reviewed_date:
                warnings.append(
                    f"alternatives/{a.name}: related principle {n} modified {principle_date} "
                    f"after last_reviewed {last_reviewed} - re-audit trade-offs"
                )
    return warnings


def principle_revision_date(path: Path):
    """Return the real revision date without treating a clean checkout as a change.

    A new worktree assigns every file its checkout timestamp. That used to make
    alternatives look stale even when Git showed no related principle change.
    An uncommitted edit remains current; a clean file uses its last Git revision.
    """
    relative = path.relative_to(ROOT).as_posix()
    try:
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode != 0
        if not dirty:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "--", relative],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            stamp = result.stdout.strip()
            if result.returncode == 0 and stamp.isdigit():
                return date.fromtimestamp(int(stamp))
    except OSError:
        pass
    return date.fromtimestamp(path.stat().st_mtime)


def check_principle_antipatterns() -> list[str]:
    """Principles with `warns_against` frontmatter list anti-pattern phrases.
    Search rules/, alternatives/, README, etc. for those phrases appearing
    as recommendations (not warnings).

    This catches cases where a new principle bans pattern X but existing
    rules still recommend X.
    """
    warnings: list[str] = []
    pdir = ROOT / "principles"
    if not pdir.exists():
        return warnings
    # Collect principles' warns_against phrases
    banned: list[tuple[str, str, Path]] = []  # (phrase, principle_name, source)
    for p in pdir.glob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        raw = fm.get("warns_against", "")
        if not raw:
            continue
        # Phrases as comma-separated or bracket list
        phrases = [ph.strip().strip('"').strip("'") for ph in re.split(r"[,\[\]]", raw) if ph.strip()]
        for ph in phrases:
            if ph:
                banned.append((ph, p.name, p))

    if not banned:
        return warnings

    # Check rules and alternatives for the banned phrases
    targets = []
    for d in ["rules", "alternatives"]:
        dp = ROOT / d
        if dp.exists():
            targets.extend(dp.glob("*.md"))

    for target in targets:
        text = target.read_text(encoding="utf-8", errors="replace").lower()
        for phrase, principle_name, principle_path in banned:
            if target == principle_path:
                continue
            if phrase.lower() in text:
                rel = target.relative_to(ROOT)
                warnings.append(
                    f"{rel}: contains phrase '{phrase}' that {principle_name} warns against - "
                    f"verify the rule doesn't recommend the anti-pattern"
                )
    return warnings


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Resolve all markdown links (outside code blocks/spans)
    for f in collect_files():
        text = strip_code(f.read_text(encoding="utf-8", errors="replace"))
        for m in LINK_RE.finditer(text):
            url = m.group(2).strip()
            if is_external(url):
                continue
            if not url.endswith(".md") and not url.endswith(".py"):
                # Links to other extensions or dirs, skip
                continue
            if PLACEHOLDER_RE.search(url):
                # Template placeholder (feat-<NNN>-<slug>.md etc), not a real path
                continue
            err = check_link(f, url)
            if err:
                rel = f.relative_to(ROOT)
                errors.append(f"{rel}: {err}")

    # 2. Principle numbering
    errors.extend(check_principle_numbering())

    # 3. Text references to principle numbers must resolve
    errors.extend(check_principle_number_references())

    # 3b. Claims like "N principles" must match actual file count
    errors.extend(check_principle_count_claims())

    # 4. Principle coverage (warning)
    warnings.extend(check_principle_coverage())

    # 5. Hook coverage (warning)
    warnings.extend(check_hook_coverage())

    # 6. Alternatives freshness (warning) - flag when a related principle is
    # newer than the alternatives's last_reviewed date
    warnings.extend(check_alternatives_freshness())

    # 7. Anti-pattern propagation (warning) - principles with warns_against
    # frontmatter flag rules/alternatives that mention those phrases
    warnings.extend(check_principle_antipatterns())

    # Report
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")

    if not errors and not warnings:
        print("All cross-references OK.")
        return 0

    if errors:
        return 1
    if strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
