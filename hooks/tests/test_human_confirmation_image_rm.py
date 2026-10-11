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
