#!/usr/bin/env python3
"""Focused semantic regressions for review/reproduction skill authority."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    bug = (ROOT / "skills" / "development" / "bug-reproducer" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    deep = (ROOT / "skills" / "development" / "deep-review" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "Invocation alone to hunt for unknown bugs is inspection-only",
        "A direct request to fix or implement a reported bug",
        "Do not ask the user to approve the same scope twice",
        "materially changes",
    ):
        require(phrase in bug, f"bug-reproducer authority contract missing: {phrase}")
    require("Gate 1" in bug and "Gate 2" in bug, "bug-reproducer lost its two gates")

    for phrase in (
        "{REPO_ROOT}",
        "{REVIEW_SCRATCH}",
        "writable scratch",
        "git diff --exit-code",
        "immutable test receipts",
        "## Troubleshooting",
    ):
        require(phrase in deep, f"deep-review execution contract missing: {phrase}")

    print("test_review_skill_contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
