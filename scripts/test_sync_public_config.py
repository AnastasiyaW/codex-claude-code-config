"""Regression: public privacy scan reads publishable Git content, not local reports."""
from __future__ import annotations

import importlib.util
import subprocess
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "sync_public_config.py"
SPEC = importlib.util.spec_from_file_location("sync_public_config", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sync-public-index-") as directory:
        root = Path(directory)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "safe.md").write_text("safe public content\n", encoding="utf-8")
        (root / "reports").mkdir()
        (root / "reports" / "private.json").write_text("private runtime report\n", encoding="utf-8")
        subprocess.run(["git", "add", "safe.md"], cwd=root, check=True)
        got = [path.relative_to(root).as_posix() for path in MODULE.iter_indexed_files(root)]
        assert got == ["safe.md"], got
    print("test_sync_public_config: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
