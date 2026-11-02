"""Owner 2026-11-02: DROP DATABASE passes only when her own request asks to delete and names the database."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

DB = "scratch_drill_20260101"
REMOTE = f"ssh host1 'docker exec app-db-1 psql -U app -d postgres -c \"DROP DATABASE {DB}\"'"


class DbDropShape(unittest.TestCase):
    def test_drop_shapes(self) -> None:
        self.assertEqual(hcg.db_drop_targets(REMOTE), [DB])
        self.assertEqual(hcg.db_drop_targets(f"psql -U u -c 'DROP DATABASE IF EXISTS {DB};'"), [DB])
        self.assertEqual(hcg.db_drop_targets(REMOTE + " # claude-bypass: destructive"), [DB])

    def test_other_shapes_are_not_a_drop(self) -> None:
        for cmd in (f"psql -c 'DROP TABLE users'", f"psql -c 'DROP DATABASE {DB}; DROP DATABASE app'",
                    f"psql -c 'DROP DATABASE {DB}' | sh", f"psql -c 'DROP DATABASE {DB}' && rm -rf /srv",
                    f"psql -c 'DROP DATABASE {DB}'; docker volume rm pgdata", f"dropdb {DB}",
                    f"ssh -o ProxyCommand=sh host1'psql -c \"DROP DATABASE {DB}\"'",
                    f"psql -c \"DROP DATABASE $NAME\"", f"psql -f drop.sql"):
            self.assertIsNone(hcg.db_drop_targets(cmd), cmd)


class DbDropApproval(unittest.TestCase):
    def go(self, prompt: str, names: list[str] | None = None) -> bool:
        hcg.APPROVAL_LOG = Path(__file__).with_name("_db_drop_audit.jsonl")
        try:
            return hcg._db_drop_approval(names or [DB], REMOTE, prompt, {})[0]
        finally:
            hcg.APPROVAL_LOG.unlink(missing_ok=True)

    def test_named_request_approves(self) -> None:
        self.assertTrue(self.go(f"удали базу {DB}"))
        self.assertTrue(self.go(f"соглашаюсь на удаление пробной базы {DB}"))

    def test_other_requests_do_not_approve(self) -> None:
        self.assertFalse(self.go("соглашаюсь на удаление пробной базы"))   # not named
        self.assertFalse(self.go("да"))
        self.assertFalse(self.go("да, удаляй"))
        self.assertFalse(self.go(f"не удаляй {DB}"))
        self.assertFalse(self.go(f"удалить {DB}?"))
        self.assertFalse(self.go(f"посмотри {DB}"))
        self.assertFalse(self.go(f"удали {DB}_old"))   # a longer name is not this one
        self.assertFalse(self.go("удали базу postgres", ["postgres"]))
        self.assertFalse(self.go(f"удали {DB}", [DB, "app"]))

    def test_audit_record_names_the_database(self) -> None:
        import json
        log = Path(__file__).with_name("_db_drop_record.jsonl")
        hcg.APPROVAL_LOG = log
        try:
            self.assertTrue(hcg._db_drop_approval([DB], REMOTE, f"удали базу {DB}", {"session_id": "s1"})[0])
            rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual((rec["action"], rec["databases"], rec["session"]), ("db-drop", [DB], "s1"))
            self.assertIn("удали базу", log.read_text(encoding="utf-8"))
        finally:
            log.unlink(missing_ok=True)

    def test_unwritable_audit_refuses(self) -> None:
        hcg.APPROVAL_LOG = Path(__file__) / "audit.jsonl"   # parent is a file: the record cannot be written
        self.assertFalse(hcg._db_drop_approval([DB], REMOTE, f"удали {DB}", {})[0])


if __name__ == "__main__":
    unittest.main()
