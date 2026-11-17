"""Owner 2026-10-12: asking to clean docker images approves `docker rmi <name:tag|@digest>` only."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

TAG = "app-staging:v1.2.3"
DIGEST = "ghcr.io/x/y@sha256:" + "a" * 64


class ImageRmShape(unittest.TestCase):
    def test_tagged_rmi_over_ssh_is_image_only(self) -> None:
        self.assertTrue(hcg.image_rm_only(f"ssh host1 'docker rmi {TAG} {DIGEST} 2>&1 | grep -c Deleted; df -h /'"))
        self.assertTrue(hcg.image_rm_only(f"docker image rm {TAG}"))

    def _with_journal(self, scripts: tuple[str, ...]) -> None:
        saved = hcg.IMAGE_RM_COMPANION
        self.addCleanup(setattr, hcg, "IMAGE_RM_COMPANION", saved)
        hcg.IMAGE_RM_COMPANION = hcg._image_rm_companion(scripts)

    def test_configured_journal_log_beside_rmi_is_image_only(self) -> None:
        self._with_journal(("/srv/ops/journal.py",))
        j = ('CLAUDE_SESSION=0a1b2c3d python3 /srv/ops/journal.py log host1-disk '
             '"unused images" "by owner request" 2>/dev/null || true')
        self.assertTrue(hcg.image_rm_only(f"ssh host1 '{j}; docker rmi {TAG} {DIGEST} | grep -c Untagged'"))
        self.assertTrue(hcg.image_rm_only(f"ssh host1 'python3 /srv/ops/journal.py log p \"a\"; docker rmi {TAG}'"))

    def test_journal_lookalikes_are_not_image_only(self) -> None:
        self._with_journal(("/srv/ops/journal.py",))
        for j in ('python3 /srv/ops/journal.py log p "$(id)"', 'python3 /srv/ops/journal.py log p "`id`"',
                  'python3 /tmp/journal.py log p "a"', 'python3 /srv/ops/journal.py purge p "a"',
                  'python3 /srv/ops/journal.py log p "a" > /etc/passwd',
                  'python3 -c "import os" /srv/ops/journal.py log p "a"',
                  'X=1 python3 /srv/ops/journal.py log p "a"', 'python3 /srv/ops/journal.py log p "a" "b" "c"',
                  'python3 /srv/ops/journal.py log p a', 'python3 /srv/ops/journalXpy log p "a"',
                  'true; sh', 'true sh'):
            self.assertFalse(hcg.image_rm_only(f"ssh host1 '{j}; docker rmi {TAG}'"), j)
        self.assertFalse(hcg.image_rm_only("ssh host1 'python3 /srv/ops/journal.py log p \"a\" || true'"))

    def test_journal_log_without_local_config_is_refused(self) -> None:
        self._with_journal(())
        self.assertFalse(hcg.image_rm_only(f"ssh host1 'python3 /srv/ops/journal.py log p \"a\"; docker rmi {TAG}'"))
        self.assertFalse(hcg.image_rm_only(f"ssh host1 'true; docker rmi {TAG}'"))
        self.assertTrue(hcg.image_rm_only(f"ssh host1 'docker rmi {TAG} | grep -c Untagged'"))

    def test_other_shapes_are_not_image_only(self) -> None:
        for cmd in (f"docker rmi -f {TAG}", "docker rmi 3c78e161c588", "docker rmi redis",
                    "docker system prune -af", f"docker rmi {TAG}; docker rm db",
                    f"docker rmi {TAG} && rm -rf /srv/data", "docker volume rm pgdata",
                    f"docker rmi {TAG} | sh", f"docker rmi {TAG} | tee /etc/x",
                    f"docker rmi {TAG} | python3 -c 'import shutil'",
                    f"ssh host1 'docker rmi {TAG} | sh'",
                    f"docker rmi {TAG} | ssh h2 'sh'", f"docker rmi {TAG}; ssh h2 'python3 -c 1'",
                    f"ssh h1 'docker rmi {TAG}' | ssh h2 'tee /etc/x'",
                    f"ssh -o ProxyCommand=sh h1 'docker rmi {TAG}'",
                    f"ssh -J jump h1 'docker rmi {TAG}'", f"ssh -F /tmp/cfg h1 'docker rmi {TAG}'",
                    f"ssh -Fcfg h1 'docker rmi {TAG}'", f"ssh -vFcfg h1 'docker rmi {TAG}'",
                    f"ssh -o Pro\"xyCommand\"=sh h1 'docker rmi {TAG}'",
                    f"ssh -o Include=/tmp/evil.conf h1 'docker rmi {TAG}'",
                    f"ssh -o 'Match exec=sh' h1 'docker rmi {TAG}'"):
            self.assertFalse(hcg.image_rm_only(cmd), cmd)


class ImageRmApproval(unittest.TestCase):
    def go(self, prompt: str, answer: str = "") -> bool:
        hcg.APPROVAL_LOG = Path(__file__).with_name("_image_rm_audit.jsonl")
        try:
            return hcg._image_rm_approval(f"docker rmi {TAG}", prompt, answer, {})[0]
        finally:
            hcg.APPROVAL_LOG.unlink(missing_ok=True)

    def test_request_to_clean_images_approves(self) -> None:
        self.assertTrue(self.go("да, почисти старые образы на сервере"))
        self.assertTrue(self.go("удали старые образы"))

    def test_other_requests_do_not_approve(self) -> None:
        self.assertFalse(self.go("почисти логи на сервере"))
        self.assertFalse(self.go("не удаляй образы"))
        self.assertFalse(self.go("почистить образы?"))
        self.assertFalse(self.go("да", "Перезапущу бота"))
        self.assertFalse(self.go("да", "Удаление образов не нужно, ничего не удаляю"))
        self.assertFalse(self.go("да", "Образ не удаляю; удалю контейнер db"))
        self.assertFalse(self.go("да", "Удалю старые образы на сервере, подтверди"))
        self.assertFalse(self.go("да", "Образы не будут удалены, удалю контейнер db"))
        self.assertFalse(self.go("да, удаляй", "Без удаления образов, только контейнер"))


if __name__ == "__main__":
    unittest.main()
