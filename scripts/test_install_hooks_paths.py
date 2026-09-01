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
        for name, event in (
            ("session-feedback-capture.py", "Stop"),
            ("feedback-pending-show.py", "SessionStart"),
        ):
            assert (name, event, None) in claude_selection
            assert (name, event, None) in codex_selection
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python old/batch-completion-guard.py"}]}]}}
        assert MODULE._remove_replaced_hooks(settings) == 1
        assert settings["hooks"]["Stop"] == []
        assert MODULE.COMMAND_SUFFIXES[("user-task-completion-guard.py", "SessionStart")] == " --session-start"
        target = canonical_repo / "hooks" / "user-task-completion-guard.py"
        stale = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": f"python {target} --session-start"}]}]}}
        assert MODULE._merge_hook(stale, "SessionStart", target, None) == "repaired"
        repaired = stale["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        assert repaired == f'python "{target.as_posix()}" --session-start'
        router = canonical_repo / "hooks" / "keyword-skill-router.py"
        duplicate = {"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": f'python "{router.as_posix()}"',
                        "statusMessage": "Keep this"}]},
            {"hooks": [{"type": "command", "command": f'python "{router.as_posix()}"'}]},
        ]}}
        assert MODULE._merge_hook(duplicate, "UserPromptSubmit", router, None) == "deduplicated"
        router_hooks = [
            hook for group in duplicate["hooks"]["UserPromptSubmit"]
            for hook in group["hooks"]
            if MODULE._script_name_from_command(hook["command"]) == "keyword-skill-router.py"
        ]
        assert len(router_hooks) == 1
        assert router_hooks[0]["statusMessage"] == "Keep this"
        matcher_split = {"hooks": {"PreToolUse": []}}
        assert MODULE._merge_hook(matcher_split, "PreToolUse", router, "Bash") == "added"
        assert MODULE._merge_hook(matcher_split, "PreToolUse", router, "PowerShell") == "added"
        assert len(matcher_split["hooks"]["PreToolUse"]) == 2

        git_home = Path(td) / "git-home"
        live_pre_push = MODULE._git_hooks_dir(git_home) / "pre-push"
        live_pre_push.parent.mkdir(parents=True)
        live_pre_push.write_text("legacy scanner\n", encoding="utf-8")
        installed, backup = MODULE._install_git_pre_push(git_home, dry_run=False)
        assert installed == live_pre_push
        assert backup is not None and backup.read_text(encoding="utf-8") == "legacy scanner\n"
        rendered = installed.read_text(encoding="utf-8")
        assert 'PUBLIC_SCANNER="$CANONICAL_ROOT/hooks/pre-push-public-repo-scan.py"' in rendered
        assert 'CANONICAL_ROOT="$CLAUDE_DIR/claude-code-config"' in rendered
        assert 'ATTRIBUTION_SCANNER="$CLAUDE_DIR/scripts/pre_push_claude_attribution.py"' in rendered
        assert '$CLAUDE_CONFIG_ROOT' not in rendered
        assert '"$HOME"' not in rendered
        assert rendered.startswith("#!/bin/sh")
        assert 'unset CLAUDE_CONFIG_ROOT CLAUDE_PUBLIC_SCAN_NAMES' in rendered
        assert '"$PUBLIC_SCANNER" "$@"' in rendered
        assert "scripts/pre_push_public_repo_scan.py" not in rendered

        claude_router = {"hooks": {"UserPromptSubmit": []}}
        assert MODULE._merge_hook(
            claude_router, "UserPromptSubmit", router, None, "claude"
        ) == "added"
        claude_command = claude_router["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        assert claude_command.endswith(" --profile claude"), claude_command

        codex_router = {"hooks": {"UserPromptSubmit": []}}
        assert MODULE._merge_hook(
            codex_router, "UserPromptSubmit", router, None, "codex"
        ) == "added"
        codex_command = codex_router["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        assert codex_command.endswith(" --profile codex"), codex_command
    print("test_install_hooks_paths: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
