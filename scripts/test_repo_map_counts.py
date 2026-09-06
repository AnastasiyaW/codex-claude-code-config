"""Regression: a top/budget cap must not masquerade as extraction coverage."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile


def main() -> None:
    script = (Path(__file__).resolve().parents[1] / "skills" / "development"
              / "repo-map" / "scripts" / "repo_map.py")
    spec = importlib.util.spec_from_file_location("repo_map", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="repo-map-counts-") as directory:
        root = Path(directory)
        (root / "sample.py").write_text(
            "\n".join(f"def symbol_{i}():\n    return {i}\n" for i in range(5)),
            encoding="utf-8",
        )
        uncapped = module.build_map(root, budget_tokens=1000)
        capped = module.build_map(root, top=2, budget_tokens=1000)
        budgeted = module.build_map(root, top=2, budget_tokens=1)
        for result in (uncapped, capped, budgeted):
            assert result["files_scanned"] == 1, result
            assert result["symbols_extracted_total"] == 5, result
            assert result["symbols_total"] == result["symbols_ranked_after_top"]
        assert uncapped["symbols_emitted"] == 5, uncapped
        assert capped["symbols_ranked_after_top"] == capped["symbols_emitted"] == 2
        assert budgeted["symbols_ranked_after_top"] == 2
        assert budgeted["symbols_emitted"] == 1, budgeted
        assert "5 extracted symbols" in module.render_text(capped)
    print("test_repo_map_counts: OK (uncapped, top, budget, compatibility)")


if __name__ == "__main__":
    main()
