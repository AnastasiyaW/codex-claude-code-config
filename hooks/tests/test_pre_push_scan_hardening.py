"""Regression: what a public push publishes must all be scanned (2026-10-28 audit).

Each test builds a real repository and a local bare remote, then runs the scanner's
main() end to end with only visibility, the material policy and the semantic model
call replaced. Every must-block case has a must-pass control next to it.

All credential-shaped values are assembled from fragments at run time: written as
literals they would trip the scanner that guards this public repository.

Run against another revision of the scanner with PRE_PUSH_SCAN_SCRIPT=<path>.
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(os.environ.get("PRE_PUSH_SCAN_SCRIPT")
              or Path(__file__).resolve().parents[1] / "pre-push-public-repo-scan.py")
SPEC = importlib.util.spec_from_file_location("pre_push_scan_hardening_target", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

ZERO = "0" * 40
KEY = "AK" + "IA" + "QZ" * 8                      # AWS access key id shape
HOME = "/" + "home/" + "fixtureuser/project"       # developer home path shape
SAFE = '{"verdict": "SAFE", "reason": "fixture"}'


# SOI, APP0 JFIF, SOS with two bytes of entropy data, EOI.
JPEG = (b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + b"\x12\x34" + b"\xff\xd9")


def png(*chunks: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    body = b"".join(chunk(k, d) for k, d in chunks)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + body
            + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""))


class Repo:
    """A work repository with an `origin` bare remote; machine hooks disabled."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.bare = root / "remote.git"
        self.work = root / "work"
        subprocess.run(["git", "init", "-q", "--bare", str(self.bare)], check=True, stdin=subprocess.DEVNULL, capture_output=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.work)], check=True, stdin=subprocess.DEVNULL, capture_output=True)
        (root / "no-hooks").mkdir()
        for key, value in (("core.hooksPath", str(root / "no-hooks")), ("user.name", "fixture"),
                           ("user.email", "fixture@example.invalid"), ("commit.gpgsign", "false"),
                           ("tag.gpgsign", "false"), ("core.autocrlf", "false")):
            self.git("config", key, value)
        self.git("remote", "add", "origin", str(self.bare))

    def git(self, *args: str, env: dict | None = None) -> str:
        r = subprocess.run(["git", *args], cwd=self.work, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env=env or os.environ.copy())
        if r.returncode:
            raise AssertionError(f"git {args}: {r.stderr}")
        return r.stdout.strip()

    def commit(self, files: dict[str, str | bytes], message: str = "change") -> str:
        for name, content in files.items():
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                path.unlink()
            elif isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8", newline="\n")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def publish(self) -> str:
        """Push main to the bare remote and fetch, so origin really has it."""
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")
        return self.git("rev-parse", "HEAD")


class ScanHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = Repo(Path(self._tmp.name))
        self.reviewed: list[str] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def scan(self, push_lines: list[str], env: dict | None = None) -> tuple[int, str]:
        def fake_b(claude, prompt, config_dir, api_key=None):
            self.reviewed.append(prompt)
            return subprocess.CompletedProcess(["claude"], 0, SAFE, "")

        old_argv, old_stdin, old_cwd = sys.argv, sys.stdin, os.getcwd()
        sys.argv = [str(SCRIPT), "origin", str(self.repo.bare)]
        sys.stdin = io.StringIO("".join(line + "\n" for line in push_lines))
        stderr = io.StringIO()
        try:
            os.chdir(self.repo.work)
            with (
                patch.dict(os.environ, env or {}),
                patch.object(MODULE, "parse_github_slug", return_value=("example", "public")),
                patch.object(MODULE, "repo_is_public", return_value=True),
                patch.object(MODULE, "pushed_material_problems", return_value=None),
                patch.object(MODULE, "find_claude_cli", return_value="claude.exe"),
                patch.object(MODULE, "_agent_b_call", side_effect=fake_b),
                contextlib.redirect_stderr(stderr),
            ):
                code = MODULE.main()
        finally:
            sys.argv, sys.stdin = old_argv, old_stdin
            os.chdir(old_cwd)
        return code, stderr.getvalue()

    def push_main(self, base: str) -> list[str]:
        tip = self.repo.git("rev-parse", "HEAD")
        return [f"refs/heads/main {tip} refs/heads/main {base}"]

    def assertBlocked(self, result: tuple[int, str], code: int = 1) -> None:
        self.assertEqual(code, result[0], result[1])

    def assertPassed(self, result: tuple[int, str]) -> None:
        self.assertEqual(0, result[0], result[1])

    # --- item 1: every commit, every message, every tag object ------------------

    def test_item1_key_added_then_deleted_in_same_push_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"cfg.txt": f"key = {KEY}\n"}, "add config")
        self.repo.commit({"cfg.txt": None}, "remove config")
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_item1_key_in_commit_message_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"a.txt": "base\nmore\n"}, f"use {KEY} for the bucket")
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_item1_key_in_annotated_tag_message_blocks(self) -> None:
        self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.git("tag", "-a", "v1", "-m", f"release; staging key {KEY}")
        tag = self.repo.git("rev-parse", "v1")
        self.assertBlocked(self.scan([f"refs/tags/v1 {tag} refs/tags/v1 {ZERO}"]))

    def test_item1_clean_annotated_tag_passes(self) -> None:
        self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.git("tag", "-a", "v1", "-m", "release notes, nothing secret")
        tag = self.repo.git("rev-parse", "v1")
        self.assertPassed(self.scan([f"refs/tags/v1 {tag} refs/tags/v1 {ZERO}"]))

    def test_item1_merge_with_content_no_parent_had_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "one\n"})
        self.repo.publish()
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.commit({"b.txt": "side\n"})
        self.repo.git("checkout", "-q", "main")
        self.repo.commit({"c.txt": "main\n"})
        self.repo.git("merge", "-q", "--no-ff", "--no-commit", "side")
        (self.repo.work / "a.txt").write_text(f"one\n{KEY}\n", encoding="utf-8")
        self.repo.git("add", "a.txt")
        self.repo.git("commit", "-q", "-m", "merge side")
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_item1_git_failure_is_not_checked(self) -> None:
        self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        missing = "1234567890abcdef1234567890abcdef12345678"
        self.assertBlocked(self.scan([f"refs/heads/x {missing} refs/heads/x {ZERO}"]), code=2)

    # --- item 2: the remote, not local tracking refs, says what is published ----

    def test_item2_forged_tracking_ref_does_not_hide_history(self) -> None:
        self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        tip = self.repo.commit({"cfg.txt": f"{KEY}\n"}, "add")
        self.repo.git("update-ref", "refs/remotes/origin/main", tip)  # stale or forged
        self.assertBlocked(self.scan([f"refs/heads/feature {tip} refs/heads/feature {ZERO}"]))

    def test_item2_remote_without_refs_scans_full_history(self) -> None:
        self.repo.commit({"cfg.txt": f"{KEY}\n"}, "root")
        tip = self.repo.commit({"cfg.txt": "clean\n"}, "clean up")
        self.repo.git("update-ref", "refs/remotes/origin/main", tip)  # e.g. after set-url
        self.assertBlocked(self.scan([f"refs/heads/main {tip} refs/heads/main {ZERO}"]))

    def test_item2_new_ref_on_published_history_reviews_only_the_ref_name(self) -> None:
        self.repo.commit({"cfg.txt": f"{KEY}\n"}, "root")  # already public on the remote
        tip = self.repo.publish()
        self.assertPassed(self.scan([f"refs/heads/copy {tip} refs/heads/copy {ZERO}"]))
        self.assertEqual(1, len(self.reviewed))
        self.assertIn("refs/heads/copy", self.reviewed[0])
        self.assertNotIn(KEY, self.reviewed[0])

    # --- item 3: external diff, injected config and textconv cannot empty it ----

    def test_item3_diff_rewriters_cannot_hide_content(self) -> None:
        cases = {
            "diff.external": ({"diff.external": "true"}, {}),
            "GIT_EXTERNAL_DIFF": ({}, {"GIT_EXTERNAL_DIFF": "true"}),
            "GIT_CONFIG_PARAMETERS": ({}, {"GIT_CONFIG_PARAMETERS": "'diff.external'='true'"}),
            "textconv": ({"diff.hide.textconv": "true"}, {}),
        }
        for label, (config, env) in cases.items():
            with self.subTest(label):
                self.tearDown()
                self.setUp()
                base = self.repo.commit({"a.txt": "base\n", ".gitattributes": "*.txt diff=hide\n"})
                self.repo.publish()
                for key, value in config.items():
                    self.repo.git("config", key, value)
                self.repo.commit({"cfg.txt": f"{KEY}\n"})
                self.assertBlocked(self.scan(self.push_main(base), env=env))

    # --- item 4: binary blobs are read as bytes; only images/fonts may pass -----

    def test_item4_key_in_png_text_chunk_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"logo.png": png((b"tEXt", b"Comment\x00" + KEY.encode()))})
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_item4_key_in_compressed_png_chunk_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"logo.png": png((b"zTXt", b"Comment\x00\x00" + zlib.compress(KEY.encode())))})
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_item4_plain_png_and_jpeg_pass(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"logo.png": png((b"tEXt", b"Software\x00fixture")),
                          "photo.jpg": JPEG})
        self.assertPassed(self.scan(self.push_main(base)))

    def test_item4_unknown_binary_blocks_and_is_named(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"tools/blob.bin": b"\x00\x01harmless\x00"})
        code, out = self.scan(self.push_main(base))
        self.assertEqual(1, code, out)
        self.assertIn("tools/blob.bin", out)

    def test_item4_text_disguised_as_png_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"note.png": b"\x00 plain text dressed as an image\n"})
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_item4_big_file_threshold_cannot_hide_text(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.git("config", "core.bigFileThreshold", "10")
        self.repo.commit({"cfg.txt": "padding " * 10 + KEY + "\n"})
        self.assertBlocked(self.scan(self.push_main(base)))

    # --- item 5: no silent truncation before the semantic reviewer -------------

    def test_item5_large_push_reaches_reviewer_in_full(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        tail = "tail-marker-" + "q" * 8
        self.repo.commit({"big.txt": "ordinary documentation line\n" * 9000 + tail + "\n"})
        self.assertPassed(self.scan(self.push_main(base)))
        self.assertGreater(len(self.reviewed), 1)
        self.assertTrue(any(tail in p for p in self.reviewed))
        self.assertTrue(all(len(p) < 2 * 120_000 for p in self.reviewed))

    def test_item5_push_over_review_budget_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"big.txt": "ordinary documentation line\n" * 9000})
        with patch.object(MODULE, "AGENT_B_MAX_CHUNKS", 1):
            self.assertBlocked(self.scan(self.push_main(base)), code=2)

    # --- item 6: regex gaps and the README exemption -------------------------

    def regex_hits(self, text: str, path: str = "docs/note.md") -> list:
        return MODULE.agent_a_regex(f"diff --git a/{path} b/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n+{text}\n")

    def test_item6_private_names_are_case_insensitive(self) -> None:
        names = dict(MODULE.PII_PATTERNS, private_names=r"\b(fixturehost)\b")
        with patch.object(MODULE, "PII_PATTERNS", names):
            checks = MODULE._compile_checks() if hasattr(MODULE, "_compile_checks") else None
            with patch.object(MODULE, "_CHECKS", checks, create=True):
                self.assertTrue(self.regex_hits("ssh FIXTUREHOST uptime"))
                self.assertTrue(self.regex_hits("ssh fixtureHost uptime"))
                self.assertFalse(self.regex_hits("ssh otherhost uptime"))

    def test_item6_email_addresses(self) -> None:
        at = "@"
        for leak in ("jane.roe" + at + "mailfixture" + ".net", "ops" + at + "corp-fixture" + ".io"):
            with self.subTest(leak):
                self.assertTrue(self.regex_hits(f"contact {leak}"))
        for fine in ("noreply" + at + "anthropic.com", "noreply" + at + "github.com",
                     "12345+someone" + at + "users.noreply.github.com", "icon" + at + "2x.png",
                     "dev" + at + "example.com"):
            with self.subTest(fine):
                self.assertFalse(self.regex_hits(f"contact {fine}"))

    def test_item6_private_ipv4(self) -> None:
        for leak in ("10." + "1.2.3", "172." + "20.0.5", "192." + "168.1.10", "100." + "100.5.6"):
            with self.subTest(leak):
                self.assertTrue(self.regex_hits(f"host {leak}:22"))
        for fine in ("8.8.8.8", "100.63.0.1", "172.32.0.1", "1.2.3.4"):
            with self.subTest(fine):
                self.assertFalse(self.regex_hits(f"host {fine}:22"))

    def test_item6_github_token_families(self) -> None:
        for prefix in ("o", "p", "s", "u"):
            with self.subTest(prefix):
                self.assertTrue(self.regex_hits("token " + "gh" + prefix + "_" + "Ab9" * 12))
        self.assertFalse(self.regex_hits("token gh" + "x_" + "Ab9" * 12))

    def test_item6_escaped_windows_home_paths(self) -> None:
        bs = "\\"
        for path in ("C" + ":" + bs * 2 + "Users" + bs * 2 + "fixtureuser" + bs * 2 + "repo",
                     "C" + ":" + bs * 4 + "Users" + bs * 4 + "fixtureuser",
                     "D" + ":/" + "Users/fixtureuser/repo"):
            with self.subTest(path):
                self.assertTrue(self.regex_hits(f'"cwd": "{path}"'))
        self.assertFalse(self.regex_hits('"cwd": "C:\\\\Users\\\\<you>\\\\repo"'))

    def test_item6_base64_wrapped_pem(self) -> None:
        pem = b"-----BEGIN " + b"OPENSSH PRIVATE" + b" KEY-----\nAAAAfixture\n"
        self.assertTrue(self.regex_hits("blob " + base64.b64encode(pem).decode()))
        self.assertTrue(self.regex_hits("blob x" + base64.b64encode(pem).decode()))  # misaligned
        self.assertFalse(self.regex_hits("blob " + base64.b64encode(b"just an ordinary sentence here").decode()))

    def test_item6_readme_exemption_is_by_full_path(self) -> None:
        with patch.object(MODULE, "_EXEMPT_PATHS", ["README.md"]):
            self.assertFalse([f for f in self.regex_hits(HOME, "README.md") if f.kind == "pii"])
            self.assertTrue([f for f in self.regex_hits(HOME, "docs/README.md") if f.kind == "pii"])
            self.assertTrue([f for f in self.regex_hits(KEY, "README.md") if f.kind == "secret"])

    # --- independent review findings (fresh-context reviewer, 2026-10-28) ---------

    def test_review_replace_ref_cannot_show_a_clean_twin(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        leaky = self.repo.commit({"cfg.txt": f"{KEY}\n"}, "add")
        self.repo.git("reset", "-q", "--hard", base)
        clean = self.repo.commit({"cfg.txt": "clean\n"}, "add")
        self.repo.git("replace", leaky, clean)
        self.assertBlocked(self.scan([f"refs/heads/x {leaky} refs/heads/x {ZERO}"]))

    def test_review_ls_remote_ignores_insteadof_rewrites(self) -> None:
        self.repo.commit({"cfg.txt": f"{KEY}\n"}, "root")
        tip = self.repo.git("rev-parse", "HEAD")
        mirror = self.repo.root / "mirror.git"
        subprocess.run(["git", "init", "-q", "--bare", str(mirror)], check=True, stdin=subprocess.DEVNULL, capture_output=True)
        self.repo.git("push", "-q", str(mirror), "main")  # the mirror already has it
        self.repo.git("config", f"url.{mirror.as_posix()}.insteadOf", self.repo.bare.as_posix())
        self.assertBlocked(self.scan([f"refs/heads/main {tip} refs/heads/main {ZERO}"]))

    def test_review_binary_needs_real_signature(self) -> None:
        for name, data in (("f.eot", b"PK\x03\x04\x00" + zlib.compress(KEY.encode())),
                           ("f.webp", b"RIFF\x00\x00\x00\x00WAVEfmt \x00"),
                           ("f.avif", b"\x00\x00\x00\x1cnot-an-image")):
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                base = self.repo.commit({"a.txt": "base\n"})
                self.repo.publish()
                self.repo.commit({name: data})
                self.assertBlocked(self.scan(self.push_main(base)))

    def test_review_utf16_text_in_image_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"p.jpg": b"\xff\xd8\xff\xe1\x00\x10" + KEY.encode("utf-16-le") + b"\x00\x00"})
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_review_extra_commit_header_and_identity_host(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        tree = self.repo.git("rev-parse", "HEAD^{tree}")
        raw = (f"tree {tree}\nparent {base}\nauthor f <f@example.invalid> 1 +0000\n"
               f"committer f <f@example.invalid> 1 +0000\nx-note {KEY}\n\nclean message\n")
        path = self.repo.root / "commit.txt"
        path.write_text(raw, encoding="utf-8", newline="\n")
        odd = self.repo.git("hash-object", "-t", "commit", "-w", str(path))
        self.assertBlocked(self.scan([f"refs/heads/x {odd} refs/heads/x {base}"]))
        host = "10." + "9.8.7"
        self.repo.git("reset", "-q", "--hard", base)
        env = dict(os.environ, GIT_AUTHOR_EMAIL=f"dev@{host}", GIT_COMMITTER_EMAIL=f"dev@{host}")
        (self.repo.work / "b.txt").write_text("b\n", encoding="utf-8")
        self.repo.git("add", "b.txt")
        self.repo.git("commit", "-q", "-m", "clean", env=env)
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_review_empty_file_name_is_scanned(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({f"keys/{KEY}.txt": ""})
        self.assertBlocked(self.scan(self.push_main(base)))

    def test_review_visibility_needs_an_explicit_answer(self) -> None:
        for out, want in (("false\n", True), ("true\n", False), ("", None), ("null\n", None)):
            with self.subTest(out), patch.object(
                    MODULE, "run", return_value=subprocess.CompletedProcess(["gh"], 0, out, "")):
                self.assertEqual(want, MODULE.repo_is_public("o", "r"))
        self.assertIsNone(MODULE.parse_github_slug("https://gitlab.com/x/github.com/o/r"))
        self.assertEqual(("o", "r"), MODULE.parse_github_slug("https://github.com/o/r.git"))
        self.assertEqual(("o", "r"), MODULE.parse_github_slug("git" + "@" + "github.com:o/r.git"))

    # --- second review round (coordinator, 2026-10-28) --------------------------

    def test_review2_tag_body_line_starting_with_tagger_is_scanned(self) -> None:
        self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.git("tag", "-a", "v2", "-m", "release\n\ntagger " + KEY)
        tag = self.repo.git("rev-parse", "v2")
        self.assertBlocked(self.scan([f"refs/tags/v2 {tag} refs/tags/v2 {ZERO}"]))

    def test_review2_png_with_bytes_after_iend_blocks(self) -> None:
        for label, tail in (("plain trailer", b"appended notes, nothing secret"),
                            ("key trailer", b"x" + KEY.encode() + b"y")):
            with self.subTest(label):
                self.tearDown()
                self.setUp()
                base = self.repo.commit({"a.txt": "base\n"})
                self.repo.publish()
                self.repo.commit({"logo.png": png() + tail})
                self.assertBlocked(self.scan(self.push_main(base)))

    def test_review2_binary_strings_reach_the_semantic_reviewer(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        marker = "semantic-review-marker"
        self.repo.commit({"logo.png": png((b"tEXt", b"Comment\x00" + marker.encode()))})
        self.assertPassed(self.scan(self.push_main(base)))
        self.assertTrue(any(marker in p for p in self.reviewed))

    # --- third review round (re-review of 808432c) --------------------------------

    def test_review3_remote_ref_names_are_scanned(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        ip = "10." + "20.30.40"
        for ref in (f"refs/heads/{KEY}", f"refs/heads/deploy-{ip}", f"refs/tags/{KEY}"):
            with self.subTest(ref):
                self.assertBlocked(self.scan([f"refs/heads/main {base} {ref} {ZERO}"]))

    def test_review3_only_structurally_valid_png_and_jpeg_pass(self) -> None:
        blocked = {
            "logo.gif": b"GIF89a\x01\x00\x01\x00\x00\x00\x00" + zlib.compress(KEY.encode()),
            "f.woff2": b"wOF2\x00\x01\x00\x00" + zlib.compress(b"any file"),
            "f.ttf": b"\x00\x01\x00\x00" + bytes(32),
            "f.ico": b"\x00\x00\x01\x00" + bytes(32),
            "p.jpg": JPEG + b"trailing",
            "q.jpg": JPEG[:2] + b"\xff\xef\x00\x06" + b"\x00" * 4 + JPEG[2:],  # APP15 segment
            "hidden.png": png((b"zzZz", zlib.compress(b"payload"))),       # unknown chunk
            "cut.png": png()[:-12],                                          # no IEND
        }
        for name, data in blocked.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                base = self.repo.commit({"a.txt": "base\n"})
                self.repo.publish()
                self.repo.commit({name: data})
                code, out = self.scan(self.push_main(base))
                self.assertEqual(1, code, out)
                self.assertIn(name, out)

    def test_review3_key_in_png_pixel_stream_blocks(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        sig_ihdr = png()[:8 + 25]
        body = zlib.compress(b"\x00\x00" + KEY.encode())
        idat = struct.pack(">I", len(body)) + b"IDAT" + body + struct.pack(">I", zlib.crc32(b"IDAT" + body))
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
        self.repo.commit({"logo.png": sig_ihdr + idat + iend})
        self.assertBlocked(self.scan(self.push_main(base)))

    def raw_commit(self, base: str, header_extra: str, author: str = "a <a@example.com>") -> str:
        tree = self.repo.git("rev-parse", "HEAD^{tree}")
        raw = (f"tree {tree}\nparent {base}\nauthor {author} 1700000000 +0000\n"
               f"committer a <a@example.com> 1700000000 +0000\n{header_extra}\nmsg\n")
        path = self.repo.root / "raw-commit.txt"
        path.write_text(raw, encoding="utf-8", newline="\n")
        return self.repo.git("hash-object", "-t", "commit", "-w", str(path))

    def test_review3_signature_header_is_scanned_and_validated(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        begin, end = "-----BEGIN PGP " + "SIGNATURE-----", "-----END PGP " + "SIGNATURE-----"
        for label, body in (("key in armour", f" {KEY}\n"), ("home in armour", f" {HOME}/\n"),
                            ("not base64", " this is not armour\n")):
            with self.subTest(label):
                c = self.raw_commit(base, f"gpgsig {begin}\n{body} {end}\n")
                self.assertBlocked(self.scan([f"refs/heads/main {c} refs/heads/main {base}"]))
        good = base64.b64encode(b"\x88\x5e\x04\x00signature bytes").decode()
        c = self.raw_commit(base, f"gpgsig {begin}\n \n {good}\n {end}\n")
        self.assertPassed(self.scan([f"refs/heads/main {c} refs/heads/main {base}"]))

    def test_review3_author_name_is_scanned(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        name = "ops" + "@" + "build-host" + ".internal " + "10." + "1.2.3"
        c = self.raw_commit(base, "", author=f"{name} <a@example.com>")
        self.assertBlocked(self.scan([f"refs/heads/main {c} refs/heads/main {base}"]))

    def test_review3_own_address_is_not_a_finding(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        own = "owner" + "@" + "mailfixture" + ".net"
        self.repo.git("config", "user.email", own)
        self.repo.commit({"b.txt": "b\n"})
        self.assertPassed(self.scan(self.push_main(base)))
        self.assertFalse(any(own in p for p in self.reviewed))

    def test_review3_regex_widening(self) -> None:
        at, fw_at, cyr_a = "@", "＠", "а"
        for leak in ("cd " + "/" + "home/alice", "open " + "/" + "Users/Bob", "C" + ":" + "\\Users\\Bob",
                     "host 192." + "168.001.010", "mail alice" + at + "gm" + cyr_a + "il.com",
                     "mail alice" + fw_at + "gmail.com"):
            with self.subTest(leak):
                self.assertTrue(self.regex_hits(leak))
        for fine in ("cd /usr/local", "version 1.2.3.4", "see docs" + at + "example.com"):
            with self.subTest(fine):
                self.assertFalse(self.regex_hits(fine))

    def test_control_clean_change_with_ordinary_readme_passes(self) -> None:
        base = self.repo.commit({"a.txt": "base\n"})
        self.repo.publish()
        self.repo.commit({"README.md": "# Fixture\n\nInstall with `pip install fixture`.\n",
                          "docs/README.md": "See the docs at https://docs.example.com/guide.\n"},
                         "docs: add readmes")
        self.assertPassed(self.scan(self.push_main(base)))
        self.assertEqual(1, len(self.reviewed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
