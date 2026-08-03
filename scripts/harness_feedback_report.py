#!/usr/bin/env python3
"""Summarize harness overload events without exposing transcript contents."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("event") == "harness-overload":
            rows.append(item)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=Path.home() / ".claude" / "harness-feedback" / "events.jsonl",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = load(args.path)
    report = {
        "events": len(rows),
        "profiles": dict(Counter(row.get("profile", "unknown") for row in rows)),
        "categories": dict(
            Counter(
                category
                for row in rows
                for category in row.get("categories", [])
                if isinstance(category, str)
            )
        ),
        "release_gate_mentions": sum(bool(row.get("mentions_release_gate")) for row in rows),
        "staging_smoke_mentions": sum(bool(row.get("mentions_staging_smoke")) for row in rows),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"harness feedback events: {report['events']}")
        print(f"profiles: {report['profiles']}")
        print(f"categories: {report['categories']}")
        print(
            "release-gate mentions: "
            f"{report['release_gate_mentions']}; staging-smoke mentions: "
            f"{report['staging_smoke_mentions']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
