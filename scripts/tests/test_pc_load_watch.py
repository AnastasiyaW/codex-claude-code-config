"""Hook matcher must catch real hook processes and nothing that merely mentions a hooks path."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("w", Path(__file__).resolve().parents[1] / "pc_load_watch.py")
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

HOME = "C:/" + "/".join(("Users", "u"))      # assembled so no literal home path ships in the repo
PY = HOME.replace("/", "\\") + r"\AppData\Local\Python\pythoncore-3.14-64\python.exe"
CFG = HOME + "/.claude/claude-code-config"

CASES = {
    f"{PY} {CFG}/hooks/api-key-leak-detector.py": True,
    f'"{PY}"  {HOME}/.claude/private-hooks/retouch-security-test-router.py': True,
    rf'"C:\Program Files\Git\bin\..\usr\bin\bash.exe" -c "python \"{CFG}/hooks/live-tree-guard.py\""': True,
    f'python "{CFG}/hooks/keyword-skill-router.py" --profile codex': True,
    f'bash -c "cd x; python {CFG}/hooks/a.py && sleep 900"': False,
    f"python -c import time; time.sleep(900) {HOME}/.claude/zz-fake-hooks/neg.py": False,
    "python -m pytest tests/hooks/test_x.py": False,
    r"C:\x\claude.exe --type=renderer": False,
}


def test_hook_matcher():
    assert [c for c, want in CASES.items() if w._is_hook(c) != want] == []


if __name__ == "__main__":
    test_hook_matcher()
    print("ok")
