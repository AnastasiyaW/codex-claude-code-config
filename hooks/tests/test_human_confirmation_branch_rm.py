"""Owner 2026-10-31: removing remote branches passes on her request when every branch is named."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

CMD = "git push origin --delete ops/org-runner main"


class BranchRmGated(unittest.TestCase):
    def test_remote_branch_removal_is_destructive(self) -> None:
        for cmd in (CMD, "git push origin :ops/org-runner", "git push -q origin -d x"):
            self.assertFalse(hcg.decide(cmd)[0], cmd)

    def test_ordinary_pushes_stay_free(self) -> None:
        for cmd in ("git push origin feature/x", "git push -q origin HEAD:feature/x",
                    "git push origin pr413m:chore/crossweft-gone-routes-20261023"):
            self.assertTrue(hcg.decide(cmd)[0], cmd)


class BranchRmShape(unittest.TestCase):
    def test_targets(self) -> None:
        self.assertEqual(hcg.branch_rm_targets(CMD), ["ops/org-runner", "main"])
        self.assertEqual(hcg.branch_rm_targets("cd /d/x/cw && git push origin :a :b"), ["a", "b"])
        self.assertEqual(hcg.branch_rm_targets("git push https://github.com/o/r.git -d a"), ["a"])

    def test_other_shapes_are_not_branch_only(self) -> None:
        for cmd in (f"{CMD}; rm -rf /srv", f"{CMD} | sh", f"{CMD} && git push -f origin main",
                    "git push origin --delete 'a b'", "git push origin --delete $B",
                    f"{CMD} && python -c 1"):
            self.assertIsNone(hcg.branch_rm_targets(cmd), cmd)


class BranchRmApproval(unittest.TestCase):
    def go(self, prompt: str, answer: str = "", branches=("ops/org-runner", "main")) -> bool:
        hcg.APPROVAL_LOG = Path(__file__).with_name("_branch_rm_audit.jsonl")
        try:
            return hcg._branch_rm_approval(list(branches), CMD, prompt, answer, {})[0]
        finally:
            hcg.APPROVAL_LOG.unlink(missing_ok=True)

    def test_named_request_approves(self) -> None:
        self.assertTrue(self.go("удали ветки ops/org-runner и main"))
        self.assertTrue(self.go("удаляй", "Можно ли удалить ветки ops/org-runner и main?"))

    def test_unnamed_or_negated_does_not_approve(self) -> None:
        self.assertFalse(self.go("удали ветку ops/org-runner"))
        self.assertFalse(self.go("не удаляй ops/org-runner и main"))
        self.assertFalse(self.go("удалить ops/org-runner и main?"))
        self.assertFalse(self.go("да", "Ветки ops/org-runner и main оставляю, перезапущу бота"))
        self.assertFalse(self.go("исправь хук", "ops/org-runner main удалить"))
        self.assertFalse(self.go("удаляй", "Удалю ветку ops/org-runner-and-enforcement и main",
                                 branches=("ops/org-runner", "main")))


if __name__ == "__main__":
    unittest.main()
