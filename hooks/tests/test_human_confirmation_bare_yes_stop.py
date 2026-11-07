"""Regression: a bare «да» to my one-line stop offer approves it, even when an earlier paragraph
of the same answer explains a rule with «если» (owner 2026-10-30: the offer
«Убью зависшие процессы сборки: `taskkill //PID ... //F`» was refused as unnamed targets,
because the explanation sentence above it said «только если»).
A condition in the sentence that leads into the offer still voids it. Synthetic transcripts only;
nothing is executed."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "human-confirmation-guard.py"
_spec = importlib.util.spec_from_file_location("human_confirmation_guard", HOOK)
guard = importlib.util.module_from_spec(_spec)
_argv, sys.argv = sys.argv, [str(HOOK)]
_spec.loader.exec_module(guard)
sys.argv = _argv

PIDS = ("108800", "127404", "66840", "143928", "20236")
CMD = "taskkill " + " ".join(f"//PID {p}" for p in PIDS) + " //F"
EXPLAINED_OFFER = (
    "Причина найдена: на голое «да» хук принимает команду, только если в той же строке перед ней "
    "стоит «убью:» или похожее слово. У меня команда стояла отдельной строкой. "
    "Повторяю предложение в нужной форме:\n\n"
    f"Убью зависшие процессы сборки: `{CMD}`\n\n"
    "Ответьте «да», и я сразу перезапущу сборку 2.1.2 с подписью.")


class BareYesStopOfferTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="bare-yes-stop-")
        self.addCleanup(self._dir.cleanup)
        guard.APPROVAL_LOG = Path(self._dir.name) / "approvals.jsonl"

    def decide(self, answer: str, prompt: str = "да", cmd: str = CMD) -> tuple[bool, str]:
        path = Path(self._dir.name) / "t.jsonl"
        entries = [
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": answer}]}},
            {"type": "user", "origin": {"kind": "human"}, "isSidechain": False,
             "message": {"role": "user", "content": prompt}},
        ]
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
        return guard.approved_by_owner(cmd, {"tool_name": "Bash", "transcript_path": str(path),
                                             "session_id": "test", "tool_input": {"command": cmd}})

    def test_explanation_with_esli_above_offer_does_not_void_it(self) -> None:
        self.assertEqual((True, "process stop"), self.decide(EXPLAINED_OFFER))

    def test_condition_leading_into_offer_still_voids_it(self) -> None:
        for lead_in in ("Если сборка не закончится через 10 минут, то:",
                        "Сборка висит. Если через минуту не оживёт, тогда:",
                        "Подождём ещё. Иначе:"):
            with self.subTest(lead_in=lead_in):
                ok, why = self.decide(f"{lead_in}\nУбью зависшие процессы сборки: `{CMD}`")
                self.assertFalse(ok, why)

    def test_tree_kill_still_needs_t_in_the_proposal(self) -> None:
        ok, why = self.decide(EXPLAINED_OFFER, cmd=CMD.replace(" //F", " //T //F"))
        self.assertFalse(ok)
        self.assertIn("/T", why)

    def test_unproposed_pid_still_refused(self) -> None:
        ok, why = self.decide(EXPLAINED_OFFER, cmd=CMD.replace("//F", "//PID 4242 //F"))
        self.assertFalse(ok)
        self.assertIn("4242", why)

    def test_powershell_still_refused(self) -> None:
        path_ok, _ = self.decide(EXPLAINED_OFFER)
        self.assertTrue(path_ok)
        path = Path(self._dir.name) / "t.jsonl"
        ok, _ = guard.approved_by_owner(CMD, {"tool_name": "PowerShell", "transcript_path": str(path),
                                              "session_id": "test", "tool_input": {"command": CMD}})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
