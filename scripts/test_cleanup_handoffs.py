import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from cleanup_handoffs import classify, handoff_timestamp, inventory_handoffs


def handoff_name(days_ago: int, suffix: str) -> str:
    stamp = time.localtime(time.time() - days_ago * 86400)
    return time.strftime("%Y-%m-%d_%H-%M_", stamp) + suffix + ".md"


def write_handoff(path: Path, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Handoff\n\n**Status:** {status}\n", encoding="utf-8")


class CleanupHandoffsTests(unittest.TestCase):
    def test_inventory_scans_canonical_project_handoffs_and_excludes_indexes_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep = root / "project-a" / handoff_name(1, "keep")
            archive = root / "project-b" / handoff_name(20, "closed")
            orphan = root / "project-c" / handoff_name(40, "active")
            write_handoff(keep, "ACTIVE")
            write_handoff(archive, "CLOSED")
            write_handoff(orphan, "ACTIVE")
            write_handoff(root / "archive" / "project-old" / handoff_name(90, "archived"), "CLOSED")
            write_handoff(root / "INDEX.md", "ACTIVE")
            write_handoff(root / "project-a" / "PROBLEMS.md", "ACTIVE")

            handoffs, skipped = inventory_handoffs(root)

            self.assertEqual(handoffs, sorted([keep, archive, orphan]))
            self.assertEqual(skipped, [root / "project-a" / "PROBLEMS.md"])
            now = time.time()
            self.assertEqual(classify(keep, now, 14, 30), "keep")
            self.assertEqual(classify(archive, now, 14, 30), "archive")
            self.assertEqual(classify(orphan, now, 14, 30), "orphan")

    def test_filename_timestamp_wins_over_forged_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / handoff_name(40, "active")
            write_handoff(handoff, "ACTIVE")
            now = time.time()
            Path(handoff).touch()

            self.assertIsNotNone(handoff_timestamp(handoff))
            self.assertEqual(classify(handoff, now, 14, 30), "orphan")

    def test_noncanonical_name_has_no_authoritative_timestamp(self) -> None:
        self.assertIsNone(handoff_timestamp(Path("PROBLEMS.md")))


if __name__ == "__main__":
    unittest.main()
