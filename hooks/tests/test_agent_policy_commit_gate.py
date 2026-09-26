"""agent_policy_gates commit gate: a repo's `commit_checks` run on what `git commit` records.

Driven through stdin like the harness. The check is a stub script that fails when
the judged content contains BAD, so the test covers the gate, not any one tool.
"""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "agent_policy_gates.py"
CHECK = """import subprocess, sys
staged = "--staged" in sys.argv
out = subprocess.run(["git", "diff"] + (["--cached"] if staged else ["HEAD"]),
                     capture_output=True, text=True).stdout
sys.exit(1 if "BAD" in out else 0)
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _hook(repo, command):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(repo),
             "tool_input": {"command": command}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                       capture_output=True, text=True)
    return '"decision"' in r.stdout


def _repo(tmp_path):
    repo = tmp_path / "r"
    (repo / ".github").mkdir(parents=True)
    (repo / "check.py").write_text(CHECK)
    (repo / ".github" / "agent-policy.json").write_text(json.dumps(
        {"commit_checks": [["python", "check.py", "--staged"]]}))
    (repo / "a.txt").write_text("ok\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return repo


def test_staged_bad_change_blocks_commit(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("BAD\n")
    _git(repo, "add", "a.txt")
    assert _hook(repo, 'git commit -m "x"')


def test_clean_staged_change_is_allowed(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("fine\n")
    _git(repo, "add", "a.txt")
    assert not _hook(repo, 'git commit -m "x"')


def test_commit_all_judges_the_working_tree(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("BAD\n")  # not staged: only -a records it
    assert not _hook(repo, 'git commit -m "x"')
    assert _hook(repo, 'git commit -am "x"')


def _gates():
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_policy_gates", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_commit_parsing_review_cases(tmp_path):
    g = _gates()
    inv = lambda c: [(str(t), w) for t, w in g.commit_invocations(c, tmp_path)]  # noqa: E731
    here = str(tmp_path)
    assert inv('git commit -m "x"') == [(here, False)]
    assert inv('git -C "my dir" commit -m x') == [(str(tmp_path / "my dir"), False)]
    assert inv("git --no-pager commit -m x") == [(here, False)]
    assert inv("git -c a=b -C p commit -m x") == [(str(tmp_path / "p"), False)]
    assert inv("git commit f.py -m x") == [(here, True)]      # pathspec records the working tree
    assert inv("git commit -i f.py -m x") == [(here, True)]
    assert inv("git commit -o f.py -m x") == [(here, True)]
    assert inv("git commit -am x") == [(here, True)]
    assert inv("git commit --all -m x") == [(here, True)]
    assert inv('git commit -m "use -a flag"') == [(here, False)]  # -a inside the message is text
    assert inv("git commit -F msg.txt") == [(here, False)]
    assert inv("git commit --dry-run -m x") == []
    assert inv('echo "run git commit later"') == []
    assert inv("git commit-tree HEAD^{tree}") == []
    assert inv("cd x && git commit -m y") == [(str(tmp_path / "x"), False)]
    # review round 2
    assert inv("git add x\ngit commit -m y") == [(here, False)]           # newline separates
    assert inv("git -C C:\\repo\\sub commit -m y") == [(str(Path("C:/repo/sub")), False)]  # not "reposub"
    assert inv("git commit -m x 2>&1") == [(here, False)]                  # redirection is not a path
    assert inv("git commit -m x > out.txt") == [(here, False)]
    assert inv("cd sub; git commit -m y") == [(str(tmp_path / "sub"), False)]
    assert inv("Set-Location sub; git commit -m y") == [(str(tmp_path / "sub"), False)]
    assert inv("env GIT_EDITOR=true git commit -m y") == [(here, False)]
    assert inv("VAR=x git commit -m y") == [(here, False)]


def test_non_commit_commands_are_untouched(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("BAD\n")
    _git(repo, "add", "a.txt")
    assert not _hook(repo, "git status")
    assert not _hook(repo, "git commit-tree HEAD^{tree}")
