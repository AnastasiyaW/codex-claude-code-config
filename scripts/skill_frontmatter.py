#!/usr/bin/env python3
"""One parser for SKILL.md frontmatter, in the two modes that are actually needed.

Eight scripts here parsed this format independently. Two were byte-identical, the rest
were near-copies -- which is worse, because an exact copy is found by any scanner and a
near-copy drifts in silence. None of them read with `utf-8-sig`, and two anchored on
`---`, so a byte-order mark made them drop a skill without a word. Those same three
bytes hid skills from the loader, hooks.json from the Codex repair script, and two
SKILL.md files from their own frontmatter this week.

The two modes are a real distinction, not a convenience:

    loader_view()   what the Claude/Codex loader sees. A BOM means NO frontmatter,
                    because that is the truth being reported. Diagnostics need this --
                    making it tolerant would hide the defect it exists to find.
    tolerant_view() the content regardless of a BOM. Inventories and catalogues need
                    this: they describe what a file says, not whether it loads.

Pick deliberately. `recover_skill_trees.py` is the reason both exist.

Self-test: python skill_frontmatter.py --self-test
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BOM = "﻿"
_BLOCK = re.compile(r"---\r?\n(.*?)\r?\n---", re.S)
_FOLDED = {">", "|", ">-", "|-"}


def read(path: Path) -> str:
    """Read a skill file without letting a byte-order mark reach the caller as text."""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def has_bom(path: Path) -> bool:
    try:
        return path.read_bytes()[:3] == b"\xef\xbb\xbf"
    except OSError:
        return False


def loader_view(path: Path) -> str | None:
    """The frontmatter block as the LOADER sees it: None when a BOM precedes it.

    Reporting absent here is the point -- a skill whose frontmatter the loader cannot
    see has no name and is silently dropped, and a diagnostic that papers over that
    reports health the machine does not have.
    """
    if has_bom(path):
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _BLOCK.match(text)
    return m.group(1) if m else None


def tolerant_view(path: Path) -> str | None:
    """The frontmatter block regardless of a byte-order mark."""
    text = read(path)
    m = _BLOCK.match(text)
    return m.group(1) if m else None


def value(body: str, key: str) -> str:
    """One frontmatter value, including YAML folded and literal block scalars."""
    lines = body.splitlines()
    prefix = f"{key}:"
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        raw = line[len(prefix):].strip().strip("\"'")
        if raw not in _FOLDED:
            return raw
        parts: list[str] = []
        for nxt in lines[index + 1:]:
            if nxt and not nxt[0].isspace():
                break
            parts.append(nxt.strip())
        return " ".join(p for p in parts if p).strip()
    return ""


def self_test() -> int:
    import tempfile

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok ' if got == want else 'FAIL'}] {label}")

    plain = "---\nname: alpha\ndescription: does a thing\n---\n\n# Alpha\n"
    folded = "---\nname: beta\ndescription: >\n  first line\n  second line\n---\n\n# Beta\n"

    check("plain value", value(_BLOCK.match(plain).group(1), "name"), "alpha")
    check("folded value joined",
          value(_BLOCK.match(folded).group(1), "description"), "first line second line")
    check("missing key is empty", value(_BLOCK.match(plain).group(1), "nope"), "")
    check("quoted value unquoted",
          value("name: \"gamma\"", "name"), "gamma")

    with tempfile.TemporaryDirectory() as td:
        clean = Path(td) / "clean.md"
        clean.write_text(plain, encoding="utf-8")
        bommed = Path(td) / "bom.md"
        bommed.write_bytes(BOM.encode("utf-8") + plain.encode("utf-8"))

        check("clean file: loader sees it", loader_view(clean) is not None, True)
        check("clean file: tolerant sees it", tolerant_view(clean) is not None, True)
        check("BOM file: loader reports ABSENT (the defect)", loader_view(bommed), None)
        check("BOM file: tolerant still reads it", tolerant_view(bommed) is not None, True)
        check("BOM detected", has_bom(bommed), True)
        check("no BOM on the clean one", has_bom(clean), False)
        check("read() strips the mark",
              read(bommed).startswith("---"), True)
        check("missing file reads empty, does not raise",
              read(Path(td) / "nope.md"), "")

    print("\nSELF-TEST:", "PASS" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else 0)
