"""Paths inside `ssh <host> '...'` are remote POSIX paths, judged by path, never stat-ed here.

Case 2026-10-28: the owner said «да удали `repeat-guard.sh`; `test_repo_drift_watch.sh`;
`repo-drift-watch.sh` на сервере». The files sat in a server home under D:/tmp/... (Git Bash had
mangled a Windows path into that name). Windows lstat of a path with ':' raises an OSError,
the guard read that as "access denied" and refused the named files.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hcg", Path(__file__).resolve().parents[1] / "human-confirmation-guard.py")
hcg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hcg)

OWNER = "да удали `repeat-guard.sh`; `test_repo_drift_watch.sh`; `repo-drift-watch.sh` на контабо"
D = "/srv/deploy/D:/tmp/req-11f32e5e45e9-test"
FILES = ("repeat-guard.sh", "test_repo_drift_watch.sh", "repo-drift-watch.sh")


class RemotePathApproval(unittest.TestCase):
    def go(self, cmd: str, prompt: str = OWNER) -> tuple[bool, str]:
        saved_req, saved_log = hcg.owner_request, hcg.APPROVAL_LOG
        hcg.owner_request = lambda _p: (prompt, "")
        hcg.APPROVAL_LOG = Path(__file__).with_name("_remote_paths_audit.jsonl")
        try:
            return hcg.approved_by_owner(cmd, {"transcript_path": "x"})
        finally:
            hcg.APPROVAL_LOG.unlink(missing_ok=True)
            hcg.owner_request, hcg.APPROVAL_LOG = saved_req, saved_log

    def test_owner_named_files_on_server_pass(self) -> None:
        one = f"ssh vpshost 'rm \"{D}/repeat-guard.sh\"'"
        self.assertTrue(self.go(one)[0], self.go(one))
        three = "ssh vpshost 'rm " + " ".join(f'"{D}/{f}"' for f in FILES) + "'"
        self.assertTrue(self.go(three)[0], self.go(three))

    def test_unnamed_file_refused(self) -> None:
        ok, why = self.go(f"ssh vpshost 'rm \"{D}/other.sh\"'")
        self.assertFalse(ok, why)

    def test_recursive_folder_without_full_path_refused(self) -> None:
        ok, why = self.go(f"ssh vpshost 'rm -r \"{D}\"'")
        self.assertFalse(ok, why)

    def test_database_refused_unless_owner_names_it(self) -> None:
        ok, why = self.go(f"ssh vpshost 'rm \"{D}/state.db\"'")
        self.assertFalse(ok, why)

    def test_mask_refused(self) -> None:
        ok, why = self.go(f"ssh vpshost 'rm {D}/*.sh'")
        self.assertFalse(ok, why)

    def test_local_part_after_lone_ampersand_is_not_remote(self) -> None:
        # review 2026-10-28: `ssh h rm F&rm F` runs the second rm here; it must keep the local check
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="hcg-amp-"))
        f = d / "notes.bin"
        f.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
        try:
            p = f.as_posix()
            for cmd in (f"ssh h rm {p}&rm {p}", f"ssh h 'rm {p}'&rm {p}"):
                ok, why = self.go(cmd, "удали временные")
                self.assertFalse(ok, (cmd, why))
        finally:
            f.unlink()
            d.rmdir()

    def test_same_path_run_locally_in_unparsed_form_keeps_local_check(self) -> None:
        # review 2026-10-28 (HOLD): these run `rm`/`mv` on this machine too; the local SQLite
        # header must still be read even though an ssh segment names the same path
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="hcg-unparsed-"))
        f = d / "state.bin"
        f.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
        try:
            p = f.as_posix()
            for cmd in (f"ssh h rm {p}; mv {d.as_posix()}/new.bin {p}",
                        f"ssh h rm {p}; timeout 5 rm {p}",
                        f"ssh -o ProxyCommand='rm {p}' h rm {p}"):
                ok, why = self.go(cmd, "удали временные")
                self.assertFalse(ok, (cmd, why))
        finally:
            f.unlink()
            d.rmdir()

    def test_timeout_and_ssh_local_command_deletes_are_seen(self) -> None:
        # review 2026-10-28: both passed decide() with no check at all
        for cmd in ("timeout 5 rm C:/data/x.txt", "timeout -s KILL 5 rm C:/data/x.txt",
                    "timeout --foreground 1.5m rm C:/data/x.txt",
                    "ssh -o ProxyCommand='rm C:/data/x.txt' h ls",
                    "ssh -oLocalCommand=\"rm C:/data/x.txt\" h ls"):
            self.assertFalse(hcg.decide(cmd)[0], cmd)
        self.assertEqual(hcg.delete_targets("timeout -k 3 10 rm a b"), ["a", "b"])
        self.assertTrue(hcg.decide("ssh -o ProxyCommand='ssh -W %h:%p jump' h ls")[0])

    def test_ssh_options_that_run_local_code(self) -> None:
        # review 2026-10-28 round 2
        for cmd in ("ssh -4o ProxyCommand='rm C:/data/x.txt' h ls",
                    "ssh -4oProxyCommand='rm C:/data/x.txt' h ls",
                    "ssh -o ProxyCommand='rm C:/data/x.txt' h",
                    "ssh -o Match='exec \"rm C:/data/x.txt\"' h ls",
                    "sudo -u ssh ssh -o ProxyCommand='rm C:/data/x.txt' h ls",
                    "sudo -g ssh ssh -o LocalCommand='rm C:/data/x.txt' h ls"):
            self.assertFalse(hcg.decide(cmd)[0], cmd)
        # owner approval never covers a delete sent through ssh options that run code here
        for cmd in (f"ssh -o ProxyCommand='rm C:/data/x.txt' vpshost 'rm \"{D}/repeat-guard.sh\"'",
                    f"ssh -F cfg vpshost 'rm \"{D}/repeat-guard.sh\"'"):
            self.assertFalse(self.go(cmd)[0], cmd)
        # plain transport options keep the owner's named-file approval working
        ok_cmd = f"ssh -o BatchMode=yes vpshost 'rm \"{D}/repeat-guard.sh\"'"
        self.assertTrue(self.go(ok_cmd)[0], self.go(ok_cmd))

    def test_redirections_with_ampersand_still_parse(self) -> None:
        self.assertEqual(hcg.split_segments("rm a 2>&1"), ["rm a 2>&1"])
        self.assertEqual(hcg.split_segments("rm a &>/dev/null"), ["rm a &>/dev/null"])
        self.assertEqual(len(hcg.split_segments("rm a & rm b")), 2)

    def test_local_colon_path_still_checked_locally(self) -> None:
        # Not wrapped in ssh: still a local path, still fail-closed on an unreadable stat.
        ok, why = self.go(f"rm \"{D}/repeat-guard.sh\"")
        self.assertFalse(ok, why)


if __name__ == "__main__":
    unittest.main()
