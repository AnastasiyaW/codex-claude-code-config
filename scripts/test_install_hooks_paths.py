"""Keep the hook installer from recreating an active legacy tree."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parent / "install_hooks.py"
SPEC = importlib.util.spec_from_file_location("install_hooks", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "home"
        canonical_repo = home / ".claude" / "claude-code-config"
        other_repo = Path(td) / "checkout"
        canonical_repo.mkdir(parents=True)
        assert MODULE._global_hooks_dir(canonical_repo, home) == canonical_repo / "hooks"
        try:
            MODULE._global_hooks_dir(other_repo, home)
        except RuntimeError as exc:
            assert "non-canonical checkout" in str(exc)
        else:
            raise AssertionError("external checkout must not create a legacy global hook tree")
        isolated_home = Path(td) / "isolated-home"
        assert MODULE._global_hooks_dir(other_repo, isolated_home) == other_repo / "hooks"
        local_args = SimpleNamespace(codex=False, local=True)
        hooks_dir, settings_path = MODULE._resolve_targets(local_args)
        assert hooks_dir == Path.cwd() / ".claude" / "hooks"
        assert settings_path == Path.cwd() / ".claude" / "settings.json"
        claude_selection = MODULE._selection(SimpleNamespace(codex=False, extras=True))
        codex_selection = MODULE._selection(SimpleNamespace(codex=True, extras=True))
        assert any(entry[0] == "agent-skill-contract.py" for entry in claude_selection)
        assert all(entry[0] != "subagent-skill-context.py" for entry in claude_selection)
        assert all(entry[0] != "subagent-evidence-receipt.py" for entry in claude_selection)
        assert any(entry[0] == "subagent-skill-context.py" for entry in codex_selection)
        assert any(entry[0] == "subagent-evidence-receipt.py" for entry in codex_selection)
        assert all(entry[0] != "agent-skill-contract.py" for entry in codex_selection)
    print("test_install_hooks_paths: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
