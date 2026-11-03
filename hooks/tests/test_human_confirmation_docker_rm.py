"""Owner 2026-11-03: docker containers, volumes and images named in my «Удаление» block go on her bare yes."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

IMG = "registry.example/app/worker:v1-7bf41604"
CMD = f"ssh host1 'docker rm gh-runner gh-runner-dind; docker volume rm gh-runner_dind-storage; docker rmi {IMG}'"
BLOCK = ("**Удаление** — 4 пути, ответь «да»:\n```\n/var/lib/docker/volumes/gh-runner_dind-storage\n"
         f"docker container gh-runner\ndocker container gh-runner-dind\ndocker image {IMG}\n```\n")


class DockerRmShape(unittest.TestCase):
    def test_named_removals_over_ssh(self) -> None:
        self.assertEqual(hcg.docker_rm_targets(CMD), [
            ("container", "gh-runner"), ("container", "gh-runner-dind"),
            ("volume", "gh-runner_dind-storage"), ("image", IMG)])
        self.assertEqual(hcg.docker_rm_targets("docker volume rm a1 b2; docker volume ls -q"),
                         [("volume", "a1"), ("volume", "b2")])

    def test_other_shapes_are_refused(self) -> None:
        for cmd in ("docker rm -f web", "docker volume rm -f v1", "docker volume prune -f",
                    "docker system prune -af", "docker rmi redis", "docker rmi 3c78e161c588",
                    "docker rm web && rm -rf /srv/data", "docker volume rm v1 | sh",
                    "docker rm $(docker ps -aq)", "docker volume rm v*",
                    "ssh -o ProxyCommand=sh h1 'docker rm web'", "ssh h1 'docker rm web; python3 -c 1'"):
            self.assertIsNone(hcg.docker_rm_targets(cmd), cmd)


class DockerRmApproval(unittest.TestCase):
    def go(self, cmd: str, prompt: str, answer: str = "") -> bool:
        hcg.APPROVAL_LOG = Path(__file__).with_name("_docker_rm_audit.jsonl")
        try:
            return hcg._docker_rm_approval(hcg.docker_rm_targets(cmd), cmd, prompt, answer, {})[0]
        finally:
            hcg.APPROVAL_LOG.unlink(missing_ok=True)

    def test_bare_yes_to_the_block_approves(self) -> None:
        self.assertTrue(self.go(CMD, "Да, удаляй", BLOCK))

    def test_owner_naming_approves(self) -> None:
        self.assertTrue(self.go("docker volume rm pgdata_old", "удали том pgdata_old на сервере"))

    def test_refusals(self) -> None:
        self.assertFalse(self.go(CMD, "да", "Удалю тома раннера, подтверди"))           # no block
        self.assertFalse(self.go(CMD + "", "да", BLOCK.replace("gh-runner-dind\n", "x\n")))  # one unnamed
        self.assertFalse(self.go("docker volume rm pgdata_old", "да",
                                 "**Удаление**\n```\ndocker volume pgdata_old\n```\n"))  # data volume needs her words
        self.assertFalse(self.go(CMD, "не удаляй тома gh-runner_dind-storage"))
        self.assertFalse(self.go(CMD, "удалить gh-runner gh-runner-dind gh-runner_dind-storage?"))
        self.assertFalse(self.go(CMD, "почисти логи"))


if __name__ == "__main__":
    unittest.main()
