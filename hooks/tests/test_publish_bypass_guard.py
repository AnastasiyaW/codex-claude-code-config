"""publish-bypass-guard: every route that publishes past the pre-push leak scan blocks; ordinary work passes.

Hermetic: a temporary global git config (GIT_CONFIG_GLOBAL) points core.hooksPath at a temporary
hooks folder whose pre-push calls the scan, and repo visibility is a fake table, so the suite
needs no network and does not read the machine's own git config.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(os.environ.get("HOOKS_DIR", Path(__file__).resolve().parents[1]))
GUARD_PATH = HOOKS / "publish-bypass-guard.py"
_SPEC = importlib.util.spec_from_file_location("pbg", GUARD_PATH)
pbg = importlib.util.module_from_spec(_SPEC)
sys.modules["pbg"] = pbg  # dataclasses resolve annotations through sys.modules
_SPEC.loader.exec_module(pbg)

VISIBILITY = {"acme/alpha": "PUBLIC", "acme/beta": "PUBLIC", "acme/gamma": "PUBLIC",
              "acme/secret": "PRIVATE", "acme/delta": "PUBLIC", "acme/epsilon": "PUBLIC",
              "acme/zeta": "PUBLIC", "acme/eta": "PUBLIC"}
SCAN_HOOK = '#!/bin/sh\nexec python "$HOME/.claude/claude-code-config/hooks/pre-push-public-repo-scan.py" "$@"\n'
# The canonical chain hook ships next to the guard; the tests read it from this source tree.
CHAIN_HOOK = (Path(__file__).resolve().parents[1] / "pre-push-chain.sh").read_text(encoding="utf-8")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class Fixture:
    root: Path
    env: dict[str, str]

    @classmethod
    def build(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.root = root
        global_hooks = root / "global-hooks"
        global_hooks.mkdir()
        (global_hooks / "pre-push").write_text(SCAN_HOOK, encoding="utf-8")
        gitconfig = root / "gitconfig"
        gitconfig.write_text(f"[core]\n\thooksPath = {global_hooks.as_posix()}\n", encoding="utf-8")
        cls.saved = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
        os.environ["GIT_CONFIG_GLOBAL"] = str(gitconfig)
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

        def repo(name: str, slug: str, local_hooks: str | None = None) -> Path:
            path = root / name
            path.mkdir()
            _git("init", "-q", cwd=path)
            _git("remote", "add", "origin", f"https://github.com/{slug}.git", cwd=path)
            if local_hooks is not None:
                _git("config", "core.hooksPath", ".githooks", cwd=path)
                (path / ".githooks").mkdir()
                if local_hooks:
                    (path / ".githooks" / "pre-push").write_text(local_hooks, encoding="utf-8")
            return path

        cls.normal = repo("alpha", "acme/alpha")
        cls.unscanned = repo("beta", "acme/beta", "")
        cls.chained = repo("gamma", "acme/gamma", CHAIN_HOOK)
        cls.private = repo("secret", "acme/secret", "")
        exit_first = CHAIN_HOOK.replace("GLOBAL_HOOKS=", "exit 0\nGLOBAL_HOOKS=", 1)
        cls.exit_first = repo("delta", "acme/delta", exit_first)
        cls.echo_scan = repo("epsilon", "acme/epsilon",
                             CHAIN_HOOK + 'echo "runs pre-push-public-repo-scan.py"\n')
        cls.old_chain = repo("zeta", "acme/zeta",
                             '#!/bin/sh\nexec "$(git config --global --get core.hooksPath)/pre-push" "$@"\n')
        cls.crlf_chain = repo("eta", "acme/eta", None)
        _git("config", "core.hooksPath", ".githooks", cwd=cls.crlf_chain)
        (cls.crlf_chain / ".githooks").mkdir()
        (cls.crlf_chain / ".githooks" / "pre-push").write_bytes(CHAIN_HOOK.replace("\n", "\r\n").encode())
        pbg.repo_visibility = VISIBILITY.get

    @classmethod
    def teardown(cls) -> None:
        for key, value in cls.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cls.tmp.cleanup()


def setUpModule() -> None:
    Fixture.build()


def tearDownModule() -> None:
    Fixture.teardown()


def routes(command: str, cwd: Path | None = None, shell: str = "bash") -> set[str]:
    extra = (shell,) if shell != "bash" else ()  # older guard revisions took no shell argument
    return {f.route for f in pbg.evaluate(command, str(cwd or Fixture.normal), *extra)}


class MustBlock(unittest.TestCase):
    def check(self, command: str, route: str, cwd: Path | None = None) -> None:
        self.assertIn(route, routes(command, cwd), command)

    def test_push_no_verify(self) -> None:
        self.check("git push --no-verify origin main", "push-no-verify")
        self.check("git push --no-verif", "push-no-verify")
        self.check("& git.exe push --no-verify", "push-no-verify")
        self.check("bash -c 'git push --no-verify'", "push-no-verify")
        self.check("out=$(git push --no-verify)", "push-no-verify")
        self.check("ssh host1 'cd /srv/x && git push --no-verify'", "push-no-verify")
        self.check("Start-Process git -ArgumentList 'push --no-verify'", "push-no-verify")
        self.check('git -c alias.pp="push --no-verify" pp', "push-no-verify")

    def test_hookspath_override(self) -> None:
        self.check("git -c core.hooksPath=/dev/null push", "hookspath-override")
        self.check("git -c core.hookspath=x status", "hookspath-override")
        self.check("git --config-env=core.hooksPath=EMPTY push", "hookspath-override")

    def test_git_config_env(self) -> None:
        self.check("GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='x'\" git push", "git-config-env")
        self.check("GIT_EXTERNAL_DIFF=x git push origin main", "git-config-env")
        self.check("env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=x git push",
                   "git-config-env")
        self.check("$env:GIT_CONFIG_GLOBAL='nul'; git push", "git-config-env")
        self.check("export GIT_CONFIG_GLOBAL=/dev/null && git push", "git-config-env")

    def test_send_pack(self) -> None:
        self.check("git send-pack https://github.com/acme/alpha.git main", "send-pack")

    def test_local_hooks_without_scan(self) -> None:
        self.check(f'cd "{Fixture.unscanned}" && git push', "local-hooks")
        self.check(f'git -C "{Fixture.unscanned}" push origin main', "local-hooks")
        self.check("git push", "local-hooks", cwd=Fixture.unscanned)
        found = [f for f in pbg.evaluate("git push", str(Fixture.unscanned)) if f.route == "local-hooks"]
        self.assertIn(str(Fixture.unscanned.name), found[0].detail)
        self.assertIn("config --unset core.hooksPath", found[0].fix)

    def test_unknown_repo(self) -> None:
        self.check("cd $REPO && git push", "unknown-repo")
        self.check("cd /no/such/dir/here && git push", "unknown-repo")

    # Fresh-context review 2026-10-28: each of these passed the first version.
    def test_git_bash_drive_paths(self) -> None:
        if os.name != "nt":
            self.skipTest("drive-letter spelling exists only on Windows")
        posix = "/" + Fixture.unscanned.as_posix().replace(":", "", 1)
        posix = posix[0] + posix[1].lower() + posix[2:]
        self.check(f"cd {posix} && git push", "local-hooks")
        self.check(f"git -C {posix} push", "local-hooks")

    def test_hookspath_rewritten_in_config(self) -> None:
        self.check("git config core.hooksPath .nohooks && git push", "hookspath-config")
        self.check("git config --global --unset core.hooksPath; git push", "hookspath-config")

    def test_home_moves_global_config(self) -> None:
        self.check("HOME=/tmp/empty git push", "git-config-env")
        self.check("$env:HOME='C:\\x'; git push", "git-config-env")

    def test_dynamic_subcommand_or_arguments(self) -> None:
        self.check("$a='push','--no-verify'; git @a", "dynamic-git")
        self.check("p=push; git $p --no-verify", "dynamic-git")
        self.check("echo push --no-verify | xargs git", "dynamic-git")
        self.check("git push origin $FLAGS", "dynamic-git")

    def test_public_flag_with_value_and_release_api(self) -> None:
        self.check("gh gist create --public=true f", "gist-public")
        self.check("gh repo create acme/x --public=true --push", "repo-public")
        self.check("gh api -X POST repos/acme/alpha/releases -f body=x", "api-write")
        self.check("gh api gists -f public=true -f files[a][content]=x", "api-write")

    def test_visibility_and_gist(self) -> None:
        self.check("gh repo edit acme/alpha --visibility public --accept-visibility-change-consequences",
                   "repo-public")
        self.check("gh repo edit --visibility=public", "repo-public")
        self.check("gh repo create newthing --public --source=. --push", "repo-public")
        self.check("gh gist create notes.txt --public", "gist-public")
        self.check("gh gist create notes.txt -p", "gist-public")
        self.check("gh gist edit abc123 --add secrets.txt", "gist-public")

    def test_api_writes(self) -> None:
        self.check("gh api -X PUT repos/acme/alpha/contents/a.txt -f message=m -f content=eA==",
                   "api-write")
        self.check("gh api repos/acme/alpha/git/blobs -f content=x", "api-write")
        self.check("gh api --method=PATCH /repos/{owner}/{repo}/git/refs/heads/main -F sha=abc",
                   "api-write")
        self.check("gh api graphql -f query='mutation { createCommitOnBranch(input: {}) { commit { oid } } }'",
                   "api-write")
        self.check("gh api -X PATCH repos/acme/alpha -f visibility=public", "repo-public")

    def test_release_on_public_or_unknown(self) -> None:
        self.check("gh release create v1.0 dist.zip", "release-public")
        self.check("gh release upload v1.0 dist.zip -R acme/unknown", "release-public")


class CoordinatorReview(unittest.TestCase):
    """Independent re-review of e193aab (HOLD, 12 executed bypasses) and the chain-bytes review."""

    def check(self, command: str, route: str, cwd: Path | None = None, shell: str = "bash") -> None:
        self.assertIn(route, routes(command, cwd, shell), command)

    def test_1_escapes_are_removed_before_tokenising(self) -> None:
        self.check("git push --no-ve\\rify", "push-no-verify")
        self.check("git pu\\sh --no-verify", "push-no-verify")
        self.check("g\\it push --no-verify", "push-no-verify")
        self.check("git push --no-ver`ify", "push-no-verify", shell="powershell")
        self.check("gi`t pu`sh --no-verify", "push-no-verify", shell="powershell")

    def test_2_git_dir_names_the_repo_judged(self) -> None:
        git_dir = (Fixture.unscanned / ".git").as_posix()
        self.check(f"GIT_DIR={git_dir} git push", "local-hooks")
        self.check(f"export GIT_DIR={git_dir}; git push", "local-hooks")
        self.check(f"$env:GIT_DIR='{git_dir}'; git push", "local-hooks", shell="powershell")
        self.check("GIT_DIR=$X git push", "unknown-repo")
        self.check("GIT_WORK_TREE=/no/such/tree GIT_DIR=/no/such/dir git push", "unknown-repo")

    def test_3_alias_from_env_config(self) -> None:
        self.check("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.pp GIT_CONFIG_VALUE_0=push git pp",
                   "alias-from-env")
        self.check("git --config-env=alias.pp=PP pp", "alias-from-env")
        self.check("$env:GIT_CONFIG_PARAMETERS=\"'alias.pp'='push'\"; git pp", "alias-from-env",
                   shell="powershell")

    def test_4_builtins_that_run_commands(self) -> None:
        self.check("git submodule foreach 'git push --no-verify'", "push-no-verify")
        self.check("git bisect run git push --no-verify", "push-no-verify")
        self.check("git rebase -x 'git push --no-verify' main", "push-no-verify")
        self.check("git rebase --exec='git push --no-verify' main", "push-no-verify")
        self.check("git difftool -x 'git push --no-verify'", "push-no-verify")

    def test_5_chain_hook_must_be_canonical_bytes(self) -> None:
        for repo in (Fixture.exit_first, Fixture.echo_scan, Fixture.old_chain):
            self.check("git push", "local-hooks", cwd=repo)
        found = [f for f in pbg.evaluate("git push", str(Fixture.exit_first)) if f.route == "local-hooks"]
        self.assertIn("pre-push-chain.sh", found[0].fix)
        self.assertEqual(set(), routes("git push", Fixture.crlf_chain))

    def test_6_api_fields_read_unquoted(self) -> None:
        self.check("gh api -X PATCH repos/acme/alpha -f 'visibility'='public'", "repo-public")
        self.check('gh api -X PATCH repos/acme/alpha -F "private"=false', "repo-public")
        self.check("gh api -X PUT repos//acme/alpha//contents/a.txt -f content=eA==", "api-write")

    def test_7_http_clients_hub_gh_alias_and_secret_gists(self) -> None:
        self.check("curl -X PUT https://api.github.com/repos/acme/alpha/contents/a -d @body.json",
                   "http-write")
        self.check("curl -d @b.json https://api.github.com/repos/acme/alpha/git/blobs", "http-write")
        self.check("wget --method=PATCH https://api.github.com/repos/acme/alpha --body-data x",
                   "http-write")
        self.check("Invoke-RestMethod -Method Post -Uri https://uploads.github.com/repos/a/b/releases/1/assets",
                   "http-write", shell="powershell")
        self.check("hub api -X PUT repos/acme/alpha/contents/a -f content=x", "api-write")
        self.check("gh alias set pubr 'repo edit --visibility public'", "alias-set")
        self.check("gh alias set --shell np 'git push --no-verify'", "alias-set")
        self.check("gh gist create notes.txt", "gist-public")

    def test_8_variable_command_names(self) -> None:
        self.check("g=git; $g push --no-verify", "dynamic-git")
        self.check("$g = 'git'; & $g push origin main", "dynamic-git", shell="powershell")
        self.check("${G} push", "dynamic-git")

    def test_9_encoded_powershell(self) -> None:
        import base64
        payload = base64.b64encode("git push --no-verify".encode("utf-16-le")).decode()
        self.check(f"pwsh -EncodedCommand {payload}", "push-no-verify", shell="powershell")
        self.check(f"powershell -enc {payload}", "push-no-verify", shell="powershell")
        self.check("pwsh -e not-base64!!", "encoded-command", shell="powershell")


class ThirdReview(unittest.TestCase):
    """Third independent review of 9449f67 (HOLD): executed bypasses and one false positive."""

    def check(self, command: str, route: str, cwd: Path | None = None, shell: str = "bash") -> None:
        self.assertIn(route, routes(command, cwd, shell), command)

    def test_1_wrapper_option_values(self) -> None:
        for command in ("nice -n 5 git push", "timeout -s INT 60 git push", "env -u FOO git push",
                        "ionice -c 3 git push", "stdbuf -o L git push", "sudo -u bob git push",
                        "time -o t.log git push", "nohup git push", "command git push"):
            self.check(command, "local-hooks", cwd=Fixture.unscanned)
        self.check("nice -n 5 env GIT_DIR=../beta/.git git push", "local-hooks")
        self.check("env -C ../beta git push", "local-hooks")
        self.check("mywrap --flag git push", "unknown-shape")

    def test_2_push_target_changed_in_the_same_command(self) -> None:
        public = "https://github.com/acme/alpha.git"
        self.check(f"git remote set-url origin {public} && git push", "local-hooks", cwd=Fixture.private)
        self.check(f"git -c remote.origin.pushurl={public} push", "local-hooks", cwd=Fixture.private)
        self.check(f"git config remote.origin.url {public}; git push", "local-hooks", cwd=Fixture.private)
        self.check("git -c url.https://github.com/acme/alpha.pushInsteadOf=https://github.com/acme/secret push",
                   "local-hooks", cwd=Fixture.private)

    def test_3_gh_repo_env(self) -> None:
        self.check("GH_REPO=acme/alpha gh release create v1", "release-public", cwd=Fixture.private)
        self.check("export GH_REPO=acme/alpha; gh release create v1", "release-public", cwd=Fixture.private)
        self.check("$env:GH_REPO='acme/alpha'; gh release upload v1 f", "release-public",
                   cwd=Fixture.private, shell="powershell")

    def test_4_start_process_workdir_and_dynamic_api_path(self) -> None:
        self.check("Start-Process git -ArgumentList 'push origin main' -WorkingDirectory ../beta",
                   "local-hooks", shell="powershell")
        self.check("gh api -X PUT $P -f content=x", "dynamic-git")


class MustPass(unittest.TestCase):
    def check(self, command: str, cwd: Path | None = None, shell: str = "bash") -> None:
        self.assertEqual(set(), routes(command, cwd, shell), command)

    def test_plain_push_from_normal_repo(self) -> None:
        self.check("git push")
        self.check("git push -u origin feat/x")
        self.check(f'git -C "{Fixture.normal}" push origin main')

    def test_dry_run_is_not_a_hook_skip(self) -> None:
        self.check("git push -n origin main")

    def test_text_mentioning_routes(self) -> None:
        self.check("echo git push --no-verify")
        self.check("echo 'gh repo edit --visibility public'")
        self.check('grep -n -- "--no-verify" hooks/publish-bypass-guard.py')
        self.check("Write-Output 'git push --no-verify'")
        self.check('git commit -m "never use git push --no-verify"')
        self.check("# git push --no-verify\ngit status")

    def test_local_hooks_that_chain_or_private_target(self) -> None:
        self.check("git push", cwd=Fixture.chained)
        self.check("git push", cwd=Fixture.crlf_chain)
        self.check("git push", cwd=Fixture.private)

    def test_safe_gh(self) -> None:
        self.check("gh release create v1 -R acme/secret")
        self.check("gh api repos/acme/alpha/contents/a.txt")
        self.check("gh repo create newthing --private --source=. --push")
        self.check("gh repo edit acme/alpha --visibility private")
        self.check("gh pr create --title t --body 'run git push --no-verify? no'")

    def test_other_git(self) -> None:
        self.check("git status && git log --oneline -3 && git fetch origin")
        self.check("git config --get core.hooksPath")
        self.check("git push origin HEAD:@{u}")
        self.check("git ls-files | xargs git add")
        self.check("git submodule foreach 'git status'")
        # third review: quoted values of non-push git subcommands are data
        self.check("git log --grep='git push --no-verify'")
        self.check("git log -S 'git push --no-verify' --oneline")
        self.check("git grep -e 'push --no-verify'")
        self.check("git push", cwd=Fixture.private)
        self.check("gh release create v1", cwd=Fixture.private)
        self.check("nice -n 5 git push")
        self.check("git remote -v && git push")
        self.check("git rebase -x 'npm test' main")
        self.check("curl https://api.github.com/repos/acme/alpha")
        self.check("$x = 'push done'; Write-Output $x", shell="powershell")
        self.check("cd D:/tmp && ls", None)
        self.check("pwsh -NoProfile -Command Get-Date", shell="powershell")
        self.check("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=x git status")


class Approval(unittest.TestCase):
    def blocked(self, command: str, prompt: str | None, cwd: Path | None = None) -> set[str]:
        findings = pbg.evaluate(command, str(cwd or Fixture.normal))
        self.assertTrue(findings, command)
        return {f.route for f in pbg.unapproved(findings, prompt)}

    def test_named_action_unblocks(self) -> None:
        self.assertEqual(set(), self.blocked("git push --no-verify", "разрешаю git push --no-verify в alpha"))
        self.assertEqual(set(), self.blocked("gh repo edit acme/alpha --visibility public",
                                             "ok, make acme/alpha public"))

    def test_approval_covers_only_the_named_action(self) -> None:
        prompt = "разрешаю git push --no-verify в alpha"
        self.assertEqual({"repo-public"}, self.blocked("gh repo edit acme/alpha --visibility public", prompt))
        self.assertEqual({"push-no-verify"}, self.blocked("git push --no-verify", prompt, Fixture.chained))
        self.assertEqual({"hookspath-override"}, self.blocked("git -c core.hooksPath=x push", prompt))

    def test_negation_question_or_absence_do_not_approve(self) -> None:
        for prompt in (None, "", "не делай git push --no-verify в alpha",
                       "I disapprove: push alpha with --no-verify",
                       "disallow --no-verify push to alpha",
                       "можно git push --no-verify в alpha?", "git push --no-verify в alpha"):
            self.assertEqual({"push-no-verify"}, self.blocked("git push --no-verify", prompt), prompt)


class EndToEnd(unittest.TestCase):
    """The hook as the harness runs it: stdin event, stdout decision, transcript as approval."""

    def run_hook(self, command: str, prompt: str | None, tool: str = "Bash") -> dict | None:
        home = Fixture.root / "home"
        home.mkdir(exist_ok=True)
        event = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(Fixture.normal),
                 "hook_event_name": "PreToolUse", "session_id": "test"}
        if prompt is not None:
            transcript = Fixture.root / "transcript.jsonl"
            transcript.write_text(json.dumps({"type": "user", "origin": {"kind": "human"},
                                              "message": {"role": "user", "content": prompt}},
                                             ensure_ascii=False) + "\n", encoding="utf-8")
            event["transcript_path"] = str(transcript)
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
        result = subprocess.run([sys.executable, "-B", str(GUARD_PATH)], input=json.dumps(event),
                                capture_output=True, text=True, encoding="utf-8", env=env,
                                timeout=120, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_block_then_owner_approval(self) -> None:
        verdict = self.run_hook("git push --no-verify", None)
        self.assertEqual("block", (verdict or {}).get("decision"))
        self.assertIn("push-no-verify", verdict["reason"])
        self.assertIsNone(self.run_hook("git push --no-verify", "да, разрешаю git push --no-verify в alpha"))
        audit = Fixture.root / "home" / ".claude" / "logs" / "publish-approvals.jsonl"
        self.assertIn("push-no-verify", audit.read_text(encoding="utf-8"))

    def test_plain_push_and_powershell(self) -> None:
        self.assertIsNone(self.run_hook("git push", None))
        verdict = self.run_hook("$env:GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='x'\"; git push", None,
                                tool="PowerShell")
        self.assertEqual("block", (verdict or {}).get("decision"))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    if outcome.wasSuccessful():
        print(f"all {outcome.testsRun} checks correct")
    sys.exit(0 if outcome.wasSuccessful() else 1)
