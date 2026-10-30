# -*- coding: utf-8 -*-
"""merge-gate-guard: every spelling that must block, and the controls that must pass.

Run: python hooks/tests/test_merge_gate_guard.py   (exit 0 = all pass, 1 = a case failed)
HOOKS_DIR points the test at a copy of hooks/ (mutation_probe.py --dir-env HOOKS_DIR).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

HOOKS = Path(os.environ.get("HOOKS_DIR", Path(__file__).resolve().parents[1]))
SCRIPT = HOOKS / "merge-gate-guard.py"
spec = importlib.util.spec_from_file_location("merge_gate_guard", SCRIPT)
mg = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(HOOKS))
spec.loader.exec_module(mg)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repos(tmp: Path) -> dict[str, Path]:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    (repo / "f").write_text("x", encoding="utf-8")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "init")
    feature = tmp / "feature"
    git(repo, "worktree", "add", "-q", "-b", "feature", str(feature))
    tracking = tmp / "tracking"
    git(repo, "worktree", "add", "-q", "-b", "tracks-master", str(tracking))
    git(repo, "config", "branch.tracks-master.merge", "refs/heads/master")
    git(repo, "config", "branch.tracks-master.remote", "origin")
    git(repo, "config", "alias.pm", "push origin master")
    git(repo, "config", "alias.shpm", "!git push origin HEAD:main")
    git(repo, "config", "alias.pf", "push origin feature")
    develop = tmp / "develop"
    develop.mkdir()
    git(develop, "init", "-q", "-b", "develop")
    git(develop, "config", "user.email", "t@example.invalid")
    git(develop, "config", "user.name", "t")
    (develop / "f").write_text("x", encoding="utf-8")
    git(develop, "add", "f")
    git(develop, "commit", "-q", "-m", "init")
    git(develop, "update-ref", "refs/remotes/origin/develop", "HEAD")
    git(develop, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
    matching = tmp / "matching"
    git(repo, "worktree", "add", "-q", "-b", "other", str(matching))
    return {"repo": repo, "feature": feature, "tracking": tracking, "develop": develop,
            "matching": matching}


# (command, where, powershell)
BLOCK = [
    # gh pr merge, plain and decorated
    ("gh pr merge 5", "feature", False),
    ("gh pr merge 5 --merge --delete-branch", "feature", False),
    ("gh pr merge --auto --squash 5", "feature", False),
    ("gh -R o/r pr merge 5", "feature", False),
    ("gh pr -R o/r merge 5", "feature", False),
    ("gh --repo=o/r pr merge 5", "feature", False),
    # quoting and concatenation
    ('"gh" pr merge 5', "feature", False),
    ("g'h' pr merge 5", "feature", False),
    ('gh "pr" "merge" 5', "feature", False),
    ("gh pr\\\n merge 5", "feature", False),
    # paths and .exe
    ("/usr/bin/gh pr merge 5", "feature", False),
    ('"C:/Program Files/GitHub CLI/gh.exe" pr merge 5', "feature", False),
    # env prefixes and wrappers
    ("GH_TOKEN=abc gh pr merge 5", "feature", False),
    ("env GH_DEBUG=1 gh pr merge 5", "feature", False),
    ("sudo -E gh pr merge 5", "feature", False),
    ("timeout 60 gh pr merge 5", "feature", False),
    ("nohup gh pr merge 5 &", "feature", False),
    ("command gh pr merge 5", "feature", False),
    ("echo 5 | xargs gh pr merge", "feature", False),
    ("find . -maxdepth 0 -exec gh pr merge 5 \\;", "feature", False),
    # chains and substitution
    ("git status && gh pr merge 5", "feature", False),
    ("true; gh pr merge 5", "feature", False),
    ("echo $(gh pr merge 5)", "feature", False),
    ("echo `gh pr merge 5`", "feature", False),
    ('git commit -m "$(gh pr merge 5)"', "feature", False),
    # carriers
    ("ssh host 'gh pr merge 5'", "feature", False),
    ("ssh -p 22 host gh pr merge 5", "feature", False),
    ("bash -c 'gh pr merge 5'", "feature", False),
    ("sh -c \"cd /x && gh pr merge 5\"", "feature", False),
    ("eval 'gh pr merge 5'", "feature", False),
    ("echo 'gh pr merge 5' | bash", "feature", False),
    ("cmd /c \"gh pr merge 5\"", "feature", False),
    ("pwsh -Command \"gh pr merge 5\"", "feature", False),
    ("python -c \"import subprocess; subprocess.run(['gh','pr','merge','5'])\"", "feature", False),
    ("node -e \"require('child_process').execSync('gh pr merge 5')\"", "feature", False),
    ("alias m='gh pr merge'; m 5", "feature", False),
    ("x=gh; $x pr merge 5", "feature", False),
    ('"$GH" pr merge 5', "feature", False),
    # gh api / http merges and ref moves
    ("gh api -X PUT repos/o/r/pulls/5/merge", "feature", False),
    ("gh api repos/o/r/merges -f base=master -f head=x", "feature", False),
    ("gh api graphql -f query='mutation{mergePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'", "feature", False),
    ("gh api graphql -f query='mutation{enablePullRequestAutoMerge(input:{}){clientMutationId}}'", "feature", False),
    ("gh api -X PATCH repos/o/r/git/refs/heads/master -f sha=abc", "feature", False),
    ("curl -X PUT -H 'Authorization: token x' https://api.github.com/repos/o/r/pulls/5/merge", "feature", False),
    ("gh alias set m 'pr merge'", "feature", False),
    # git push to protected names
    ("git push origin master", "feature", False),
    ("git push origin main", "feature", False),
    ("git push origin HEAD:master", "feature", False),
    ("git push origin HEAD:refs/heads/main", "feature", False),
    ("git push origin +master", "feature", False),
    ("git push --force origin master", "feature", False),
    ("git push -f origin feature:master", "feature", False),
    ("git push origin :main", "feature", False),
    ("git push origin --delete master", "feature", False),
    ("git push --all origin", "feature", False),
    ("git push --mirror origin", "feature", False),
    ("git push origin 'refs/heads/*:refs/heads/*'", "feature", False),
    ("git push origin feature master", "feature", False),
    ("git push --repo=origin master", "feature", False),
    ("git push origin MASTER", "feature", False),
    ("git -C ../repo push origin master", "feature", False),
    ("git -c push.default=current push origin master", "feature", False),
    ("git --no-pager push origin master", "feature", False),
    ('"C:/Program Files/Git/cmd/git.exe" push origin master', "feature", False),
    ("GIT_TRACE=1 git push origin master", "feature", False),
    # refspec-less pushes whose target is protected
    ("git push", "repo", False),
    ("git push origin", "repo", False),
    ("git push -u origin", "repo", False),
    ("git push origin HEAD", "repo", False),
    ("git push", "tracking", False),
    ("cd ../repo && git push", "feature", False),
    # default branch learned from the remote HEAD
    ("git push origin develop", "develop", False),
    # aliases
    ("git pm", "feature", False),
    ("git shpm", "feature", False),
    ("git -c alias.zz='push origin master' zz", "feature", False),
    ("git -c alias.zz='!git push origin main' zz", "feature", False),
    # remote host: refspec-less cannot be resolved -> blocked, explicit protected -> blocked
    ("ssh host 'cd /srv/x && git push'", "feature", False),
    ("ssh host git push origin main", "feature", False),
    # PowerShell
    ("gh pr merge 5", "feature", True),
    ("& \"C:\\Program Files\\GitHub CLI\\gh.exe\" pr merge 5", "feature", True),
    ("Start-Process gh -ArgumentList 'pr','merge','5'", "feature", True),
    ("Start-Process gh -ArgumentList \"pr merge 5\"", "feature", True),
    ("Invoke-Expression 'gh pr merge 5'", "feature", True),
    ("iex \"gh pr merge 5\"", "feature", True),
    ("git push origin master", "feature", True),
    ("Invoke-RestMethod -Method Put -Uri https://api.github.com/repos/o/r/pulls/5/merge", "feature", True),
    ("$g = 'gh'; & $g pr merge 5", "feature", True),
    # independent review, round 1: forms the first version missed
    ("gh api -X PUT repos/{owner}/{repo}/pulls/5/merge", "feature", False),
    ("gh api -X PATCH repos/{owner}/{repo}/git/refs/heads/master -f sha=x", "feature", False),
    ("gh api --method PUT repos/{owner}/{repo}/pulls/5/merge", "feature", False),
    ("gh api --method=PUT repos/o/r/pulls/5/merge", "feature", False),
    ("git -C $(git rev-parse --show-toplevel) push origin master", "feature", False),
    ("git push $(git remote | head -1) master", "feature", False),
    ("git push origin `git branch --show-current`:master", "feature", False),
    ("git push origin $(git rev-parse --abbrev-ref HEAD):master", "feature", False),
    ("BR=master; git push origin $BR", "feature", False),
    ("BR=master git push origin $BR", "feature", False),
    ("git push origin ${BR:-master}", "feature", False),
    ('git push origin "$(echo master)"', "feature", False),
    ("git push origin $UNSET_BRANCH_FOR_TEST", "feature", False),
    ("git -c push.default=matching push", "repo", False),
    ("git -c remote.origin.push=HEAD:master push", "feature", False),
    ("git -c remote.origin.push=refs/heads/*:refs/heads/* push", "feature", False),
    ("gh api -X PUT repos/o/r/contents/f -f message=m -f content=eA==", "feature", False),
    ("gh api -X PUT repos/o/r/contents/f -f message=m -f content=eA== -f branch=main", "feature", False),
    ("gh api graphql -f query='mutation{createCommitOnBranch(input:{}){commit{oid}}}'", "feature", False),
    ("gh api graphql -f query='mutation{enqueuePullRequest(input:{}){clientMutationId}}'", "feature", False),
    ("gh api -X POST repos/o/r/git/refs -f ref=refs/heads/master -f sha=x", "feature", False),
    ("gh api -X PATCH repos/o/r -f default_branch=x", "feature", False),
    ("gh repo sync o/r --force", "feature", False),
    ("git send-pack origin master", "feature", False),
    ("git push origin feature:heads/master", "feature", False),
    ("Push-Location ..\\repo; git push", "feature", True),
    ("$a=@('pr','merge','5'); gh @a", "feature", True),
    ("Start-Process -FilePath gh -ArgumentList @('pr','merge','5')", "feature", True),
    ("& (Get-Command gh) pr merge 5", "feature", True),
    ("& (Get-Command git) push origin master", "feature", True),
    ("curl -d '{}' https://api.github.com/repos/o/r/merges", "feature", False),
    ("curl --request PUT https://api.github.com/repos/o/r/pulls/5/merge", "feature", False),
    ("bash <<'EOF'\ngh pr merge 5\nEOF", "feature", False),
    ("ssh host <<EOF\ngit push origin main\nEOF", "feature", False),
    ("x=$(gh pr merge 5)", "feature", False),
    ("(cd ../repo && git push origin master)", "feature", False),
    ("{ gh pr merge 5; }", "feature", False),
    ("echo y | gh pr merge 5", "feature", False),
    ("echo 'gh pr merge 5' | sh -s", "feature", False),
    ("Write-Output 'gh pr merge 5' | Invoke-Expression", "feature", True),
    # independent review, round 2
    ("cat <<EOF | bash\ngh pr merge 5\nEOF", "feature", False),
    ("cat <<'EOF' | sh\ngit push origin master\nEOF", "feature", False),
    ("cat <<'EOF' | tee x | bash\ngit push origin master\nEOF", "feature", False),
    ("printf 'git push origin master\\n' | bash", "feature", False),
    ("python - <<'EOF'\nimport subprocess\nsubprocess.run(['gh','pr','merge','5'])\nEOF", "feature", False),
    ("git push origin \"$(git branch --show-current)\"", "repo", False),
    ("BR=$(git branch --show-current); git push origin \"$BR\"", "repo", False),
    ("git push origin HEAD:`git rev-parse --abbrev-ref HEAD`", "repo", False),
    ("git checkout master && git push", "feature", False),
    ("git switch main; git push origin HEAD", "feature", False),
    ("gh api graphql -F query=@m.graphql", "feature", False),
    ("gh api graphql --input q.json", "feature", False),
    ("gh api graphql -f query=\"$(cat m.graphql)\"", "feature", False),
    ("$a=@('push','origin','master'); git @a", "feature", True),
    ("Start-Process -FilePath git -ArgumentList 'push origin master'", "feature", True),
    ("$gh=(Get-Command gh).Source; & $gh pr merge 5", "feature", True),
    ("gh api -X PUT repos/o/r/contents/f -f message=m -f content=eA== -f branch=$BR_UNSET_X", "feature", False),
    ("gh api -X POST repos/o/r/branches/feat/rename -f new_name=master", "feature", False),
    ("gh api -X POST repos/o/r/merge-upstream -f branch=master", "feature", False),
    ("git push origin ma$UNSET_X", "feature", False),
    # independent review, round 3
    ("$b = git branch --show-current; git push origin $b", "repo", True),
    ("$env:BR='master'; git push origin $env:BR", "feature", True),
    ("gh api graphql -f query=$QUERY_UNSET", "feature", False),
    ("git checkout feature && git checkout master && git push", "feature", False),
    # independent review, round 4: faking a feature branch while on master
    ("git checkout feature || true; git push", "repo", False),
    ("git checkout feature & git push", "repo", False),
    ("git -C ../feature checkout feature; git push", "repo", False),
    ("git checkout -p feature && git push", "repo", False),
    ("git checkout -t origin/master -b x && git push", "repo", False),
    ("git checkout --track=direct -b x && git push", "repo", False),
    ("git checkout -t origin/master -b x && git push", "feature", False),
    ("git checkout -b feat9 master && git push origin HEAD:master", "repo", False),
    ("git checkout -b && git push", "feature", False),
    ("git checkout -b master2 -b master && git push origin HEAD", "feature", False),
    ("git push origin \"${X_UNSET}/main\"", "feature", False),
    ("gh api graphql -f query=\"mutation{${M}(input:{})}\"", "feature", False),
    ("gh api graphql -f query=\"{x} $(cat m.graphql)\"", "feature", False),
]

ALLOW = [
    ("git push origin feature", "feature", False),
    ("git push -u origin feature", "feature", False),
    ("git push --force-with-lease origin feature", "feature", False),
    ("git push", "feature", False),
    ("git push origin HEAD", "feature", False),
    ("git push origin feature:feature-2", "feature", False),
    ("git push --tags origin", "feature", False),
    ("git push origin refs/tags/v1.0", "feature", False),
    ("git push origin 'refs/tags/*'", "feature", False),
    ("git push --dry-run origin master", "feature", False),
    ("git push origin mastermind", "feature", False),
    ("git push origin master-fix", "feature", False),
    ("git push origin feature/main-page", "feature", False),
    ("git pf", "feature", False),
    ("git commit -m 'gh pr merge is now gated'", "feature", False),
    ("git commit -m 'never git push origin master'", "feature", False),
    ("git log --grep 'pr merge' --oneline", "feature", False),
    ("git merge --no-ff feature", "feature", False),
    ("git pull origin master", "feature", False),
    ("git fetch origin master", "feature", False),
    ("git checkout master", "feature", False),
    ("gh pr view 5 --json mergeable,mergeStateStatus", "feature", False),
    ("gh pr checks 5", "feature", False),
    ("gh pr update-branch 5", "feature", False),
    ("gh pr create --title 'merge gate' --body 'after this, gh pr merge is blocked'", "feature", False),
    ("gh pr comment 360 --body-file note.md", "feature", False),
    ("gh api repos/o/r/pulls/5", "feature", False),
    ("gh run list --branch master", "feature", False),
    ("grep -rn 'gh pr merge' docs", "feature", False),
    ("rg 'git push origin master' .", "feature", False),
    ("python ~/.claude/claude-code-config/scripts/safe_merge.py o/r 5", "feature", False),
    ("python scripts/safe_merge.py o/r 5 && gh pr view 5 --json state", "feature", False),
    ("ls -la", "feature", False),
    ("echo pushing feature", "feature", False),
    ("ssh host 'cd /srv/x && git push origin feature'", "feature", False),
    ("ssh host git pull origin main", "feature", False),
    ("Get-ChildItem", "feature", True),
    ("git push origin feature", "feature", True),
    ("Select-String -Path x -Pattern 'gh pr merge'", "feature", True),
    # independent review, round 1: false blocks on ordinary work
    ("gh api repos/o/r/git/refs/heads/master", "feature", False),
    ("gh api repos/o/r/git/refs/heads/master --jq .object.sha", "feature", False),
    ("gh api repos/o/r/pulls/5/merge", "feature", False),
    ("gh api -X GET repos/o/r/pulls/5/merge", "feature", False),
    ("curl -s https://api.github.com/repos/o/r/pulls/5/merge", "feature", False),
    ("gh api -X PUT repos/o/r/contents/f -f message=m -f content=eA== -f branch=feature", "feature", False),
    ("git commit -m \"$(cat <<'EOF'\nmerge gate: gh pr merge and git push origin master are blocked\nEOF\n)\"", "feature", False),
    ("gh pr create --title t --body \"$(cat <<'EOF'\nafter this, gh pr merge is blocked\nEOF\n)\"", "feature", False),
    ("cat > notes.md <<'EOF'\nrun gh pr merge only through safe_merge\nEOF", "feature", False),
    ("echo 'gh pr merge 5'", "feature", False),
    ("printf '%s\\n' 'git push origin master'", "feature", False),
    ("echo 'gh pr merge 5' | grep merge", "feature", False),
    ("Write-Host \"gh pr merge 5\"", "feature", True),
    ("gh pr merge --help", "feature", False),
    ("git push --help", "feature", False),
    ("gh repo sync", "feature", False),
    ("gh api repos/{owner}/{repo}/pulls --jq '.[].number'", "feature", False),
    ("BR=feature; git push origin $BR", "feature", False),
    ("git push origin \"${BR_FOR_TEST}\"", "feature", False),
    ("git -c push.default=current push", "feature", False),
    ("find . -name '*.py' -exec grep -l merge {} \\;", "feature", False),
    ("Get-Content x | Select-String push", "feature", True),
    # independent review, round 2: the current-branch idiom and other ordinary work
    ("git push origin \"$(git branch --show-current)\"", "feature", False),
    ("git push -u origin \"$(git rev-parse --abbrev-ref HEAD)\"", "feature", False),
    ("BR=$(git branch --show-current); git push origin \"$BR\"", "feature", False),
    ("git push origin HEAD:$(git symbolic-ref --short HEAD)", "feature", False),
    ("git push origin \"$(git branch --show-current)\"", "feature", True),
    ("for b in a b; do git push origin feature-$b; done", "feature", False),
    ("gh repo sync --branch feature", "feature", False),
    ("gh api graphql -f query='query{viewer{login}}'", "feature", False),
    ("git checkout -b feature-2 && git push -u origin feature-2", "feature", False),
    ("cat <<'EOF' | grep merge\ngh pr merge 5\nEOF", "feature", False),
    # independent review, round 3
    ("gh api graphql -F owner=o -f query='query($owner:String!){repository(owner:$owner,name:\"r\"){id}}'",
     "feature", False),
    ("gh api graphql --paginate -f query='query($endCursor:String){viewer{repositories(after:$endCursor){nodes{name}}}}'",
     "feature", False),
    ("git checkout -b feat2 && git push -u origin HEAD", "feature", False),
    ("git switch -c feat2 && git push -u origin \"$(git branch --show-current)\"", "feature", False),
    ("git push origin \"$USER/feature\"", "feature", False),
    ("$b = git branch --show-current; git push origin $b", "feature", True),
    ("git push origin \"$USER/main-page-fix\"", "feature", False),
    ("git checkout feature && git push", "repo", False),
    ("git checkout -b feat9 master && git push origin HEAD", "repo", False),
    ("git checkout -p master && git push", "feature", False),
    ("git -C ../repo checkout master; git push", "feature", False),
]


def hook_run(command: str, cwd: Path, powershell: bool) -> tuple[int, str]:
    event = {"hook_event_name": "PreToolUse", "tool_name": "PowerShell" if powershell else "Bash",
             "tool_input": {"command": command}, "cwd": str(cwd)}
    out = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(event),
                         capture_output=True, text=True, timeout=60)
    return out.returncode, out.stdout


UNRESOLVED_MSG = ("the destination is a variable or substitution this hook cannot resolve "
                  "(write the branch name literally)")


class FakeGit:
    """The repositories of make_repos(), answered from memory so no git process starts."""

    def __init__(self) -> None:
        self.config = {
            "alias.pm": "push origin master", "alias.shpm": "!git push origin HEAD:main",
            "alias.pf": "push origin feature", "branch.tracks-master.merge": "refs/heads/master",
        }
        self.dev_config: dict[str, str] = {}
        self.heads = {"repo": "master", "feature": "feature", "tracking": "tracks-master",
                      "matching": "other", "develop": "develop"}
        self.branches = ["feature", "master", "other", "tracks-master"]

    def root(self, name: str) -> Path:
        return Path(os.path.normpath(f"/fakegit/{name}"))

    def __call__(self, cwd, *args):
        if cwd is None:
            return None
        name = {str(self.root(k)): k for k in self.heads}.get(os.path.normpath(str(cwd)))
        if name is None:
            return None
        config = self.dev_config if name == "develop" else self.config
        if args == ("rev-parse", "--git-dir"):
            return ".git"
        if args[:3] == ("rev-parse", "--verify", "--quiet"):
            return "0" * 40 if args[3][len("refs/heads/"):] in self.branches else None
        if args == ("symbolic-ref", "-q", "--short", "HEAD"):
            return self.heads[name]
        if args[:3] == ("symbolic-ref", "-q", "--short"):
            return "origin/develop" if name == "develop" and args[3] == "refs/remotes/origin/HEAD" else None
        if args[:2] == ("config", "--get-all"):
            # multi-valued only for push refspecs; everything else must be read with --get
            assert args[2].startswith("remote."), f"FakeGit: --get-all for {args[2]}"
            return config.get(args[2])
        if args[:2] == ("config", "--get"):
            assert not args[2].startswith("remote."), f"FakeGit: --get for multi-valued {args[2]}"
            return config.get(args[2])
        if args[0] == "for-each-ref":
            return "\n".join(["develop"] if name == "develop" else self.branches)
        raise AssertionError(f"FakeGit: unexpected git call {args}")


def unit(failures: list[str]) -> None:
    """Exact answers of the building blocks: tokenizer, expansion, write detection, finders."""

    def eq(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    def toks(text, ps=False):
        return [s["tokens"] for s in mg.split_commands(text, ps)]

    def seps(text, ps=False):
        return [s["sep"] for s in mg.split_commands(text, ps)]

    # tokenizer
    eq("plain", toks("a b  c"), [["a", "b", "c"]])
    eq("separators", seps("a && b || c | d ; e & f\ng"), ["&&", "||", "|", ";", "&", "\n", None])
    eq("separator tokens", toks("a&&b||c|d;e&f"), [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]])
    eq("empty segment keeps the first separator", seps("a ; ; b"), [";", None])
    eq("empty segment adopts a separator", seps("a\n;b"), ["\n", None])
    eq("single quotes", toks("echo 'a b' 'c\"d'"), [["echo", "a b", 'c"d']])
    eq("double quotes and escapes", toks('echo "a \\" b" x\\ y'), [["echo", 'a " b', "x y"]])
    eq("trailing escape is literal", toks("a\\"), [["a\\"]])
    eq("line continuation", toks("a \\\nb"), [["a", "b"]])
    eq("powershell doubled quote", toks("echo 'it''s'", True), [["echo", "it's"]])
    eq("powershell backtick escape", toks('echo "a`"b" x`y', True), [["echo", 'a"b', "xy"]])
    eq("powershell keeps backslash", toks("C:\\x\\gh.exe pr", True), [["C:\\x\\gh.exe", "pr"]])
    eq("powershell backtick continuation", toks("a `\nb", True), [["a", "b"]])
    eq("bash backslash escape", toks("a\\;b"), [["a;b"]])
    eq("substitution stays in its word", toks("git -C $(git rev-parse --top) push"),
       [["git", "-C", "$(git rev-parse --top)", "push"]])
    eq("nested substitution", toks("x$(a $(b) 'c)' d)y z"), [["x$(a $(b) 'c)' d)y", "z"]])
    eq("unterminated substitution", toks("a $(b c"), [["a", "$(b c"]])
    eq("braced variable", toks("echo ${A:-b c} d"), [["echo", "${A:-b c}", "d"]])
    eq("at-paren is literal in bash", toks("a @(b) c"), [["a", "@(b"], ["c"]])
    eq("powershell array", toks("gh @('pr','merge')", True), [["gh", "@('pr','merge')"]])
    eq("powershell subexpression", toks("x $(gh pr) y", True), [["x", "$(gh pr)", "y"]])
    eq("backtick substitution", toks("a `b c` d"), [["a", "`b c`", "d"]])
    eq("unterminated backtick", toks("a `b c"), [["a", "`b c"]])
    eq("subshell parens", toks("(cd x && y)"), [["cd", "x"], ["y"]])
    eq("paren inside a word", toks("f(x) y"), [["f(x"], ["y"]])
    eq("braces as a group", toks("{ a; } b"), [["a"], ["b"]])
    eq("brace inside a word", toks("repos/{owner}/{repo}/x"), [["repos/{owner}/{repo}/x"]])
    eq("comment", toks("a # b c\nd"), [["a"], ["d"]])
    eq("hash inside a word", toks("a#b c"), [["a#b", "c"]])
    eq("hash inside quotes", toks("'#x' y"), [["#x", "y"]])
    segs = mg.split_commands("cat <<'EOF' > f\nline gh pr merge\n  EOF\nEOF\nnext x")
    eq("heredoc tokens", [s["tokens"] for s in segs], [["cat", ">", "f"], ["next", "x"]])
    eq("heredoc body", segs[0]["heredocs"], ["line gh pr merge\n  EOF"])
    segs = mg.split_commands("cat <<-END\n\tbody\n\tEND\nz")
    eq("tab-stripped heredoc", (segs[0]["heredocs"], segs[-1]["tokens"]), (["\tbody"], ["z"]))
    segs = mg.split_commands("cat <<EOF\nno end")
    eq("unterminated heredoc", segs[0]["heredocs"], ["no end"])
    segs = mg.split_commands("cat <<EOF")
    eq("heredoc without a body", segs[0]["heredocs"], [""])
    eq("here-string is not a heredoc", toks("cat <<<word x"), [["cat", "<<<word", "x"]])
    eq("here-string marker alone", toks("cat <<< x"), [["cat", "<<<", "x"]])
    eq("a group closed before a newline", seps("x; { a }\nb"), [";", "\n", None])
    eq("trailing escape in open double quotes", toks('echo "a\\'), [["echo", "a\\"]])
    eq("a lone dollar", toks("echo $"), [["echo", "$"]])
    eq("substitution after a close paren", toks("x)$(y) z"), [["x"], ["$(y)", "z"]])
    eq("braced capture closes on a brace", toks("a ${x)} b"), [["a", "${x)}", "b"]])
    eq("heredoc then more lines", [s["tokens"] for s in mg.split_commands("cat <<E\nl1\nE\nnext x\nlast")],
       [["cat"], ["next", "x"], ["last"]])
    eq("heredoc marker without a delimiter", toks("a << b"), [["a"]])
    eq("heredoc in powershell is text", toks("a <<EOF", True), [["a", "<<EOF"]])
    eq("_capture", (mg._capture("$(a(b)c)d", 0), mg._capture("x$(a ')' b", 1), mg._capture("${a}b", 0)),
       (8, 10, 4))
    eq("_capture unterminated", mg._capture("$(a", 0), 3)

    # names
    eq("_base", [mg._base(x) for x in ("/usr/bin/gh", '"C:\\x\\GH.EXE"', "`git", "$(gh", "gh)")],
       ["gh", "gh", "git", "gh", "gh"])
    eq("_variable_like", [mg._variable_like(x) for x in ("$x", "%x%", "@a", "x%", "x")],
       [True, True, True, True, False])
    eq("_primary_index", [mg._primary_index(t) for t in (
        ["gh"], ["A=1", "gh"], ["sudo", "-E", "gh"], ["timeout", "-k", "1", "5", "gh"],
        ["timeout", "-s", "KILL", "--foreground", "5", "gh"], ["timeout", "5", "gh"],
        ["env", "A=1", "gh"], ["-x"], [], ["ls", "-la"], ["timeout", "5"])],
       [0, 1, 2, 4, 5, 2, 2, 0, 0, 0, 2])
    eq("_short", [mg._short(x) for x in ("+refs/heads/Main", "heads/master", "refs/tags/v1", " x ")],
       ["main", "master", "refs/tags/v1", "x"])
    eq("_split_args", mg._split_args(["@('pr','merge')", "a b", "", "x,y"]), ["pr", "merge", "a", "b", "x", "y"])

    # variables
    ctx = mg.Ctx(None, variables={"BR": "main"})
    eq("expand known", mg.expand("x$BR-${BR}", ctx), ("xmain-main", True))
    eq("expand env", mg.expand("$BR_FOR_TEST", ctx), ("feature", True))
    eq("expand powershell env", mg.expand("$env:BR_FOR_TEST", ctx), ("feature", True))
    eq("expand unknown", mg.expand("$UNSET_BRANCH_FOR_TEST", ctx), ("$UNSET_BRANCH_FOR_TEST", False))
    eq("expand default form", mg.expand("${BR:-x}", ctx), ("${BR:-x}", False))
    eq("expand substitution", [mg.expand(x, ctx)[1] for x in ("$(a)", "`a`", "@(a)")], [False] * 3)
    eq("expand splat", mg.expand("@BR", ctx), ("main", True))
    eq("expand plain", mg.expand("master", ctx), ("master", True))
    eq("remote ignores local env", mg.expand("$BR_FOR_TEST", mg.Ctx(None, remote=True)),
       ("$BR_FOR_TEST", False))
    ctx = mg.Ctx(None)
    eq("bash assignment", (mg._assignment(["A=1", "B=$A"], ctx), ctx.vars), (True, {"A": "1", "B": "1"}))
    ctx = mg.Ctx(None)
    eq("powershell assignment", (mg._assignment(["$a", "=", "@('pr','merge')"], ctx), ctx.vars),
       (True, {"a": "pr merge"}))
    ctx = mg.Ctx(None)
    eq("powershell assignment without spaces", (mg._assignment(["$g='gh'"], ctx), ctx.vars),
       (True, {"g": "gh"}))
    ctx = mg.Ctx(None)
    eq("not assignments", [mg._assignment(t, ctx) for t in (["A=1", "gh"], ["$a", "-eq", "1"],
                                                           ["$a.b", "=", "1"], [], ["gh"])],
       [False] * 5)
    eq("no vars recorded", ctx.vars, {})
    child = mg.Ctx(Path("x"), variables={"A": "1"}).child(remote=True)
    eq("child copies", (child.cwd, child.remote, child.depth, child.vars), (Path("x"), True, 1, {"A": "1"}))

    # HTTP writes
    eq("_is_write", [mg._is_write(a) for a in (
        ["-X", "PUT", "u"], ["-XPOST", "u"], ["--method=patch", "u"], ["--method", "delete"],
        ["--request", "PUT"], ["-Method", "Put"], ["-Method:Post"], ["-X", "GET", "-f", "a=1"],
        ["-f", "a=1"], ["-F", "a=1"], ["--input", "f"], ["-d", "{}"], ["--json", "{}"],
        ["-Body", "x"], ["u"], ["-X"], ["-X", "HEAD"], ["-H", "Accept: x"])],
       [True] * 7 + [False] + [True] * 6 + [False] * 4)
    eq("_http_finding", [mg._http_finding(a) for a in (
        ["graphql", "-f", "query=mutation{mergePullRequest(input:{})}"],
        ["-X", "PUT", "repos/o/r/pulls/5/merge"], ["repos/o/r/pulls/5/merge"],
        ["-X", "POST", "repos/o/r/git/refs", "-f", "ref=refs/heads/main"],
        ["-X", "POST", "repos/o/r/git/refs", "-f", "ref=refs/heads/feat"],
        ["-X", "PUT", "repos/o/r/contents/a", "-f", "branch=feat"],
        ["-X", "PUT", "repos/o/r/contents/a", "-f", "branch=master"],
        ["-X", "PATCH", "repos/o/r", "-f", "default_branch=x"],
        ["-X", "PATCH", "repos/o/r", "-f", "description=x"])],
       ["GitHub GraphQL mutation that merges or moves a branch", "HTTP write to a GitHub merge/ref endpoint",
        None, "HTTP write creating a protected ref", None, None,
        "HTTP contents write onto the default branch", "HTTP write changing the default branch", None])
    eq("a bare key=value is not a field", mg._http_finding(["-X", "POST", "repos/o/r/git/refs", "ref=refs/heads/main"]),
       None)
    eq("a trailing -f", mg._http_finding(["-X", "POST", "repos/o/r/git/refs", "-f"]), None)
    eq("rename to a feature name", mg._http_finding(["-X", "POST", "repos/o/r/branches/x/rename", "-f",
                                                      "new_name=feat2"]), None)

    # gh
    ctx = mg.Ctx(None)
    eq("gh_finding", [mg.gh_finding(a, ctx) for a in (
        ["pr", "merge", "5"], ["-R", "o/r", "pr", "merge"], ["pr", "view", "merge"], ["pr"], [],
        ["repo", "sync", "o/r"], ["repo", "sync"], ["api", "-X", "PUT", "repos/o/r/pulls/1/merge"],
        ["api", "repos/o/r/pulls/1/merge"], ["alias", "set", "m", "pr merge"], ["alias", "list"],
        ["pr", "merge", "--help"], ["--repo", "x", "pr", "merge"], ["status", "merge"])],
       ["gh pr merge", "gh pr merge", None, None, None, "gh repo sync of a remote repository", None,
        "HTTP write to a GitHub merge/ref endpoint", None, "gh alias that merges", None, None,
        "gh pr merge", None])

    # gh aliases from the config file
    with tempfile.TemporaryDirectory() as cfg:
        Path(cfg, "config.yml").write_text(
            "  lead: pr merge\ngit_protocol: https\naliases:\n    mm: pr merge\n    sh: '!gh pr merge $1'\n"
            "    co: pr checkout\n    p: pr\n    # note: x\n\nx\n  stray: pr merge\n", encoding="utf-8")
        saved = {k: os.environ.get(k) for k in ("GH_CONFIG_DIR", "XDG_CONFIG_HOME", "APPDATA")}
        os.environ["GH_CONFIG_DIR"] = cfg
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ.pop("APPDATA", None)
        try:
            eq("_gh_aliases", {k: v for k, v in mg._gh_aliases().items() if k in ("mm", "sh", "co", "stray", "lead")},
               {"mm": "pr merge", "sh": "!gh pr merge $1", "co": "pr checkout"})
            eq("gh alias findings", [mg.gh_finding(a, mg.Ctx(None)) for a in (
                ["mm", "5"], ["sh", "5"], ["co", "5"], ["p", "merge", "5"], ["-R", "o/r", "p", "merge"])],
               ["gh alias mm -> gh pr merge", "gh alias sh -> gh pr merge", None,
                "gh alias p -> gh pr merge", "gh alias p -> gh pr merge"])
            eq("gh alias depth", mg.gh_finding(["mm"], mg.Ctx(None, depth=mg.MAX_DEPTH)), None)
            os.environ.pop("GH_CONFIG_DIR")
            os.environ["XDG_CONFIG_HOME"] = str(Path(cfg).parent)
            Path(cfg).parent.joinpath("gh").mkdir(exist_ok=True)
            Path(cfg).parent.joinpath("gh", "config.yml").write_text("aliases:\n  xx: pr merge\n", encoding="utf-8")
            eq("XDG gh config", mg._gh_aliases().get("xx"), "pr merge")
            os.environ.pop("XDG_CONFIG_HOME")
            os.environ["APPDATA"] = cfg
            Path(cfg, "GitHub CLI").mkdir()
            Path(cfg, "GitHub CLI", "config.yml").write_text("aliases:\n  yy: pr merge\n", encoding="utf-8")
            eq("APPDATA gh config", mg._gh_aliases().get("yy"), "pr merge")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(Path(cfg).parent / "gh", ignore_errors=True)

    # git push
    world = FakeGit()
    real_git = mg._git
    mg._git = world
    try:
        feat = mg.Ctx(world.root("feature"))
        eq("_refspec_destinations", [mg._refspec_destinations(s, feat) for s in (
            "HEAD", "@", "HEAD:main", "+x:refs/heads/Main", "x:", "x", "$(b):master", "x:${B:-main}",
            "x:feat-$B", "x:ma$B", "$(git branch --show-current)", "x:$U/feature", "x:$U-ter", "x:$Uster")],
           [["feature"], ["feature"], ["main"], ["main"], ["x"], ["x"], ["master"], UNRESOLVED_MSG, ["feat-$"],
            UNRESOLVED_MSG, ["feature"], ["$/feature"], ["$-ter"], UNRESOLVED_MSG])
        eq("HEAD remote", mg._refspec_destinations("HEAD", mg.Ctx(None, remote=True)),
           "HEAD on a remote host cannot be resolved")
        eq("HEAD unresolvable", mg._refspec_destinations("HEAD", mg.Ctx(None)),
           "HEAD is not a resolvable branch here")
        eq("push_finding", [mg.push_finding(a, feat) for a in (
            ["origin", "master"], ["origin", "feature"], ["--repo", "origin", "master"],
            ["--repo=origin", "main"], ["origin", "--", "master"], ["-u", "origin", "main"],
            ["--all"], ["--branches"], ["--mirror", "o"], ["-n", "origin", "master"],
            ["--delete", "origin", "main"], ["-d", "origin", "feature"], ["origin", ":master"],
            ["--tags"], ["origin", "refs/heads/*:refs/heads/*"], ["origin", "refs/tags/*"],
            ["-o", "ci.skip", "origin", "master"], ["origin", "a", "main"], ["--delete", "origin"],
            ["origin", "--force-with-lease", "feature"], [], ["origin"])],
           ["git push to master", None, "git push to master", "git push to main", "git push to master",
            "git push to main", "git push --all (includes the default branch)",
            "git push --branches (includes the default branch)", "git push --mirror (includes the default branch)",
            None, "git push to main", None, "git push to master", None,
            "git push glob refspec refs/heads/*:refs/heads/* (can reach the default branch)", None,
            "git push to master", "git push to main", None, None, None, None])
        eq("tags and deletes from master push no branch",
           [mg.push_finding(a, mg.Ctx(world.root("repo"))) for a in (["--tags"], ["origin", "--delete"])],
           [None, None])
        dev, master_repo = mg.Ctx(world.root("develop")), mg.Ctx(world.root("repo"))
        eq("remote default without a named remote", mg.push_finding([], dev),
           "git push to develop (from the current branch)")
        eq("--repo forms name the remote", [mg.push_finding(a, dev) for a in (
            ["--repo=origin", "develop"], ["--repo", "origin", "develop"], ["-o", "x", "origin", "develop"])],
           ["git push to develop"] * 3)
        eq("--repo as the last word", mg.push_finding(["--repo"], master_repo),
           "git push to master (from the current branch)")
        eq("--repo value is not a refspec", mg.push_finding(["--repo", "origin"], master_repo),
           "git push to master (from the current branch)")
        eq("-- then a refspec", [mg.push_finding(a, feat) for a in (["origin", "--", "main"], ["--", "origin", "x"])],
           ["git push to main", None])
        eq("argument list as one word", mg.git_finding(["push origin"], master_repo),
           "git push to master (from the current branch)")
        eq("-C without a starting directory", mg.git_finding(["-C", world.root("repo").as_posix(), "push"],
                                                             mg.Ctx(None)),
           "git push to master (from the current branch)")
        eq("ssh push is judged as remote", mg.scan_text("ssh h git push", master_repo),
           "over ssh: git push without a refspec: a push without a refspec on a remote host cannot be "
           "resolved (push `git push <remote> <feature-branch>`)")
        eq("builtin cd", mg.scan_text("builtin cd ../repo && git push", mg.Ctx(world.root("feature"))),
           "git push to master (from the current branch)")
        eq("a push named in code is judged as remote",
           mg.scan_text("python -c \"os.system('git push')\"", master_repo), None)
        eq("a variable program deep in a command",
           mg.scan_text("find . -exec $g push origin main ;", mg.Ctx(None)),
           "a variable standing for git: git push to main")
        eq("push from master", mg.push_finding([], mg.Ctx(world.root("repo"))),
           "git push to master (from the current branch)")
        eq("push from tracking", mg.push_finding(["origin"], mg.Ctx(world.root("tracking"))),
           "git push to master (from the current branch)")
        eq("push to the remote default", mg.push_finding(["origin", "develop"], mg.Ctx(world.root("develop"))),
           "git push to develop")
        eq("push remote unresolved", mg.push_finding([], mg.Ctx(None, remote=True)),
           "git push without a refspec: a push without a refspec on a remote host cannot be resolved "
           "(push `git push <remote> <feature-branch>`)")
        eq("push outside a repo", mg.push_finding([], mg.Ctx(Path("nowhere"))),
           "git push without a refspec: the repository of this push cannot be resolved "
           "(push `git push <remote> <feature-branch>`)")
        eq("inline matching", mg.push_finding([], feat, {"push.default": "matching"}),
           "git push to master (from the current branch)")
        eq("inline remote push", mg.push_finding(["origin"], feat, {"remote.origin.push": "HEAD:main"}),
           "git push to main (from the current branch)")
        eq("inline glob", mg.push_finding(["origin"], feat, {"remote.origin.push": "refs/heads/*:refs/heads/*"}),
           "git push with a configured glob refspec (can reach the default branch)")
        eq("inline tag glob", mg.push_finding(["origin"], feat, {"remote.origin.push": "refs/tags/*:refs/tags/*"}),
           None)
        eq("inline unresolved", mg.push_finding(["origin"], feat, {"remote.origin.push": "x:$(x)"}),
           f"git push without a refspec: {UNRESOLVED_MSG} (push `git push <remote> <feature-branch>`)")
        # a checkout/switch earlier in the same command
        eq("branch switches", [mg.scan_text(t, mg.Ctx(world.root("feature"))) for t in (
            "git checkout -b feat2 && git push -u origin HEAD", "git switch -c main && git push origin HEAD",
            "git checkout master && git push", "git checkout feature && git push", "git checkout nosuch && git push",
            "git checkout -- f && git push", "git switch - && git push", "git checkout -b $X && git push",
            "git checkout -b feat2 && git checkout master && git push",
            "git checkout master && git checkout -b f3 && git push origin HEAD")],
           [None, "git push to main", "git push to master (from the current branch)", None,
            "git push without a refspec: the branch is switched earlier in this command; name the destination "
            "branch explicitly (push `git push <remote> <feature-branch>`)"] + [
            "git push without a refspec: the branch is switched earlier in this command; name the destination "
            "branch explicitly (push `git push <remote> <feature-branch>`)"] * 3 + [
            "git push to master (from the current branch)", None])
        eq("PowerShell current-branch idiom", [mg.scan_text(t, mg.Ctx(world.root(w), powershell=True)) for t, w in (
            ("$b = git branch --show-current; git push origin $b", "repo"),
            ("$b = git branch --show-current; git push origin $b", "feature"),
            ("$env:BR='master'; git push origin $env:BR", "feature"))],
           ["git push to master", None, "git push to master"])
        eq("git_finding", [mg.git_finding(a, feat) for a in (
            ["push", "origin", "master"], ["-C", "../repo", "push"], ["-C", "/abs", "push", "origin", "x"],
            ["-c", "push.default=matching", "push"], ["send-pack", "origin", "main"], ["status"],
            ["subtree", "push", "--prefix", "d", "origin", "master"], ["subtree", "push", "origin", "x"],
            ["subtree", "pull", "origin", "master"], ["pm"], ["pf"], ["shpm"], ["nosuchalias"],
            ["-c", "alias.zz=push origin main", "zz"], ["-c", "alias.zz=!git push origin main", "zz"],
            ["--no-pager"], ["-C"], ["-C", "$(x)", "push"])],
           ["git push to master", "git push to master (from the current branch)", None,
            "git push to master (from the current branch)", "git push to main", None,
            "git subtree push to the default branch", None, None, "git alias pm -> git push to master",
            None, "git alias shpm -> git push to main", None, "git alias zz -> git push to main",
            "git alias zz -> git push to main", None, None,
            "git push without a refspec: the repository of this push cannot be resolved "
            "(push `git push <remote> <feature-branch>`)"])
        eq("remote git ignores local aliases", mg.git_finding(["pm"], mg.Ctx(None, remote=True)), None)
        eq("alias depth limit", mg.git_finding(["pm"], mg.Ctx(world.root("feature"), depth=mg.MAX_DEPTH)), None)
        # segments
        eq("cd changes the directory", mg.scan_text("cd ../repo && git push", mg.Ctx(world.root("feature"))),
           "git push to master (from the current branch)")
        eq("cd with a flag", mg.scan_text("Set-Location -Path ..\\repo; git push",
                                          mg.Ctx(world.root("feature"), powershell=True)),
           "git push to master (from the current branch)")
        eq("cd to an absolute path", mg.scan_text(f"cd {world.root('repo').as_posix()} && git push",
                                                  mg.Ctx(world.root("feature"))),
           "git push to master (from the current branch)")
        eq("cd to an unresolved path", mg.scan_text("cd $(x) && git push", mg.Ctx(world.root("feature"))),
           "git push without a refspec: the repository of this push cannot be resolved "
           "(push `git push <remote> <feature-branch>`)")
        eq("cd on a remote host", mg.scan_text("ssh h 'cd /x && git push origin feature'",
                                               mg.Ctx(world.root("feature"))), None)
        eq("plain cd", mg.scan_text("cd", mg.Ctx(world.root("feature"))), None)
    finally:
        mg._git = real_git
    ctx = mg.Ctx(None)
    eq("scan_text findings", [mg.scan_text(t, mg.Ctx(None)) for t in (
        "gh pr merge 5", "echo hi", "x=$(gh pr merge 5)", "A=1", "bash <<E\ngh pr merge 1\nE",
        "cat <<E\ngh pr merge 1\nE", "ssh h <<E\ngit push\nE", "echo 'gh pr merge 1' | bash",
        "echo 'gh pr merge 1' | grep x", "echo 'gh pr merge 1' |", "pr merge 5", "push origin main",
        "push origin feature", "$x pr merge", "$x push origin main", "$x push origin feat",
        "$x status", "python -c \"os.system('git push origin master')\"",
        "python -c \"os.system('git push')\"", "python -c \"print('pr merge')\"",
        "python -c \"subprocess.run(['gh','pr','merge'])\"", "curl -X PUT https://x/repos/o/r/pulls/1/merge",
        "curl https://x/repos/o/r/pulls/1/merge", "env -i git push origin main", "grep -r gh pr merge",
        "node -e 'x' --title 'gh pr merge 1'", "node -e 'x' -m \"$(gh pr merge 1)\"",
        "ssh h 'gh pr merge 1'")],
       ["gh pr merge", None, "gh pr merge", None, "heredoc fed to bash: gh pr merge", None,
        "heredoc fed to ssh: git push without a refspec: a push without a refspec on a remote host "
        "cannot be resolved (push `git push <remote> <feature-branch>`)", "gh pr merge", None, None,
        "pr merge after a computed program name (gh)",
        "push after a computed program name (git): git push to main", None,
        "a variable standing for gh, then pr merge", "a variable standing for git: git push to main", None,
        None, "git push to master", None, None, "gh pr merge", "HTTP write to a GitHub merge/ref endpoint",
        None, "git push to main", None, None, "gh pr merge", "over ssh: gh pr merge"])
    eq("depth stops recursion", mg.scan_text("gh pr merge", mg.Ctx(None, depth=mg.MAX_DEPTH + 1)), None)
    eq("substitution depth", mg._substitution_finding(["$(gh pr merge)"], mg.Ctx(None, depth=mg.MAX_DEPTH)), None)
    eq("scan depth", mg._scan_tokens(["x", "gh pr merge 1"], mg.Ctx(None, depth=mg.MAX_DEPTH)), None)
    eq("verdict prefilter", (mg.verdict("", None), mg.verdict("ls -la", None),
                             mg.verdict("gh pr merge 1", None)), (None, None, "gh pr merge"))
    eq("verdict powershell", (mg.verdict("& (Get-Command gh) pr merge 1", None, True),
                              mg.verdict("echo `gh pr merge 1`", None, True)),
       ("pr merge after a computed program name (gh)", None))
    eq("verdict defaults to bash", mg.verdict("gh pr\\\n merge 1", None), "gh pr merge")
    # decide(): the event wrapper, its fail-closed error path and the reason text
    reason = mg.decide({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 1"}, "cwd": "."})
    eq("decide blocks with the sanctioned path", bool(reason) and "safe_merge.py" in reason
       and "gh pr merge" in reason, True)
    eq("decide allows", mg.decide({"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": "."}), None)
    eq("decide without a command", mg.decide({"tool_name": "Bash", "tool_input": {}}), None)
    eq("decide without a cwd cannot resolve a bare push",
       bool(mg.decide({"tool_name": "Bash", "tool_input": {"command": "git push"}})), True)
    eq("decide reads PowerShell", bool(mg.decide({"tool_name": "PowerShell", "cwd": ".",
                                                  "tool_input": {"command": "Start-Process gh -ArgumentList 'pr','merge','1'"}})),
       True)
    eq("decide uses PowerShell quoting for the PowerShell tool",
       bool(mg.decide({"tool_name": "PowerShell", "cwd": ".",
                       "tool_input": {"command": '& "C:\\Program Files\\GitHub CLI\\gh.exe" pr merge 5'}})), True)
    eq("only the next pipeline stage counts", mg.scan_text("echo 'gh pr merge 1' | grep x; bash", mg.Ctx(None)), None)
    eq("http flags on a non-HTTP program", mg.scan_text("ls -X PUT repos/o/r/pulls/1/merge", mg.Ctx(None)), None)
    eq("python text that only mentions a push", mg.scan_text(
        "python -c \"print('ready to push origin master')\"", mg.Ctx(None)), None)
    real_verdict = mg.verdict
    mg.verdict = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("planted"))
    try:
        r1 = mg.decide({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 1"}, "cwd": "."})
        r2 = mg.decide({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "."})
    finally:
        mg.verdict = real_verdict
    eq("analysis error fails closed on merge text", bool(r1) and "RuntimeError" in r1, True)
    eq("analysis error allows unrelated text", r2, None)


def fast() -> int:
    """MERGE_GATE_FAST=1: every case against an in-memory copy of the test repositories, plus
    the unit battery, so not one git process starts (the mutation probe runs this hundreds of
    times)."""
    failures: list[str] = []
    world = FakeGit()
    real_git = mg._git
    mg._git = world
    try:
        for cmd, where, ps in BLOCK:
            if mg.verdict(cmd, world.root(where), ps) is None:
                failures.append(f"must BLOCK ({where}): {cmd}")
        for cmd, where, ps in ALLOW:
            got = mg.verdict(cmd, world.root(where), ps)
            if got is not None:
                failures.append(f"must ALLOW ({where}): {cmd} -> {got}")
        world.config["push.default"] = "matching"
        if mg.verdict("git push origin", world.root("matching"), False) is None:
            failures.append("must BLOCK: push.default=matching")
        del world.config["push.default"]
        world.config["remote.origin.push"] = "refs/heads/feature:refs/heads/main"
        if mg.verdict("git push origin", world.root("feature"), False) is None:
            failures.append("must BLOCK: remote.origin.push maps to main")
        del world.config["remote.origin.push"]
        world.heads["feature"] = None
        if mg.verdict("git push origin", world.root("feature"), False) is None:
            failures.append("must BLOCK: detached HEAD")
    finally:
        mg._git = real_git
    unit(failures)
    for f in failures:
        print("FAIL", f)
    print(f"SCANNED: fast cases={len(BLOCK) + len(ALLOW)} failures={len(failures)}")
    return 1 if failures else 0


os.environ["BR_FOR_TEST"] = "feature"
os.environ.pop("UNSET_BRANCH_FOR_TEST", None)
def main() -> int:
    if os.environ.get("MERGE_GATE_FAST"):
        return fast()
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        repos = make_repos(Path(tmp))
        for cmd, where, ps in BLOCK:
            got = mg.verdict(cmd, repos[where], ps)
            if got is None:
                failures.append(f"must BLOCK ({where}, ps={ps}): {cmd}")
        for cmd, where, ps in ALLOW:
            got = mg.verdict(cmd, repos[where], ps)
            if got is not None:
                failures.append(f"must ALLOW ({where}, ps={ps}): {cmd} -> {got}")
        # push.default=matching: a local master exists, so a bare push reaches it
        git(repos["repo"], "config", "push.default", "matching")
        if mg.verdict("git push origin", repos["matching"], False) is None:
            failures.append("must BLOCK: refspec-less push with push.default=matching")
        git(repos["repo"], "config", "--unset", "push.default")
        # configured remote.<name>.push refspec
        git(repos["repo"], "config", "remote.origin.push", "refs/heads/feature:refs/heads/main")
        if mg.verdict("git push origin", repos["feature"], False) is None:
            failures.append("must BLOCK: remote.origin.push maps to main")
        git(repos["repo"], "config", "--unset", "remote.origin.push")
        # detached HEAD, refspec-less: cannot resolve -> block
        git(repos["feature"], "checkout", "-q", "--detach")
        if mg.verdict("git push origin", repos["feature"], False) is None:
            failures.append("must BLOCK: refspec-less push from a detached HEAD")
        git(repos["feature"], "checkout", "-q", "feature")
        # not a repository, refspec-less -> block; explicit feature -> allow
        if mg.verdict("git push", Path(tmp), False) is None:
            failures.append("must BLOCK: refspec-less push outside a repository")
        if mg.verdict("git push origin feature", Path(tmp), False) is not None:
            failures.append("must ALLOW: explicit feature push outside a repository")
        # gh alias from the gh config file
        cfg = Path(tmp) / "ghcfg"
        cfg.mkdir()
        (cfg / "config.yml").write_text(
            "git_protocol: https\naliases:\n    mm: pr merge\n    sh: '!gh pr merge $1'\n"
            "    co: pr checkout\nprompt: enabled\n", encoding="utf-8")
        old = os.environ.get("GH_CONFIG_DIR")
        os.environ["GH_CONFIG_DIR"] = str(cfg)
        try:
            for cmd in ("gh mm 5", "gh sh 5"):
                if mg.verdict(cmd, repos["feature"], False) is None:
                    failures.append(f"must BLOCK gh alias: {cmd}")
            if mg.verdict("gh co 5", repos["feature"], False) is not None:
                failures.append("must ALLOW gh alias: gh co 5")
        finally:
            if old is None:
                os.environ.pop("GH_CONFIG_DIR", None)
            else:
                os.environ["GH_CONFIG_DIR"] = old
        # end to end through the hook process: block JSON for a merge, silence for a feature push
        rc, out = hook_run("gh pr merge 5", repos["feature"], False)
        if rc != 0 or '"decision": "block"' not in out or "safe_merge.py" not in out:
            failures.append(f"hook process must emit a block with the safe_merge hint: rc={rc} out={out[:200]}")
        rc, out = hook_run("git push origin feature", repos["feature"], False)
        if rc != 0 or out.strip():
            failures.append(f"hook process must stay silent on a feature push: rc={rc} out={out[:200]}")
        rc, out = hook_run("git push origin master", repos["feature"], True)
        if '"decision": "block"' not in out:
            failures.append("hook process must block a PowerShell push to master")
        # an analysis error on a merge-looking command blocks (fail-closed), else allows
        original = mg.scan_text
        mg.scan_text = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("planted"))
        try:
            try:
                mg.verdict("gh pr merge 5", repos["feature"], False)
                failures.append("planted analysis error did not raise from verdict")
            except RuntimeError:
                pass
        finally:
            mg.scan_text = original
        for w in ("feature", "tracking", "matching"):
            subprocess.run(["git", "-C", str(repos["repo"]), "worktree", "remove", "--force",
                            str(repos[w])], capture_output=True)
    total = len(BLOCK) + len(ALLOW) + 13
    for f in failures:
        print("FAIL", f)
    print(f"SCANNED: cases={total} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
