#!/usr/bin/env python3
"""Run a small, deterministic architecture/readability audit.

This is intentionally dependency-free and advisory by default. It checks only
facts that can be established without guessing domain boundaries: source inventory,
architecture documentation, and whole-file shape. Project-specific import rules
belong in the native tool for that stack (for example import-linter or
dependency-cruiser), not in a brittle regex here.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
# Shape is defined once, in hooks/shape_common.py, and shared with
# module-shape-advisor.py. These two had already drifted apart on day one --
# see that file's docstring for what disagreeing measurers cost.
from shape_common import (  # noqa: E402
    EXEMPT_NAME_HINTS,
    EXEMPT_PARTS,
    is_exempt as _exempt,
    python_shape as _python_shape,
    shape_findings as _shape_findings,
)


SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".go", ".java", ".js", ".jsx", ".php", ".py", ".rb", ".rs",
    ".ts", ".tsx", ".vue",
}
PROJECT_MARKERS = {
    "package.json", "pyproject.toml", "setup.py", "go.mod", "cargo.toml",
    "cmakelists.txt", "pom.xml", "build.gradle", "build.gradle.kts",
    "manage.py",
}
ARCHITECTURE_NAMES = {"architecture.md", "architecture.mdx", "architecture.rst"}
ARCHITECTURE_DIR_NAMES = {"architecture", "architecture-decisions", "adr", "adrs"}


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _source_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES and not _exempt(path)
    )


def _architecture_docs(root: Path) -> list[str]:
    docs: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or _exempt(path):
            continue
        rel_parts = path.relative_to(root).parts
        lowered = path.name.lower()
        if lowered in ARCHITECTURE_NAMES:
            docs.append(_relative(root, path))
            continue
        if any(part.lower() in ARCHITECTURE_DIR_NAMES for part in rel_parts[:-1]):
            docs.append(_relative(root, path))
    return sorted(set(docs))


def _markers(root: Path) -> list[str]:
    return sorted(
        _relative(root, path)
        for path in root.rglob("*")
        if path.is_file() and path.name.lower() in PROJECT_MARKERS and not _exempt(path)
    )


def audit(root: Path) -> dict:
    root = root.resolve()
    sources = _source_files(root)
    markers = _markers(root)
    docs = _architecture_docs(root)
    shaped: list[dict[str, object]] = []
    for path in sources:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        findings = _shape_findings(path, text)
        if findings:
            shaped.append({"file": _relative(root, path), "findings": findings})

    needs_doc = len(sources) >= 3 and bool(markers)
    warnings: list[str] = []
    if needs_doc and not docs:
        warnings.append("application has several source files but no architecture document")
    if shaped:
        warnings.append(f"{len(shaped)} source file(s) cross calibrated shape thresholds")

    return {
        "root": str(root),
        "status": "WARN" if warnings else "PASS",
        "source_files": len(sources),
        "project_markers": markers,
        "architecture_docs": docs,
        "shape_findings": shaped,
        "warnings": warnings,
        "checks": {
            "architecture_anchor": "PASS" if (not needs_doc or docs) else "WARN",
            "file_shape": "PASS" if not shaped else "WARN",
        },
    }


def _render(report: dict) -> str:
    lines = [
        f"ARCHITECTURE AUDIT: {report['status']}",
        f"Root: {report['root']}",
        f"Source files: {report['source_files']}",
        f"Architecture docs: {len(report['architecture_docs'])}",
    ]
    if report["warnings"]:
        lines.append("Warnings:")
        lines.extend(f"  - {warning}" for warning in report["warnings"])
    if report["shape_findings"]:
        lines.append("Shape findings:")
        for item in report["shape_findings"]:
            lines.append(f"  - {item['file']}: {'; '.join(item['findings'])}")
    if not report["warnings"]:
        lines.append("No calibrated architecture/readability findings.")
    return "\n".join(lines)


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="architecture-audit-") as temp:
        root = Path(temp)
        (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        (root / "src").mkdir()
        for name, body in (("a.py", "def a():\n    return 1\n"), ("b.py", "def b():\n    return 2\n"), ("c.py", "def c():\n    return 3\n")):
            (root / "src" / name).write_text(body, encoding="utf-8")
        first = audit(root)
        checks = [("missing architecture anchor is reported", first["status"] == "WARN")]
        (root / "ARCHITECTURE.md").write_text("# Fixture architecture\n", encoding="utf-8")
        long_file = "\n".join(f"value_{i} = {i}" for i in range(805)) + "\n"
        (root / "src" / "large.py").write_text(long_file, encoding="utf-8")
        second = audit(root)
        checks += [
            ("architecture anchor clears after documentation", second["checks"]["architecture_anchor"] == "PASS"),
            ("large source shape is reported", bool(second["shape_findings"])),
            ("strict signal remains WARN, not a guessed failure", second["status"] == "WARN"),
        ]
        ok = True
        for label, passed in checks:
            print(f"  [{'ok ' if passed else 'FAIL'}] {label}")
            ok = ok and passed
    print("\nSELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true", help="return 1 when advisory findings exist")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    report = audit(args.root)
    if args.as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_render(report))
    return 1 if args.strict and report["status"] != "PASS" else 0


if __name__ == "__main__":
    sys.exit(main())
