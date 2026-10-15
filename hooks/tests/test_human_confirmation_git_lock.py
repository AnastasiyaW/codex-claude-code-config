"""Owner 2026-10-15: her own «удали <repo>\\.git\\index.lock» approves the lock tool under a share."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

TOOL = str(hcg.GIT_LOCK_TOOL).replace("\\", "/")


def human(text: str) -> dict:
    return {"type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": text}}


def assistant(text: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


class GitLockOwnerApproval(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.lock = self.repo / ".git" / "index.lock"
        self.lock.write_bytes(b"")
        self.transcript = root / "t.jsonl"
        self.log = root / "approvals.jsonl"
        self.saved = hcg.APPROVAL_LOG
        hcg.APPROVAL_LOG = self.log

    def tearDown(self) -> None:
        hcg.APPROVAL_LOG = self.saved
        self.tmp.cleanup()

    def go(self, *entries: dict, cmd: str | None = None):
        self.transcript.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                                   encoding="utf-8")
        repo = str(self.repo).replace("\\", "/")
        cmd = cmd or f"python {TOOL} {repo} --remove --owner-approved"
        return hcg.git_lock_owner_approval(cmd, {"transcript_path": str(self.transcript)})

    def test_owner_naming_the_lock_approves_and_records_it(self) -> None:
        ok, why = self.go(human(f"да, удали {self.lock}"))
        self.assertTrue(ok, why)
        rec = json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["action"], "git-lock-owner")
        self.assertEqual(rec["locks"], [hcg.git_lock_key(self.lock)])

    def test_a_dropped_separator_still_names_the_same_file(self) -> None:
        typo = str(self.repo) + ".git\\index.lock"   # «<repo>.git\index.lock»
        self.assertTrue(self.go(human(f"да, удали {typo}"))[0])

    def test_bare_yes_to_my_answer_naming_the_path(self) -> None:
        self.assertTrue(self.go(assistant(f"Удалить {self.lock}? Ответьте «да»."), human("да"))[0])

    def test_refusals(self) -> None:
        cases = [
            (human("удали лок"),),                                      # names no file
            (human(f"не удаляй {self.lock}"),),                          # negation
            (human(f"удалить {self.lock}?"),),                           # a question
            (human(f"посмотри {self.lock}"),),                           # no delete intent
            (assistant("Перезапущу программу."), human("да")),           # bare yes, no deletion proposed
            (human(f"удали {self.repo / '.git' / 'HEAD.lock'}"),),       # names another lock
            (human(f"удали {self.lock}.bak"),),                          # a longer name
        ]
        for entries in cases:
            self.assertFalse(self.go(*entries)[0], entries)
        self.assertFalse(self.log.exists(), "a refused approval wrote a record")

    def test_only_the_exact_tool_call_is_this_approval(self) -> None:
        repo = str(self.repo).replace("\\", "/")
        owner = human(f"да, удали {self.lock}")
        self.assertIsNone(self.go(owner, cmd=f"python {TOOL} {repo} --remove")[0])
        self.assertIsNone(self.go(owner, cmd=f"python {TOOL} {repo} --remove --owner-approved; rm -rf /")[0])
        self.assertFalse(self.go(owner, cmd=f"python /tmp/fake/git_stale_lock.py {repo} --remove --owner-approved")[0])
        self.assertFalse(self.go(owner, cmd=f"python {TOOL} repo --remove --owner-approved")[0])
        # review 15.10 finding 1: shell metacharacters in the repository token
        self.assertFalse(self.go(owner, cmd=f'python {TOOL} "{repo}$(calc)" --remove --owner-approved')[0])

    def test_a_bare_repo_lock_does_not_name_the_working_repo_lock(self) -> None:
        # review 15.10 finding 3: x.git/index.lock (bare repo) vs x/.git/index.lock
        other = str(self.repo) + "\\x.git\\index.lock"
        self.assertFalse(self.go(human(f"удали {other}"))[0])

    def test_two_locks_named_in_one_message(self) -> None:
        # review 15.10 finding 4: the first of several space-separated paths counts too
        head = self.repo / ".git" / "HEAD.lock"
        head.write_bytes(b"")
        ok, why = self.go(human(f"удали {self.lock} {head}"))
        self.assertTrue(ok, why)
        rec = json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(sorted(rec["locks"]), sorted([hcg.git_lock_key(self.lock), hcg.git_lock_key(head)]))


if __name__ == "__main__":
    unittest.main()
