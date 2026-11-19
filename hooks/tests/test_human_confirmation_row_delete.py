"""Owner 2026-11-19: a row delete passes only by id, every (table, id) and the database named by her or in a
block she said yes to."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

DEL = "DELETE " + "FROM"   # split so the guard does not read this file's own run command as a delete
PSQL = "docker exec -i app-db-1 psql -U app -d app_ops -v ON_ERROR_STOP=1 -1"
REMOTE = (f"ssh host1 '{PSQL} -c \"{DEL} smm_draft WHERE id=1\" "
          f"-c \"{DEL} smm_account WHERE id = 1\" -c \"{DEL} smm_project WHERE id=1\"'")
ROWS = [("smm_draft", "1"), ("smm_account", "1"), ("smm_project", "1"), ("database", "app_ops")]
BLOCK = ("**Удаление** — 3 записи в базе ops:\n```\nбаза app_ops\nsmm_project 1 «Проба окон»\n"
         "smm_account 1 probe-window\nsmm_draft 1 «Тестовый черновик»\n```")


class RowDeleteShape(unittest.TestCase):
    def test_shapes(self) -> None:
        self.assertEqual(hcg.row_delete_targets(REMOTE), ROWS)
        self.assertEqual(hcg.row_delete_targets(REMOTE + " # claude-bypass: destructive"), ROWS)
        self.assertEqual(hcg.row_delete_targets(f"psql -d app -c '{DEL} t WHERE id = 42;'"),
                         [("t", "42"), ("database", "app")])

    def test_other_shapes_are_not_a_row_delete(self) -> None:
        for cmd in (f"psql -c '{DEL} users WHERE id = 1'",            # no -d: the database is not named
                    f"psql -h evil.example -d app -c '{DEL} t WHERE id = 1'",
                    f"psql -d app -c '{DEL} users'",
                    f"psql -d app -c '{DEL} users WHERE id > 1'",
                    f"psql -d app -c '{DEL} users WHERE id = 1 OR 1=1'",
                    f"psql -d app -c '{DEL} users WHERE id = 1; DROP TABLE users'",
                    f"psql -d app -c '{DEL} users WHERE name = 1'",
                    f"psql -d app -c '{DEL} users WHERE id = 1' | sh",
                    f"psql -d app -c '{DEL} users WHERE id = 1' && rm -rf /srv",
                    "psql -d app -c 'TRUNCATE users'",
                    f"psql -d app -c \"{DEL} $T WHERE id = 1\"",
                    "psql -d app -f delete.sql",
                    f"ssh -o ProxyCommand=sh host1 'psql -d app -c \"{DEL} t WHERE id=1\"'"):
            self.assertIsNone(hcg.row_delete_targets(cmd), cmd)


class RowDeleteApproval(unittest.TestCase):
    def go(self, prompt: str, answer: str = "", rows: list | None = None) -> bool:
        hcg.APPROVAL_LOG = Path(__file__).with_name("_row_delete_audit.jsonl")
        try:
            return hcg._row_delete_approval(rows or ROWS, REMOTE, prompt, answer, {})[0]
        finally:
            hcg.APPROVAL_LOG.unlink(missing_ok=True)

    def test_bare_yes_to_block_approves(self) -> None:
        self.assertTrue(self.go("да", BLOCK))
        self.assertTrue(self.go("да, удаляй", BLOCK))

    def test_pasted_block_with_request_approves(self) -> None:
        self.assertTrue(self.go("удали\nбаза app_ops\nsmm_project 1\nsmm_account 1\nsmm_draft 1"))

    def test_other_requests_do_not_approve(self) -> None:
        self.assertFalse(self.go("удали тестовую группу, учётку и черновик"))   # rows not named
        self.assertFalse(self.go("удали smm_project 1 smm_account 1 smm_draft 1"))   # database not named
        self.assertFalse(self.go("удали app_ops smm_project 1 smm_account 1 smm_draft 1, smm_draft 1 сохрани"))
        self.assertFalse(self.go("да", "Удалю smm_project 1, smm_account 1, smm_draft 1 в app_ops"))   # no block
        self.assertFalse(self.go("да", BLOCK.replace("smm_draft 1", "smm_draft 2")))
        self.assertFalse(self.go("да", BLOCK.replace("app_ops", "app_other")))
        self.assertFalse(self.go("не удаляй app_ops smm_project 1 smm_account 1 smm_draft 1"))
        self.assertFalse(self.go("удалить app_ops smm_project 1 smm_account 1 smm_draft 1?"))
        self.assertFalse(self.go("посмотри app_ops smm_project 1 smm_account 1 smm_draft 1"))
        self.assertFalse(self.go("удали app_ops smm_project 12 smm_account 1 smm_draft 1"))   # 12 is not 1
        self.assertFalse(self.go("удали app_ops smm_project 1 smm_account 1 smm_draft 1",
                                 rows=ROWS + [("users", "1")]))

    def test_audit_record_names_rows(self) -> None:
        log = Path(__file__).with_name("_row_delete_record.jsonl")
        hcg.APPROVAL_LOG = log
        try:
            self.assertTrue(hcg._row_delete_approval(ROWS, REMOTE, "да", BLOCK, {"session_id": "s1"})[0])
            rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual((rec["action"], rec["rows"], rec["session"]),
                             ("row-delete", ["smm_draft 1", "smm_account 1", "smm_project 1", "database app_ops"],
                              "s1"))
        finally:
            log.unlink(missing_ok=True)

    def test_unwritable_audit_refuses(self) -> None:
        hcg.APPROVAL_LOG = Path(__file__) / "audit.jsonl"
        self.assertFalse(hcg._row_delete_approval(ROWS, REMOTE, "да", BLOCK, {})[0])


if __name__ == "__main__":
    unittest.main()
