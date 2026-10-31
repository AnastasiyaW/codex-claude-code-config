#!/usr/bin/env python3
"""Tests for capability_registry.py. Run: python scripts/test_capability_registry.py

The negative control N1 replays a real start: the big-frames branch had been on origin
for 2.5 days with no PR when a second line started "large-image memory" for the filter.
That start must be flagged.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, os.environ.get("CAPREG_DIR") or str(Path(__file__).resolve().parent))
import capability_registry as cr  # noqa: E402

VOCAB = {
    "large-image-memory": {
        "synonyms": ["big frames", "bigframes", "low-ram", "large document", "any-size", "staged apply"],
        "paths": ["src/converter/finalization_core*", "src/common/hsvc_v3/*"],
        "min_path_hits": 2,
    },
    "cabinet-ui": {"synonyms": ["cabinet"], "paths": ["server/internal/cabinet/*"]},
}
NUMBERING = {
    "adr": {"regex": r"^docs/adr/(\d{4})-(.+)\.md$", "dir": "docs/adr", "width": 4,
            "reservation_required_above": 62},
    "migration": {"regex": r"^server/migrations/(\d{3})_(.+?)\.(?:up|down)\.sql$",
                  "dir": "server/migrations", "width": 3},
}


def item(kind="pr", number=None, ref="x", base="master", title="", body="", subjects=(),
         files=(), first="2026-10-13T00:10:00Z", last="2026-10-13T05:45:00Z", shas=None):
    return {"kind": kind, "number": number, "ref": ref, "base": base, "title": title, "body": body,
            "subjects": list(subjects), "first_commit_at": first, "last_commit_at": last,
            "shas": list(shas) if shas is not None else [f"{ref}-{i}" for i in range(len(subjects) or 1)],
            "files": [f if isinstance(f, dict) else {"path": f, "sha": "s-" + f, "status": "added"}
                      for f in files]}


BIGFRAMES = item(kind="branch", ref="feature/big-frames-m0-m1",
                 subjects=["bigframes M1: finalize over the base buffer instead of a copy"],
                 files=["src/converter/finalization_core.cpp", "src/converter/protected_finalizer.cpp"])


def replay_20261015():
    return {"repo": "acme/app", "base": "master", "now": "2026-10-15T14:00:00Z",
            "items": [BIGFRAMES,
                      item(number=363, ref="feature/release-notes", title="Docs: release notes",
                           files=["docs/notes.md"])]}


class Check(unittest.TestCase):
    def run_check(self, snap, **kw):
        args = dict(caps=[], title="", paths=[], branch="", joins=[])
        args.update(kw)
        return cr.check(snap, VOCAB, args["caps"], args["title"], args["paths"], args["branch"], args["joins"])

    def test_n1_replay_flags_bigframes(self):
        findings, _ = self.run_check(replay_20261015(), caps=["large-image-memory"],
                                     paths=["src/plugin", "src/common"],
                                     branch="feature/filter-large-image-memory")
        self.assertEqual([f["ref"] for f in findings], ["feature/big-frames-m0-m1"])
        self.assertEqual(findings[0]["type"], "same-capability")

    def test_n1_variant_title_only(self):
        findings, _ = self.run_check(replay_20261015(), title="filter: admit large documents before copying them")
        self.assertEqual([f["ref"] for f in findings], ["feature/big-frames-m0-m1"])

    def test_cli_n1_exit_1_and_ack_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            snap, cfg = Path(d, "s.json"), Path(d, "c.json")
            snap.write_text(json.dumps(replay_20261015()), encoding="utf-8")
            cfg.write_text(json.dumps({"capabilities": VOCAB}), encoding="utf-8")
            base = ["check", "--snapshot", str(snap), "--config", str(cfg), "--capability", "large-image-memory"]
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cr.main(base), 1)
            self.assertIn("big-frames-m0-m1", out.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cr.main(base + ["--overlap-reason", "owner split the work"]), 0)
                self.assertEqual(cr.main(base + ["--joins", "feature/big-frames-m0-m1"]), 0)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cr.main(["check", "--snapshot", str(snap), "--config", str(cfg),
                                          "--capability", "no-such-thing"]), 2)
                self.assertEqual(cr.main(["check", "--snapshot", str(snap), "--config", str(cfg)]), 2)

    def test_declared_capability_line(self):
        snap = replay_20261015()
        snap["items"][1]["body"] = "Some text\nCapability: cabinet-ui, large-image-memory\n"
        findings, _ = self.run_check(snap, caps=["cabinet-ui"])
        self.assertEqual([f["number"] for f in findings], [363])

    def test_declared_in_commit_trailer(self):
        snap = replay_20261015()
        snap["items"][1]["subjects"] = ["docs: notes\n\nCapability: cabinet-ui"]
        self.assertEqual(len(self.run_check(snap, caps=["cabinet-ui"])[0]), 1)

    def test_path_hints_need_min_hits(self):
        one = item(kind="branch", number=1, ref="a", title="refactor", files=["src/converter/finalization_core.cpp"])
        two = item(kind="branch", number=2, ref="b", title="refactor", files=["src/converter/finalization_core.cpp",
                                                                "src/common/hsvc_v3/codec.cpp"])
        snap = {"base": "master", "now": "2026-10-15T14:00:00Z", "items": [one, two]}
        findings, _ = self.run_check(snap, caps=["large-image-memory"])
        self.assertEqual([f["number"] for f in findings], [2])

    def test_p2_joins_whole_stack(self):
        s1 = item(number=451, ref="stack/bigframes-1", title="Big frames 1/3")
        s2 = item(number=452, ref="stack/bigframes-2", base="stack/bigframes-1", title="Big frames 2/3")
        s3 = item(number=453, ref="stack/bigframes-3", base="stack/bigframes-2", title="Big frames 3/3")
        other = item(number=500, ref="claude/low-ram", title="Low-RAM: service peak")
        snap = {"base": "master", "now": "2026-10-25T00:00:00Z", "items": [s1, s2, s3, other]}
        findings, _ = self.run_check(snap, caps=["large-image-memory"], joins=["#452"])
        self.assertEqual([f["number"] for f in findings], [500])

    def test_p3_different_capability_disjoint_paths(self):
        findings, _ = self.run_check(replay_20261015(), caps=["cabinet-ui"], paths=["server/internal/cabinet"])
        self.assertEqual(findings, [])

    def test_heavy_path_overlap(self):
        files = [f"src/engine/f{i}.cpp" for i in range(10)]
        snap = {"base": "master", "now": "2026-10-15T14:00:00Z",
                "items": [item(number=7, ref="z", title="engine tidy", files=files),
                          item(number=8, ref="y", title="engine tidy", files=files[:9])]}
        findings, _ = self.run_check(snap, caps=["cabinet-ui"], paths=["src/engine"])
        self.assertEqual([(f["type"], f["number"]) for f in findings], [("path-overlap", 7)])
        findings, notes = self.run_check(snap, caps=["cabinet-ui"], paths=["src"])
        self.assertEqual(findings, [])
        self.assertTrue(notes)

    def test_title_alone_and_subject_first_line(self):
        by_title = item(number=11, ref="claude/x1", title="Any-size apply for the panel")
        by_subject = item(kind="branch", number=12, ref="claude/x2", subjects=["Staged apply: first band", "staged apply: second"])
        one_of_many = item(number=15, ref="claude/x5", subjects=["staged apply: one"] + [f"misc {i}" for i in range(9)])
        body_line = item(number=13, ref="claude/x3", subjects=["docs: notes\n\nnot big frames work"])
        by_ref = item(number=14, ref="feature/low-ram")
        snap = {"base": "master", "now": "2026-10-15T14:00:00Z", "items": [by_title, by_subject, body_line, by_ref, one_of_many]}
        findings, _ = self.run_check(snap, caps=["large-image-memory"])
        self.assertEqual([f["number"] for f in findings], [11, 12, 14])

    def test_default_min_path_hits_is_two(self):
        one = item(kind="branch", number=21, ref="a", files=["server/internal/cabinet/a.go"])
        two = item(kind="branch", number=22, ref="b", files=["server/internal/cabinet/a.go", "server/internal/cabinet/b.go"])
        snap = {"base": "master", "now": "2026-10-15T14:00:00Z", "items": [one, two]}
        findings, _ = self.run_check(snap, caps=["cabinet-ui"])
        self.assertEqual([f["number"] for f in findings], [22])

    def test_glob_and_exact_file_areas(self):
        files = [f"src/engine/f{i}.cpp" for i in range(10)]
        snap = {"base": "master", "now": "2026-10-15T14:00:00Z",
                "items": [item(number=31, ref="g", title="t", files=files)]}
        self.assertEqual(len(self.run_check(snap, caps=["cabinet-ui"], paths=["src/engine/*.cpp"])[0]), 1)
        self.assertEqual(self.run_check(snap, caps=["cabinet-ui"], paths=["src/engine/*.h"])[0], [])
        one, _ = cr.check(snap, VOCAB, ["cabinet-ui"], "", ["src/engine/f1.cpp"], "", [], overlap_files=1)
        self.assertEqual(one[0]["files"], 1)
        f, _ = cr.check(snap, VOCAB, ["cabinet-ui"], "", list(files), "", [], overlap_files=10)
        self.assertEqual(f[0]["example"], files[:3])
        self.assertEqual(f[0]["files"], 10)

    def test_own_branch_is_skipped(self):
        findings, _ = self.run_check(replay_20261015(), caps=["large-image-memory"],
                                     branch="feature/big-frames-m0-m1")
        self.assertEqual(findings, [])


class CheckRef(unittest.TestCase):
    def snap(self):
        unify = item(number=386, ref="integration/unify", title="Integration: low-RAM and any-size apply",
                     files=["src/converter/finalization_core.cpp", "docs/x.md"])
        s1 = item(number=451, ref="stack/bigframes-1", title="Big frames 1/2", files=["src/a/b.cpp"])
        s2 = item(number=452, ref="stack/bigframes-2", base="stack/bigframes-1", title="Big frames 2/2",
                  files=["src/a/c.cpp"])
        other = item(number=9, ref="cabinet", title="cabinet css", files=["server/internal/cabinet/x.css"])
        return {"base": "master", "now": "2026-10-25T00:00:00Z", "items": [unify, s1, s2, other]}

    def test_stack_member_sees_the_other_line_not_its_own(self):
        findings, _, reason = cr.check_ref(self.snap(), VOCAB, "stack/bigframes-2")
        self.assertEqual(([f["number"] for f in findings], reason), ([386], ""))

    def test_body_joins_and_reason(self):
        snap = self.snap()
        snap["items"][2]["body"] = "Joins: #386\n"
        self.assertEqual(cr.check_ref(snap, VOCAB, "stack/bigframes-2")[0], [])
        snap["items"][2]["body"] = "Overlap-reason: owner keeps both lines until the merge\n"
        findings, _, reason = cr.check_ref(snap, VOCAB, "stack/bigframes-2")
        self.assertEqual((len(findings), reason), (1, "owner keeps both lines until the merge"))

    def test_path_overlap_by_exact_files(self):
        snap = self.snap()
        shared = [f"src/engine/f{i}.cpp" for i in range(10)]
        snap["items"] += [item(number=60, ref="p60", title="t", files=shared),
                          item(number=61, ref="p61", title="u", files=shared + ["src/engine/z.cpp"])]
        findings, _, _ = cr.check_ref(snap, VOCAB, "p60")
        self.assertEqual([(f["type"], f["number"]) for f in findings], [("path-overlap", 61)])

    def test_unknown_ref_and_empty_item(self):
        with self.assertRaises(ValueError):
            cr.check_ref(self.snap(), VOCAB, "nope")
        snap = self.snap()
        snap["items"].append(item(number=70, ref="empty", title="t"))
        findings, notes, _ = cr.check_ref(snap, VOCAB, "empty")
        self.assertEqual((findings, len(notes)), ([], 1))

    def test_cli_ref(self):
        with tempfile.TemporaryDirectory() as d:
            snap, cfg = Path(d, "s.json"), Path(d, "c.json")
            data = self.snap()
            snap.write_text(json.dumps(data), encoding="utf-8")
            cfg.write_text(json.dumps({"capabilities": VOCAB}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cr.main(["check", "--snapshot", str(snap), "--config", str(cfg), "--ref", "stack/bigframes-2"]), 1)
                self.assertEqual(cr.main(["check", "--snapshot", str(snap), "--config", str(cfg), "--ref", "cabinet"]), 0)
                data["items"][2]["body"] = "Overlap-reason: agreed"
                snap.write_text(json.dumps(data), encoding="utf-8")
                self.assertEqual(cr.main(["check", "--snapshot", str(snap), "--config", str(cfg), "--ref", "stack/bigframes-2"]), 0)


class Lines(unittest.TestCase):
    def test_shared_commit_is_one_line(self):
        a = item(number=1, ref="a", title="Big frames M1", shas=["c1", "c2"])
        b = item(number=2, ref="integration/unify", title="Big frames and more", shas=["c1", "x"])
        c = item(number=3, ref="c", title="Low-RAM peak", shas=["y"])
        snap = {"base": "master", "now": "2026-10-25T00:00:00Z", "items": [a, b, c]}
        findings, _, _ = cr.check_ref(snap, VOCAB, "a")
        self.assertEqual([f["number"] for f in findings], [3])

    def test_rebased_copy_is_the_same_line(self):
        a = item(number=1, ref="stack/1", title="Big frames 1", shas=["new1"])
        a["commit_keys"] = ["bigframes M1|2026-10-13T00:10:00Z"]
        old = item(kind="branch", ref="claude/big-frames-old", subjects=["bigframes M1", "bigframes M2"], shas=["old1"])
        old["commit_keys"] = ["bigframes M1|2026-10-13T00:10:00Z"]
        other = item(kind="branch", ref="claude/big-frames-other", subjects=["bigframes M1", "bigframes M2"], shas=["o"])
        other["commit_keys"] = ["bigframes M1|2026-10-20T00:00:00Z"]
        snap = {"base": "master", "now": "2026-10-25T00:00:00Z", "items": [a, old, other]}
        findings, _, _ = cr.check_ref(snap, VOCAB, "stack/1")
        self.assertEqual([f["ref"] for f in findings], ["claude/big-frames-other"])

    def test_pr_without_declaration_is_judged_by_title(self):
        pr = item(number=7, ref="claude/x", title="misc tidy", subjects=["big frames a", "big frames b"],
                  files=["src/converter/finalization_core.cpp", "src/common/hsvc_v3/codec.cpp"])
        br = item(kind="branch", ref="claude/y", subjects=["big frames a", "big frames b"])
        snap = {"base": "master", "now": "2026-10-25T00:00:00Z", "items": [pr, br]}
        findings, _ = cr.check(snap, VOCAB, ["large-image-memory"], "", [], "", [])
        self.assertEqual([f["ref"] for f in findings], ["claude/y"])

    def test_declared_line_is_taken_at_its_word(self):
        mine = item(number=1, ref="mine", title="cabinet tweak, not big frames", body="Capability: cabinet-ui")
        theirs = item(number=2, ref="theirs", title="Big frames M1", body="Capability: cabinet-ui")
        silent = item(number=3, ref="silent", title="Big frames M2")
        snap = {"base": "master", "now": "2026-10-25T00:00:00Z", "items": [mine, theirs, silent]}
        findings, _, _ = cr.check_ref(snap, VOCAB, "mine")
        self.assertEqual([f["ref"] for f in findings], ["theirs"])
        f2, _ = cr.check(snap, VOCAB, ["large-image-memory"], "", [], "", [])
        self.assertEqual([f["ref"] for f in f2], ["silent"])

    def test_aggregate_refs_count_only_declared(self):
        agg = item(number=386, ref="integration/unify", title="Integration: low-RAM, cabinet, everything",
                   files=[f"src/engine/f{i}.cpp" for i in range(20)], shas=["u"])
        me = item(number=5, ref="me", title="cabinet tweak", files=[f"src/engine/f{i}.cpp" for i in range(20)], shas=["m"])
        snap = {"base": "master", "now": "2026-10-25T00:00:00Z", "items": [agg, me]}
        self.assertEqual(len(cr.check_ref(snap, VOCAB, "me")[0]), 1)
        self.assertEqual(cr.check_ref(snap, VOCAB, "me", aggregate=["integration/*"])[0], [])
        agg["body"] = "Capability: cabinet-ui"
        self.assertEqual(len(cr.check_ref(snap, VOCAB, "me", aggregate=["integration/*"])[0]), 1)
        findings, notes, _ = cr.check_ref(snap, VOCAB, "integration/unify", aggregate=["integration/*"])
        self.assertEqual((findings, len(notes)), ([], 1))

    def test_russian_title(self):
        vocab = {"cabinet-ui": {"synonyms": ["кабинет"]}}
        it = item(number=410, ref="claude/x", title="Кабинет: устройства «N из M»")
        snap = {"base": "master", "now": "2026-10-25T00:00:00Z", "items": [it]}
        self.assertEqual(len(cr.check(snap, vocab, ["cabinet-ui"], "", [], "", [])[0]), 1)
        self.assertEqual(cr.synonym_hits("подкабинет", vocab["cabinet-ui"], "cabinet-ui"), [])


class Orphans(unittest.TestCase):
    def test_n4_thirty_hours(self):
        snap = {"base": "master", "now": "2026-10-14T06:10:00Z", "items": [BIGFRAMES]}
        found = cr.orphans(snap, 24)
        self.assertEqual([o["ref"] for o in found], [BIGFRAMES["ref"]])
        self.assertEqual((found[0]["age_hours"], found[0]["commits"]), (30.0, 1))
        self.assertEqual(cr.orphans(snap, 31), [])
        snap["now"] = "2026-10-14T06:40:00Z"
        self.assertEqual(cr.orphans(snap, 24)[0]["age_hours"], 30.5)
        snap["now"] = "2026-11-23T16:10:00Z"
        self.assertEqual(cr.orphans(snap, 24)[0]["age_hours"], 1000.0)

    def test_exactly_at_the_limit_counts(self):
        snap = {"base": "master", "now": "2026-10-14T00:10:00Z", "items": [BIGFRAMES]}
        self.assertEqual(len(cr.orphans(snap, 24)), 1)
        snap["now"] = "2026-10-14T00:09:59Z"
        self.assertEqual(cr.orphans(snap, 24), [])

    def test_dormant_branches_are_listed(self):
        snap = {"base": "master", "now": "2026-10-14T06:10:00Z", "items": [], "dormant_branches": ["old"]}
        self.assertEqual(cr.orphans(snap, 24), [{"type": "dormant-branch", "item": "branch old (no PR, idle)", "ref": "old"}])

    def test_prs_are_never_orphans(self):
        snap = {"base": "master", "now": "2026-12-01T00:00:00Z", "items": [item(number=3, ref="p")]}
        self.assertEqual(cr.orphans(snap, 24), [])


class Numbers(unittest.TestCase):
    def snap(self, *items, base_files=None, reservations=()):
        return {"base": "master", "now": "2026-10-25T00:00:00Z", "items": list(items),
                "base_files": base_files or {}, "reservations": [{"ref": r} for r in reservations]}

    def test_n2_adr_collision(self):
        a = item(number=386, ref="integration/unify", files=["docs/adr/0057-one-deploy-path.md"])
        b = item(number=457, ref="stack/bigframes-6", files=["docs/adr/0057-v4-streamed-admission.md"])
        findings, seen = cr.number_collisions(self.snap(a, b), NUMBERING)
        self.assertEqual(seen, 2)
        self.assertEqual([(f["kind"], f["number"]) for f in findings], [("adr", 57)])

    def test_n2_migration_collision_and_up_down_pair(self):
        a = item(number=332, ref="replay", files=["server/migrations/105_trial_replay.up.sql",
                                                 "server/migrations/105_trial_replay.down.sql"])
        self.assertEqual(cr.number_collisions(self.snap(a), NUMBERING)[0], [])
        b = item(number=418, ref="offers", files=["server/migrations/105_post_trial_offers.up.sql"])
        findings, _ = cr.number_collisions(self.snap(a, b), NUMBERING)
        self.assertEqual([(f["kind"], f["number"]) for f in findings], [("migration", 105)])

    def test_p1_stacked_identical_file_counts_once(self):
        f = {"path": "docs/adr/0057-v4-streamed-admission.md", "sha": "blob1", "status": "added"}
        a = item(number=457, ref="s6", files=[f])
        b = item(number=458, ref="s7", base="s6", files=[dict(f, sha="blob2")])
        self.assertEqual(cr.number_collisions(self.snap(a, b), NUMBERING)[0], [])

    def test_collision_with_base(self):
        a = item(number=5, ref="x", files=["docs/adr/0054-other.md"])
        findings, _ = cr.number_collisions(self.snap(a, base_files={"adr": ["docs/adr/0054-per-release-uninstaller.md"]}), NUMBERING)
        self.assertEqual(len(findings), 1)

    def test_modified_file_is_not_an_allocation(self):
        a = item(number=5, ref="x", files=[{"path": "docs/adr/0054-other.md", "sha": "b", "status": "modified"}])
        findings, seen = cr.number_collisions(self.snap(a, base_files={"adr": ["docs/adr/0054-per-release-uninstaller.md"]}), NUMBERING)
        self.assertEqual((findings, seen), ([], 1))

    def test_pr_filter(self):
        a = item(number=1, ref="a", files=["docs/adr/0057-x.md"])
        b = item(number=2, ref="b", files=["docs/adr/0057-y.md"])
        c = item(number=3, ref="c", files=["docs/adr/0040-z.md"])
        s = self.snap(a, b, c)
        self.assertEqual(len(cr.number_collisions(s, NUMBERING, scope="b")[0]), 1)
        self.assertEqual(cr.number_collisions(s, NUMBERING, scope="c")[0], [])
        self.assertEqual(cr.number_collisions(s, NUMBERING, scope="master")[0], [])
        self.assertEqual(cr.number_collisions(s, NUMBERING, scope="not-in-flight")[0], [])
        self.assertEqual(len(cr.number_collisions(s, NUMBERING, scope=None)[0]), 1)
        on_base = self.snap(a, base_files={"adr": ["docs/adr/0057-y.md"]})
        self.assertEqual(cr.number_collisions(on_base, NUMBERING, scope="master")[0], [])
        self.assertEqual(len(cr.number_collisions(on_base, NUMBERING, scope="a")[0]), 1)
        twice = self.snap(base_files={"adr": ["docs/adr/0057-y.md", "docs/adr/0057-z.md"]})
        self.assertEqual(len(cr.number_collisions(twice, NUMBERING, scope="master")[0]), 1)

    def test_unreserved_above_limit(self):
        a = item(number=9, ref="a", files=["docs/adr/0063-new.md"])
        findings, _ = cr.number_collisions(self.snap(a), NUMBERING)
        self.assertEqual([f["type"] for f in findings], ["number-unreserved"])
        ok = self.snap(a, reservations=["refs/reservations/adr/0063"])
        self.assertEqual(cr.number_collisions(ok, NUMBERING)[0], [])
        other = item(number=10, ref="b", files=["docs/adr/0040-old.md"])
        self.assertEqual(cr.number_collisions(self.snap(a, other), NUMBERING, scope="b")[0], [])
        self.assertEqual(len(cr.number_collisions(self.snap(a, other), NUMBERING, scope="a")[0]), 1)
        low = item(number=9, ref="a", files=["docs/adr/0062-new.md"])
        self.assertEqual(cr.number_collisions(self.snap(low), NUMBERING)[0], [])

    def test_zero_numbered_files_is_not_checked(self):
        with tempfile.TemporaryDirectory() as d:
            snap, cfg = Path(d, "s.json"), Path(d, "c.json")
            snap.write_text(json.dumps(self.snap(item(number=1, ref="a", files=["README.md"]))), encoding="utf-8")
            cfg.write_text(json.dumps({"numbering": NUMBERING}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cr.main(["numbers", "--snapshot", str(snap), "--config", str(cfg)]), 2)


class Cli(unittest.TestCase):
    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cr.main(args)
        return code, out.getvalue(), err.getvalue()

    def files(self, d, snap, cfg):
        sp, cp = Path(d, "s.json"), Path(d, "c.json")
        sp.write_text(json.dumps(snap), encoding="utf-8")
        cp.write_text(json.dumps(cfg), encoding="utf-8")
        return str(sp), str(cp)

    def test_orphans_and_numbers_exit_codes(self):
        snap = {"base": "master", "now": "2026-10-14T06:10:00Z", "items": [BIGFRAMES], "base_files": {}}
        clean = {"base": "master", "now": "2026-10-13T01:00:00Z", "items": [BIGFRAMES], "base_files": {}}
        with tempfile.TemporaryDirectory() as d:
            sp, cp = self.files(d, snap, {"numbering": NUMBERING})
            self.assertEqual(self.run_cli(["orphans", "--snapshot", sp])[0], 1)
            Path(d, "clean.json").write_text(json.dumps(clean), encoding="utf-8")
            self.assertEqual(self.run_cli(["orphans", "--snapshot", str(Path(d, "clean.json"))])[0], 0)
            twice = dict(snap, items=[item(number=1, ref="a", files=["docs/adr/0057-x.md"]),
                                      item(number=2, ref="b", files=["docs/adr/0057-y.md"])])
            Path(d, "twice.json").write_text(json.dumps(twice), encoding="utf-8")
            self.assertEqual(self.run_cli(["numbers", "--snapshot", str(Path(d, "twice.json")), "--config", cp])[0], 1)
            once = dict(twice, items=twice["items"][:1])
            Path(d, "once.json").write_text(json.dumps(once), encoding="utf-8")
            code, out, _ = self.run_cli(["numbers", "--snapshot", str(Path(d, "once.json")), "--config", cp])
            self.assertEqual(code, 0)
            self.assertIn("numbered_files=1", out)

    def test_missing_repo_messages(self):
        code, _, err = self.run_cli(["check", "--capability", "x"])
        self.assertEqual(code, 2)
        self.assertIn("check needs --repo or --snapshot", err)
        code, _, err = self.run_cli(["reserve", "--kind", "adr"])
        self.assertIn("reserve needs --repo", err)
        self.assertNotIn("--snapshot", err)

    def test_reserve_cli(self):
        with tempfile.TemporaryDirectory() as d:
            _, cp = self.files(d, {}, {"numbering": NUMBERING})
            real_collect, real_refs = cr.collect, cr.LiveRefs
            cr.collect = lambda repo, numbering=None: {"base": "master", "items": [], "base_files": {"adr": []}}
            cr.LiveRefs = lambda repo: FakeRefs(set())
            try:
                code, out, _ = self.run_cli(["reserve", "--repo", "o/r", "--config", cp, "--kind", "adr", "--slug", "s"])
                self.assertEqual((code, out), (0, "0001\n"))
                code, _, err = self.run_cli(["reserve", "--repo", "o/r", "--config", cp, "--kind", "nope"])
                self.assertEqual(code, 2)
                self.assertIn("not in config numbering", err)
            finally:
                cr.collect, cr.LiveRefs = real_collect, real_refs

    def test_snapshot_file_keeps_unicode_and_indent(self):
        with tempfile.TemporaryDirectory() as d:
            cache, out = Path(d, "c.json"), Path(d, "o.json")
            now = cr.dt.datetime.now(cr.dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            cache.write_text(json.dumps({"repo": "o/r", "base": "master", "now": now, "dormant_branches": [],
                                         "reservations": [], "items": [item(number=1, ref="a", title="Кабинет")]}),
                             encoding="utf-8")
            self.assertEqual(self.run_cli(["snapshot", "--repo", "o/r", "--out", str(out), "--reuse", str(cache)])[0], 0)
            raw = out.read_text(encoding="utf-8")
            self.assertIn('"title": "Кабинет"', raw)
            self.assertTrue(raw.startswith('{\n "repo"'))


class FakeRefs:
    def __init__(self, taken):
        self.taken, self.created = set(taken), []

    def head_sha(self, branch):
        self.head_of = branch
        return "abc"

    def create(self, ref, sha, message):
        if ref in self.taken:
            return False
        self.taken.add(ref)
        self.created.append((ref, json.loads(message)))
        return True


class Reserve(unittest.TestCase):
    def test_next_number_sees_base_prs_and_refs(self):
        snap = {"base": "master", "items": [item(files=["docs/adr/0058-x.md"])],
                "base_files": {"adr": ["docs/adr/0056-y.md", "docs/adr/README.md"]},
                "reservations": [{"ref": "refs/reservations/adr/0057"}, {"ref": "refs/reservations/migration/200"},
                                 {"ref": "refs/reservations/mig/0999"}, {"ref": "refs/reservations/adr/x"}]}
        self.assertEqual(cr.next_number(snap, NUMBERING["adr"], "adr"), 59)
        self.assertEqual(cr.next_number({"base": "master", "items": [item()]}, NUMBERING["adr"], "adr"), 1)

    def test_collision_retries_next(self):
        snap = {"base": "master", "items": [], "base_files": {"adr": ["docs/adr/0061-a.md"]}}
        refs = FakeRefs({"refs/reservations/adr/0062", "refs/reservations/adr/0063"})
        self.assertEqual(cr.reserve(refs, snap, NUMBERING["adr"], "adr", "slug", "b"), 64)
        self.assertEqual(refs.created[0][1], {"kind": "adr", "number": 64, "slug": "slug", "branch": "b"})
        self.assertEqual(refs.head_of, "b")
        cr.reserve(refs, snap, NUMBERING["adr"], "adr", "slug", "")
        self.assertEqual((refs.head_of, refs.created[-1][0]), ("master", "refs/reservations/adr/0065"))

    def test_all_taken_is_not_checked(self):
        snap = {"base": "master", "items": [], "base_files": {}}
        refs = FakeRefs({f"refs/reservations/adr/{n:04d}" for n in range(1, 200)})
        with self.assertRaises(cr.NotChecked):
            cr.reserve(refs, snap, NUMBERING["adr"], "adr", "s", "")


class FakeAPI:
    """Stands in for capability_registry.http(): routes by method + path."""

    def __init__(self, routes, calls=None):
        self.routes, self.calls = routes, calls if calls is not None else []

    def __call__(self, method, url, payload=None):
        path = url.replace(cr.API + "/", "")
        self.calls.append((method, path, payload))
        for (m, prefix), answer in sorted(self.routes.items(), key=lambda kv: -len(kv[0][1])):
            if m == method and path.startswith(prefix):
                return answer(path, payload) if callable(answer) else answer
        raise AssertionError(f"unexpected call {method} {path}")


def ref_node(name, date, prs=()):
    return {"name": name, "target": {"committedDate": date}, "associatedPullRequests": {"nodes": list(prs)}}


def pr_node(number, head, commits=1, files=1, total_commits=None, total_files=None):
    return {"number": number, "title": "t", "body": None, "headRefName": head, "baseRefName": "master",
            "createdAt": "2025-10-01T00:00:00Z",
            "commits": {"totalCount": total_commits or commits,
                        "nodes": [{"commit": {"oid": f"o{number}{i}", "message": f"c{i}", "committedDate": f"2025-10-2{i}T00:00:00Z",
                                             "authoredDate": f"2025-10-0{i}T00:00:00Z"}}
                                  for i in range(commits)]},
            "files": {"totalCount": total_files or files,
                      "nodes": [{"path": f"src/f{i}.cpp", "changeType": "ADDED"} for i in range(files)]}}


def page(key, nodes, next_cursor=None):
    return {"data": {"repository": {key: {"pageInfo": {"hasNextPage": bool(next_cursor), "endCursor": next_cursor},
                                          "nodes": nodes}}}}


class Live(unittest.TestCase):
    """collect() and reserve against a fake GitHub: selection, pagination, fail-closed."""

    def setUp(self):
        self.real = cr.http
        cr._TOKEN[:] = ["test-token"]

    def tearDown(self):
        cr.http = self.real
        cr._TOKEN[:] = []

    def graphql(self, path, payload):
        q, cursor = payload["query"], payload["variables"]["endCursor"]
        if "pullRequests" in q:
            if cursor is None:
                return 200, page("pullRequests", [pr_node(1, "open-pr")], "p2"), ""
            return 200, page("pullRequests", [pr_node(2, "big-pr", commits=2, files=1, total_commits=3, total_files=2)]), ""
        nodes = [ref_node("master", "2025-10-29T00:00:00Z"), ref_node("open-pr", "2025-10-29T00:00:00Z"),
                 ref_node("fresh-orphan", "2025-10-28T00:00:00Z"),
                 ref_node("old-orphan", "2025-09-01T00:00:00Z"),
                 ref_node("merged-done", "2025-10-20T00:00:00Z",
                          [{"number": 9, "state": "MERGED", "closedAt": "2025-10-21T00:00:00Z"}]),
                 ref_node("merged-reused", "2025-10-25T00:00:00Z",
                          [{"number": 8, "state": "MERGED", "closedAt": "2025-10-21T00:00:00Z"}]),
                 ref_node("even", "2025-10-28T00:00:00Z")]
        return 200, page("refs", nodes), ""

    def compare(self, path, payload):
        name = urllib.parse.unquote(path.rsplit("...", 1)[1])
        if name == "even":
            return 200, {"ahead_by": 0}, ""
        if name == "merged-reused":
            return 200, {"ahead_by": 2, "commits": [
                {"sha": "x2", "commit": {"message": "late", "committer": {"date": "2025-10-25T00:00:00Z"},
                                          "author": {"date": "2025-10-02T00:00:00Z"}}},
                {"sha": "x1", "commit": {"message": "early", "committer": {"date": "2025-10-22T00:00:00Z"},
                                          "author": {"date": "2025-10-01T00:00:00Z"}}}]}, ""
        return 200, {"ahead_by": 1, "files": [{"filename": "f", "status": "added"}],
                     "commits": [{"sha": "b" + name, "commit": {"message": "c", "committer": {"date": "2025-10-27T00:00:00Z"},
                                                                 "author": {"date": "2025-10-03T00:00:00Z"}}}]}, ""

    def routes(self, over=None):
        r = {("GET", "repos/o/r/compare/"): self.compare,
             ("GET", "repos/o/r/pulls/2/commits"): (200, [{"sha": f"r{i}", "commit": {"message": f"m{i}\nbody", "committer": {"date": f"2025-10-1{i}T00:00:00Z"},
                                                    "author": {"date": f"2025-09-0{i}T00:00:00Z"}}} for i in range(3)], ""),
             ("GET", "repos/o/r/pulls/2/files"): (200, [{"filename": "a", "status": "added"}, {"filename": "b", "status": "removed"}], ""),
             ("GET", "repos/o/r/git/matching-refs/reservations/"): (200, [{"ref": "refs/reservations/adr/0063"}], ""),
             ("GET", "repos/o/r"): (200, {"default_branch": "master"}, ""),
             ("POST", "graphql"): self.graphql}
        r.update(over or {})
        return r

    def test_collect_selection_and_pagination(self):
        calls = []
        cr.http = FakeAPI(self.routes(), calls)
        snap = cr.collect("o/r", now=cr._ts("2025-10-30T00:00:00Z"))
        compared = sorted(urllib.parse.unquote(p.rsplit("...", 1)[1]) for m, p, _ in calls if "compare" in p)
        self.assertEqual(compared, ["even", "fresh-orphan", "merged-reused"])
        by_ref = {i["ref"]: i for i in snap["items"]}
        self.assertEqual(sorted(by_ref), ["big-pr", "fresh-orphan", "merged-reused", "open-pr"])
        self.assertEqual(snap["dormant_branches"], ["old-orphan"])
        self.assertNotIn("base_files", snap)
        self.assertEqual(snap["reservations"], [{"ref": "refs/reservations/adr/0063"}])
        self.assertEqual(snap["now"], "2025-10-30T00:00:00Z")
        big = by_ref["big-pr"]
        self.assertEqual(big["subjects"], ["m0\nbody", "m1\nbody", "m2\nbody"])
        self.assertEqual(big["commit_keys"], [f"m{i}|2025-09-0{i}T00:00:00Z" for i in range(3)])
        self.assertEqual(by_ref["open-pr"]["commit_keys"], ["c0|2025-10-00T00:00:00Z"])
        self.assertEqual(by_ref["merged-reused"]["commit_keys"],
                         ["late|2025-10-02T00:00:00Z", "early|2025-10-01T00:00:00Z"])
        self.assertEqual(big["shas"], ["r0", "r1", "r2"])
        self.assertEqual(by_ref["open-pr"]["shas"], ["o10"])
        self.assertEqual(by_ref["fresh-orphan"]["shas"], ["bfresh-orphan"])
        self.assertEqual(big["files"], [{"path": "a", "status": "added"}, {"path": "b", "status": "removed"}])
        self.assertEqual((big["first_commit_at"], big["last_commit_at"]), ("2025-10-10T00:00:00Z", "2025-10-12T00:00:00Z"))
        small = by_ref["open-pr"]
        self.assertEqual(small["files"], [{"path": "src/f0.cpp", "status": "added"}])
        self.assertEqual((small["kind"], small["number"], small["base"], small["created_at"], small["body"]),
                         ("pr", 1, "master", "2025-10-01T00:00:00Z", ""))
        reused = by_ref["merged-reused"]
        self.assertEqual((reused["files"], reused["first_commit_at"], reused["last_commit_at"], reused["files_truncated"]),
                         ([], "2025-10-22T00:00:00Z", "2025-10-25T00:00:00Z", False))
        orphan = by_ref["fresh-orphan"]
        self.assertEqual((orphan["kind"], orphan["first_commit_at"], orphan["files_truncated"]),
                         ("branch", "2025-10-27T00:00:00Z", False))

    def test_truncated_branch_reads_numbered_dirs(self):
        files = [{"filename": f"src/f{i}.cpp", "status": "modified"} for i in range(300)]
        files[0] = {"filename": "docs/adr/0070-seen.md", "status": "added"}
        cr.http = FakeAPI({
            ("GET", "repos/o/r/compare/"): (200, {"ahead_by": 1, "files": files, "commits": [],
                                                  "merge_base_commit": {"sha": "forksha"}}, ""),
            ("GET", "repos/o/r/contents/docs/adr?ref=forksha"): (200, [{"path": "docs/adr/0001-old.md"}], ""),
            ("GET", "repos/o/r/contents/docs/adr?ref=big"): (200, [{"path": "docs/adr/0001-old.md"},
                                                               {"path": "docs/adr/0070-seen.md"},
                                                               {"path": "docs/adr/0071-hidden.md"}], ""),
            ("GET", "repos/o/r/contents/server/migrations?ref=forksha"): (200, [{"path": "server/migrations/019_a.up.sql"}], ""),
            ("GET", "repos/o/r/contents/server/migrations?ref=big"): (200, [{"path": "server/migrations/019_a.up.sql"}], "")})
        it = cr._branch_item("o/r", "master", "big", NUMBERING)
        added = [f["path"] for f in it["files"] if f["path"].startswith("docs/adr")]
        self.assertEqual(added, ["docs/adr/0070-seen.md", "docs/adr/0071-hidden.md"])
        self.assertEqual(len(it["files"]), 301)

    def test_collect_with_numbering_and_refresh(self):
        def graphql(path, payload):
            if "headRefName:$head" in payload["query"]:
                head = payload["variables"]["head"]
                nodes = [pr_node(1, "open-pr", files=2)] if head == "open-pr" else []
                return 200, {"data": {"repository": {"pullRequests": {"nodes": nodes}}}}, ""
            return self.graphql(path, payload)
        routes = self.routes({("POST", "graphql"): graphql,
                              ("GET", "repos/o/r/contents/docs/adr"): (200, [{"path": "docs/adr/0001-a.md"}], ""),
                              ("GET", "repos/o/r/contents/server/migrations"): (200, [], "")})
        cr.http = FakeAPI(routes)
        snap = cr.collect("o/r", now=cr._ts("2025-10-30T00:00:00Z"), numbering=NUMBERING)
        self.assertEqual(snap["base_files"], {"adr": ["docs/adr/0001-a.md"], "migration": []})
        snap["reservations"] = []
        snap["items"].append({"kind": "branch", "ref": "even", "files": []})
        out = cr.refresh(snap, "open-pr", NUMBERING)
        mine = [i for i in out["items"] if i["ref"] == "open-pr"]
        self.assertEqual((len(mine), len(mine[0]["files"]), out["refreshed"]), (1, 2, "open-pr"))
        self.assertEqual(out["reservations"], [{"ref": "refs/reservations/adr/0063"}])
        self.assertEqual(out["now"], snap["now"])
        gone = cr.refresh(snap, "even")
        self.assertNotIn("even", [i["ref"] for i in gone["items"]])
        self.assertIn("fresh-orphan", [i["ref"] for i in cr.refresh(snap, "fresh-orphan")["items"]])
        self.assertEqual(len(cr.refresh(snap, "master")["items"]), len(snap["items"]))

    def test_cli_snapshot_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            cache, out = Path(d, "cache.json"), Path(d, "out.json")
            now = cr.dt.datetime.now(cr.dt.timezone.utc)
            fresh = {"repo": "o/r", "base": "master", "now": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "items": [],
                     "dormant_branches": [], "reservations": []}
            cache.write_text(json.dumps(fresh), encoding="utf-8")
            def no_network(method, url, payload=None):
                raise cr.NotChecked("a fresh cache must not touch GitHub")
            cr.http = no_network
            with contextlib.redirect_stdout(io.StringIO()) as o:
                self.assertEqual(cr.main(["snapshot", "--repo", "o/r", "--out", str(out), "--reuse", str(cache)]), 0)
            self.assertIn("reused (0.", o.getvalue())
            self.assertIn("refreshed nothing", o.getvalue())
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["items"], [])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cr.main(["snapshot", "--repo", "o/r", "--out", str(out)]), 2)
                self.assertEqual(cr.main(["snapshot", "--repo", "o/r", "--out", str(out), "--reuse", str(Path(d, "none.json"))]), 2)
            aged = (now - cr.dt.timedelta(seconds=330)).strftime("%Y-%m-%dT%H:%M:%SZ")
            cache.write_text(json.dumps({**fresh, "now": aged}), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cr.main(["snapshot", "--repo", "o/r", "--out", str(out), "--reuse", str(cache),
                                          "--max-age-min", "5.45"]), 2)
                self.assertEqual(cr.main(["snapshot", "--repo", "o/r", "--out", str(out), "--reuse", str(cache),
                                          "--max-age-min", "5.6"]), 0)
            cache.write_text(json.dumps({**fresh, "repo": "x/y"}), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cr.main(["snapshot", "--repo", "o/r", "--out", str(out), "--reuse", str(cache),
                                          "--max-age-min", "60"]), 2)
            for stale in ({**fresh, "now": "2020-01-01T00:00:00Z"}, {**fresh, "repo": "x/y"}):
                cache.write_text(json.dumps(stale), encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cr.main(["snapshot", "--repo", "o/r", "--out", str(out), "--reuse", str(cache)]), 2)
            cache.write_text("not json", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cr.main(["snapshot", "--repo", "o/r", "--out", str(out), "--reuse", str(cache)]), 2)

    def test_truncated_compare_is_flagged(self):
        for count, flag in ((300, True), (299, False)):
            files = [{"filename": f"f{i}", "status": "added"} for i in range(count)]
            cr.http = FakeAPI({("GET", "repos/o/r/compare/"): (200, {"ahead_by": 1, "files": files, "commits": []}, "")})
            it = cr._branch_item("o/r", "master", "b")
            self.assertEqual((it["files_truncated"], it["first_commit_at"]), (flag, None))

    def test_get_follows_link_pages(self):
        pages = {"repos/o/r/x": (200, [1, 2], '<https://api.github.com/repos/o/r/x?page=2>; rel="next"'),
                 "repos/o/r/x?page=2": (200, [3], "")}
        cr.http = lambda m, url, payload=None: pages[url.replace(cr.API + "/", "")]
        self.assertEqual(cr.get("repos/o/r/x"), [1, 2, 3])

    def test_http_errors_are_not_checked(self):
        cr.http = FakeAPI({("GET", "repos/o/r"): (403, {"message": "rate limit"}, "")})
        with self.assertRaises(cr.NotChecked):
            cr.get("repos/o/r")
        cr.http = FakeAPI({("POST", "graphql"): (200, {"errors": [{"message": "bad"}], "data": None}, "")})
        with self.assertRaises(cr.NotChecked):
            cr.graphql("q", {})

    def test_n3_unreachable_is_exit_2(self):
        def down(method, url, payload=None):
            raise cr.NotChecked("network down")
        cr.http = down
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d, "c.json")
            cfg.write_text(json.dumps({"capabilities": VOCAB, "numbering": NUMBERING}), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                for cmd in (["check", "--capability", "large-image-memory"], ["orphans"], ["numbers"],
                            ["reserve", "--kind", "adr"]):
                    self.assertEqual(cr.main(cmd + ["--repo", "o/r", "--config", str(cfg)]), 2, cmd)

    def test_partial_failure_is_not_checked(self):
        def flaky(path, payload):
            if "fresh-orphan" in path:
                return 502, {"message": "bad gateway"}, ""
            return self.compare(path, payload)
        cr.http = FakeAPI(self.routes({("GET", "repos/o/r/compare/"): flaky}))
        with self.assertRaises(cr.NotChecked):
            cr.collect("o/r", now=cr._ts("2025-10-30T00:00:00Z"))

    def test_live_refs_create(self):
        calls = []
        taken = {"refs/reservations/adr/0063"}

        def refs(path, payload):
            if payload["ref"] in taken:
                return 422, {"message": "Reference already exists"}, ""
            return 201, {"ref": payload["ref"]}, ""
        cr.http = FakeAPI({("POST", "repos/o/r/git/tags"): (201, {"sha": "tagsha"}, ""),
                           ("POST", "repos/o/r/git/refs"): refs,
                           ("GET", "repos/o/r/commits/"): (200, {"sha": "headsha"}, "")}, calls)
        live = cr.LiveRefs("o/r")
        self.assertEqual(live.head_sha("feat/x"), "headsha")
        self.assertFalse(live.create("refs/reservations/adr/0063", "headsha", "{}"))
        self.assertTrue(live.create("refs/reservations/adr/0064", "headsha", "{}"))
        tag_payload = [p for m, path, p in calls if path.endswith("git/tags")][-1]
        self.assertEqual(tag_payload, {"tag": "adr-0064", "message": "{}", "object": "headsha", "type": "commit"})
        self.assertEqual([p for m, path, p in calls if path.endswith("git/refs")][-1],
                         {"ref": "refs/reservations/adr/0064", "sha": "tagsha"})
        cr.http = FakeAPI({("POST", "repos/o/r/git/tags"): (201, {"sha": "t"}, ""),
                           ("POST", "repos/o/r/git/refs"): (422, {"message": "Object does not exist"}, "")})
        with self.assertRaises(cr.NotChecked):
            live.create("refs/reservations/adr/0065", "s", "{}")
        cr.http = FakeAPI({("POST", "repos/o/r/git/tags"): (201, {"sha": "t"}, ""),
                           ("POST", "repos/o/r/git/refs"): (403, {"message": "forbidden"}, "")})
        with self.assertRaises(cr.NotChecked):
            live.create("refs/reservations/adr/0065", "s", "{}")
        cr.http = FakeAPI({("POST", "repos/o/r/git/tags"): (404, {"message": "no"}, "")})
        with self.assertRaises(cr.NotChecked):
            live.create("refs/reservations/adr/0065", "s", "{}")

    def test_token_sources(self):
        cr._TOKEN[:] = []
        old = {k: os.environ.pop(k, None) for k in ("GH_TOKEN", "GITHUB_TOKEN")}
        real_run = cr.subprocess.run
        try:
            os.environ["GITHUB_TOKEN"] = "from-env"
            self.assertEqual(cr.token(), "from-env")
            os.environ["GITHUB_TOKEN"] = "changed"
            self.assertEqual(cr.token(), "from-env")  # cached for the process
            cr._TOKEN[:] = []
            os.environ["GH_TOKEN"] = "gh-env"
            self.assertEqual(cr.token(), "gh-env")
            cr._TOKEN[:] = []
            del os.environ["GH_TOKEN"]
            del os.environ["GITHUB_TOKEN"]
            seen = {}

            def run(cmd, **kw):
                seen.update(kw, cmd=cmd)
                return types.SimpleNamespace(stdout="from-gh\n")
            cr.subprocess.run = run
            self.assertEqual(cr.token(), "from-gh")
            self.assertEqual((seen["cmd"], seen["capture_output"], seen["text"], seen["timeout"]),
                             (["gh", "auth", "token"], True, True, 30))
            cr._TOKEN[:] = []
            os.environ["GITHUB_TOKEN"] = "again"
            cr._TOKEN[:] = []
            del os.environ["GITHUB_TOKEN"]
            cr.subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout="")
            with self.assertRaises(cr.NotChecked):
                cr.token()

            def boom(*a, **k):
                raise FileNotFoundError("gh")
            cr.subprocess.run = boom
            with self.assertRaises(cr.NotChecked):
                cr.token()
        finally:
            cr.subprocess.run = real_run
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main(verbosity=1)
