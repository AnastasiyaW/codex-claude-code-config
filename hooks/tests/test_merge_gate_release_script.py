"""A release script listed in the local config passes the merge gate only in its exact form."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mgg", Path(__file__).resolve().parents[1] / "merge-gate-guard.py")
mgg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mgg)

SCRIPT = "#!/usr/bin/env bash\ngit push \"$1\" \"$snap:refs/heads/main\"\n"
ORIGIN, PUBLIC = "https://github.com/example-org/tool-private.git", "https://github.com/example/tool.git"


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


class ReleaseScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        src, cls.repo = root / "src", root / "tool"
        (src / "internal/tools").mkdir(parents=True)
        (src / "internal/tools/publish_oss.sh").write_text(SCRIPT, encoding="utf-8")
        _git(src, "init", "-q", "-b", "internal")
        _git(src, "add", ".")
        _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
        subprocess.run(["git", "clone", "-q", "-b", "internal", str(src), str(cls.repo)], check=True)
        _git(cls.repo, "remote", "set-url", "origin", ORIGIN)
        _git(cls.repo, "remote", "add", "public", PUBLIC)
        cls.config = root / "releases.json"
        cls.config.write_text(json.dumps({"releases": [{
            "script": "internal/tools/publish_oss.sh", "remote": "public",
            "origin": "example-org/tool-private", "public": "example/tool",
            "reviewed_ref": "refs/remotes/origin/internal"}]}), encoding="utf-8")
        cls.saved = mgg.RELEASES_CONFIG
        mgg.RELEASES_CONFIG = cls.config

    @classmethod
    def tearDownClass(cls) -> None:
        mgg.RELEASES_CONFIG = cls.saved
        cls.tmp.cleanup()

    def says(self, text: str, kind: str = "human") -> str:
        path = Path(self.tmp.name) / f"t-{abs(hash((text, kind)))}.jsonl"
        path.write_text(json.dumps({"type": "user", "origin": {"kind": kind},
                                    "message": {"role": "user", "content": text}}, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return str(path)

    def decide(self, command: str, owner: str = "Да, выпускай", tool: str = "Bash") -> str | None:
        return mgg.decide({"tool_name": tool, "tool_input": {"command": command},
                           "cwd": str(self.repo), "transcript_path": self.says(owner)})

    def cmd(self, tail: str = "TAG=later bash internal/tools/publish_oss.sh public 0.6.0") -> str:
        return f"cd {self.repo.as_posix()} && {tail}"

    def test_release_passes_on_owner_word(self) -> None:
        self.assertIsNone(self.decide(self.cmd()))
        self.assertIsNone(self.decide(self.cmd(), owner="влей 28"))
        self.assertIsNone(self.decide(self.cmd(), owner="please release it"))
        self.assertIsNone(self.decide(self.cmd(
            "GIT_AUTHOR_NAME=Bot GIT_AUTHOR_EMAIL=bot@example.com TAG=only "
            "bash internal/tools/publish_oss.sh public 0.6.0")))
        self.assertIsNone(self.decide("TAG=later bash internal/tools/publish_oss.sh public 0.6.0"))

    def test_without_owner_word_it_blocks(self) -> None:
        for owner in ("Исключение в хуке", "не выпускай", "выпускаем?"):
            self.assertIsNotNone(self.decide(self.cmd(), owner=owner), owner)
        self.assertIsNotNone(mgg.decide({"tool_name": "Bash", "tool_input": {"command": self.cmd()},
                                         "cwd": str(self.repo), "transcript_path": self.says("выпускай", "agent")}))

    def test_other_forms_block(self) -> None:
        for tail in ("TAG=now bash internal/tools/publish_oss.sh public 0.6.0",
                     "TAG=later bash internal/tools/publish_oss.sh https://github.com/x/y 0.6.0",
                     "TAG=later bash internal/tools/publish_oss.sh public 0.6.0; git push public x:main",
                     "TAG=later bash internal/tools/publish_oss.sh public 0.6.0 && git push origin HEAD:oss",
                     "X=$(git push public x:main) bash internal/tools/publish_oss.sh public 0.6.0",
                     "bash ./internal/tools/publish_oss.sh public 0.6.0"):
            self.assertIsNotNone(self.decide(self.cmd(tail)), tail)
        self.assertIsNotNone(self.decide(self.cmd(), tool="PowerShell"))

    def test_dirty_or_moved_checkout_blocks(self) -> None:
        script = self.repo / "internal/tools/publish_oss.sh"
        script.write_text(SCRIPT + "git push public HEAD:main\n", encoding="utf-8")
        try:
            self.assertIn("clean", self.decide(self.cmd()) or "")
        finally:
            _git(self.repo, "checkout", "--", ".")
        _git(self.repo, "remote", "set-url", "public", "https://github.com/someone/else.git")
        try:
            self.assertIn("public", self.decide(self.cmd()) or "")
        finally:
            _git(self.repo, "remote", "set-url", "public", PUBLIC)
        _git(self.repo, "remote", "set-url", "origin", "https://github.com/someone/tool.git")
        try:
            self.assertIn("origin", self.decide(self.cmd()) or "")
        finally:
            _git(self.repo, "remote", "set-url", "origin", ORIGIN)

    def test_unlisted_script_or_no_config_still_scanned(self) -> None:
        other = Path(self.tmp.name) / "other"
        (other / "internal/tools").mkdir(parents=True)
        (other / "internal/tools/publish_oss.sh").write_text(SCRIPT, encoding="utf-8")
        _git(other, "init", "-q", "-b", "internal")
        self.assertIsNotNone(self.decide(f"cd {other.as_posix()} && TAG=later bash internal/tools/publish_oss.sh public 0.6.0"))
        mgg.RELEASES_CONFIG = Path(self.tmp.name) / "missing.json"
        try:
            self.assertIsNotNone(self.decide(self.cmd()))
        finally:
            mgg.RELEASES_CONFIG = self.config


if __name__ == "__main__":
    unittest.main()
