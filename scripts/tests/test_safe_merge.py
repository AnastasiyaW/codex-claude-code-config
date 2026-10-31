# -*- coding: utf-8 -*-
"""safe_merge.py end to end through a fake gh executable.

Run: python scripts/tests/test_safe_merge.py   (exit 0 = all pass, 1 = a case failed)
  SAFE_MERGE_INPROCESS=1  same decisions without one process per gh call (mutation probe)
  SAFE_MERGE_RUNNER_ONLY=1  only the cases that exercise the real subprocess runner
SAFE_MERGE_DIR points the test at a copy of scripts/ (mutation_probe.py --dir-env SAFE_MERGE_DIR).
"""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = Path(os.environ.get("SAFE_MERGE_DIR", HERE.parent))
SCRIPT = SCRIPTS / "safe_merge.py"
SHIM = HERE / "fake_gh.py"
spec = importlib.util.spec_from_file_location("safe_merge", SCRIPT)
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)

TODAY = dt.date.today()
HEAD = "h" * 40
BASE = "b" * 40
OK_RUN = {"name": "unit", "status": "completed", "conclusion": "success"}
INPROCESS = bool(os.environ.get("SAFE_MERGE_INPROCESS"))


def day(n: int) -> str:
    return (TODAY + dt.timedelta(days=n)).isoformat()


def scenario(**change) -> dict:
    s = sm.base_scenario()
    s.update(change)
    return s


def pr(**change) -> dict:
    return dict(sm.base_scenario()["pr"], **change)


def run_case(s: dict, tmp: Path, lock_dir: Path | None = None, log: Path | None = None,
             inprocess: bool = INPROCESS) -> tuple[int, str, list[list[str]]]:
    case_dir = Path(tempfile.mkdtemp(dir=tmp))
    locks = lock_dir or case_dir / "locks"
    log = log or case_dir / "receipts" / "safe-merge.jsonl"
    if inprocess:
        gh = sm.ScenarioGh(json.loads(json.dumps(s)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = sm.run_gate(gh, "o/r", 5, locks, log)
        return code, buf.getvalue(), gh.calls
    (case_dir / "scenario.json").write_text(json.dumps(s), encoding="utf-8")
    env = dict(os.environ, FAKE_GH_SCENARIO=str(case_dir / "scenario.json"),
               FAKE_GH_STATE=str(case_dir / "state.json"), SAFE_MERGE_DIR=str(SCRIPTS))
    gh_cmd = f"{Path(sys.executable).as_posix()} {SHIM.as_posix()}"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "o/r", "5", "--gh", gh_cmd, "--lock-dir", str(locks),
         "--receipt-log", str(log)],
        capture_output=True, text=True, env=env, timeout=300)
    state_file = case_dir / "state.json"
    calls = json.loads(state_file.read_text(encoding="utf-8"))["calls"] if state_file.exists() else []
    return proc.returncode, proc.stdout + proc.stderr, calls


def merge_calls(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if c[:2] == ["pr", "merge"]]


def runs(n: int, fail_at: int | None = None, pending_at: int | None = None) -> list[dict]:
    out = []
    for i in range(n):
        r = {"name": f"job-{i}", "status": "completed", "conclusion": "success"}
        if i == fail_at:
            r["conclusion"] = "failure"
        if i == pending_at:
            r.update(status="in_progress", conclusion=None)
        out.append(r)
    return out


ALLOW = lambda name, expires, reason="hosted runner billing": {  # noqa: E731
    "allow_unavailable": [{"name": name, "reason": reason, "expires": expires}]}

CASES: list[tuple[str, dict, int, str]] = [
    ("green and fresh merges", scenario(), 0, "result=merged"),
    ("identical head merges", scenario(compare_status="identical"), 0, "result=merged"),
    ("diverged head is updated, then waits", scenario(compare_status="diverged"), 1, "updated-waiting-ci"),
    ("behind head is updated, then waits", scenario(compare_status="behind"), 1, "updated-waiting-ci"),
    ("pending check run refuses",
     scenario(check_runs=[OK_RUN, {"name": "e2e", "status": "queued", "conclusion": None}]), 1, "checks-pending"),
    ("pending commit status refuses",
     scenario(statuses=[{"context": "ci/legacy", "state": "pending"}]), 1, "checks-pending"),
    ("successful commit status counts as a real check",
     scenario(check_runs=[], statuses=[{"context": "ci/legacy", "state": "success"}]), 0, "result=merged"),
    ("failed check run refuses",
     scenario(check_runs=[OK_RUN, {"name": "e2e", "status": "completed", "conclusion": "failure"}]), 1, "checks-failed"),
    ("cancelled check run refuses",
     scenario(check_runs=[OK_RUN, {"name": "e2e", "status": "completed", "conclusion": "cancelled"}]), 1, "checks-failed"),
    ("startup_failure refuses",
     scenario(check_runs=[OK_RUN, {"name": "e2e", "status": "completed", "conclusion": "startup_failure"}]), 1, "checks-failed"),
    ("error commit status refuses",
     scenario(statuses=[{"context": "ci/legacy", "state": "error"}]), 1, "checks-failed"),
    ("skipped and neutral pass beside a success",
     scenario(check_runs=[OK_RUN, {"name": "a", "status": "completed", "conclusion": "skipped"},
                          {"name": "b", "status": "completed", "conclusion": "neutral"}]), 0, "result=merged"),
    ("only skipped checks is nothing tested",
     scenario(check_runs=[{"name": "a", "status": "completed", "conclusion": "skipped"}]), 1, "no-checks"),
    ("failure on the second page refuses", scenario(check_runs=runs(150, fail_at=130)), 1, "checks-failed"),
    ("pending on the second page refuses", scenario(check_runs=runs(201, pending_at=200)), 1, "checks-pending"),
    ("150 green runs merge", scenario(check_runs=runs(150)), 0, "result=merged"),
    ("pending status on the second page refuses",
     scenario(statuses=[{"context": f"s{i}", "state": "success"} for i in range(100)]
              + [{"context": "late", "state": "pending"}]), 1, "checks-pending"),
    ("unfinished actions suite without runs waits",
     scenario(check_suites=[{"id": 1, "app": {"slug": "github-actions"}, "status": "queued",
                             "latest_check_runs_count": 0}]), 1, "checks-pending"),
    ("unfinished suite of another app with runs waits",
     scenario(check_suites=[{"id": 2, "app": {"slug": "ci-bot"}, "status": "in_progress",
                             "latest_check_runs_count": 3}]), 1, "checks-pending"),
    ("queued suite of an app that never runs is ignored",
     scenario(check_suites=[{"id": 3, "app": {"slug": "claude"}, "status": "queued",
                             "latest_check_runs_count": 0},
                            {"id": 4, "app": {"slug": "github-actions"}, "status": "completed",
                             "latest_check_runs_count": 1}]), 0, "result=merged"),
    ("allowlisted failing check is tolerated",
     scenario(config=ALLOW("pin", day(10)),
              check_runs=[OK_RUN, {"name": "pin", "status": "completed", "conclusion": "failure"}]), 0, "result=merged"),
    ("allowlisted pending check is tolerated",
     scenario(config=ALLOW("pin", day(0)),
              check_runs=[OK_RUN, {"name": "pin", "status": "queued", "conclusion": None}]), 0, "result=merged"),
    ("expired allowlist refuses", scenario(config=ALLOW("pin", day(-1))), 1, "allowlist-expired"),
    ("allowlist dated too far refuses", scenario(config=ALLOW("pin", day(91))), 1, "allowlist-too-long"),
    ("allowlist at the limit is accepted", scenario(config=ALLOW("pin", day(90))), 0, "result=merged"),
    ("allowlist entry without reason is malformed", scenario(config=ALLOW("pin", day(5), " ")), 2, "config-malformed"),
    ("allowlist bad date is malformed", scenario(config=ALLOW("pin", "soon")), 2, "config-malformed"),
    ("allowlist that is not a list is malformed",
     scenario(config={"allow_unavailable": {"name": "pin"}}), 2, "config-malformed"),
    ("required as a string is malformed", scenario(config={"required": "unit"}), 2, "config-malformed"),
    ("required with an empty name is malformed", scenario(config={"required": ["unit", ""]}), 2, "config-malformed"),
    ("integration branches as a string is malformed",
     scenario(config={"integration_branches": "develop"}), 2, "config-malformed"),
    ("allow_no_checks that is not a reason is malformed",
     scenario(config={"allow_no_checks": True}), 2, "config-malformed"),
    ("unknown config key is malformed", scenario(config={"allow_unavalable": []}), 2, "config-malformed"),
    ("comment keys are fine", scenario(config={"_doc": "x"}), 0, "result=merged"),
    ("config that is not JSON is malformed", scenario(config="{not json"), 2, "config-malformed"),
    ("config that is a list is malformed", scenario(config="[1]"), 2, "config-malformed"),
    ("required check missing waits", scenario(config={"required": ["unit", "server"]}), 1, "checks-pending"),
    ("required check present merges", scenario(config={"required": ["unit"]}), 0, "result=merged"),
    ("required check satisfied by a skip merges",
     scenario(config={"required": ["lint"]},
              check_runs=[OK_RUN, {"name": "lint", "status": "completed", "conclusion": "skipped"}]), 0, "result=merged"),
    ("no checks at all refuses", scenario(check_runs=[]), 1, "no-checks"),
    ("only allowlisted checks refuses", scenario(config=ALLOW("unit", day(3))), 1, "no-checks"),
    ("no checks with declared reason merges",
     scenario(check_runs=[], config={"allow_no_checks": "documentation-only repository"}), 0, "result=merged"),
    ("conflicting refuses", scenario(mergeable_after="CONFLICTING"), 1, "conflicting"),
    ("mergeability unknown is not checked", scenario(mergeable_after="UNKNOWN"), 2, "(UNKNOWN)"),
    ("head moved during evaluation refuses", scenario(head_after="z" * 40), 1, "head-moved"),
    ("base moved before merge refuses", scenario(base_shas=[BASE, "c" * 40]), 1, "base-moved"),
    ("merge commit with wrong parents is not checked",
     scenario(merge_parents=["c" * 40, HEAD]), 2, "merged-untested-combination"),
    ("GitHub refusing the merge refuses", scenario(merge_fails=True), 1, "merge-rejected"),
    ("merge call errors but the PR did merge",
     scenario(merge_fails=True, merged_despite_error=True), 0, "result=merged"),
    ("wrong base refuses", scenario(pr=pr(baseRefName="develop")), 1, "wrong-base"),
    ("declared integration branch merges",
     scenario(pr=pr(baseRefName="develop"), config={"integration_branches": ["develop"]}), 0, "result=merged"),
    ("draft refuses", scenario(pr=pr(isDraft=True)), 1, "draft"),
    ("closed refuses", scenario(pr=pr(state="CLOSED")), 1, "not-open"),
    ("already merged is reported, not merged again", scenario(pr=pr(state="MERGED")), 0, "already-merged"),
    ("main as default branch merges",
     scenario(default_branch="main", pr=pr(baseRefName="main")), 0, "result=merged"),
    ("policy as a base64 contents object",
     scenario(check_runs=[], config=json.dumps({"type": "file", "encoding": "base64", "content":
              base64.b64encode(json.dumps({"allow_no_checks": "docs"}).encode()).decode()})), 0, "result=merged"),
    ("gh failing is not checked", scenario(repo="other/repo"), 2, "gh-error"),
    ("a response of the wrong shape is not checked", scenario(config="null"), 2, "config-malformed"),
]

SHOULD_MERGE_WHEN_NOT_ZERO = {"merged-untested-combination", "merge-rejected"}


def check_case(name: str, s: dict, want: int, marker: str, code: int, out: str,
               calls: list[list[str]], failures: list[str]) -> None:
    merged = merge_calls(calls)
    if code != want or marker not in out:
        failures.append(f"{name}: exit {code} (want {want}), marker '{marker}' "
                        f"{'present' if marker in out else 'absent'}\n{out[-700:]}")
        return
    should = marker != "already-merged" and (want == 0 or marker in SHOULD_MERGE_WHEN_NOT_ZERO)
    if bool(merged) != should:
        failures.append(f"{name}: merge called={bool(merged)}, expected {should}")
    if merged and merged[0] != ["pr", "merge", "5", "-R", "o/r", "--merge",
                                "--match-head-commit", s["pr"]["headRefOid"]]:
        failures.append(f"{name}: merge argv {merged[0]}")
    lines = out.splitlines()
    scanned = [ln for ln in lines if ln.startswith("SCANNED: repo=o/r pr=5 ")]
    receipts = [ln for ln in lines if ln.startswith("RECEIPT: {")]
    if len(scanned) != 1 or len(receipts) != 1:
        failures.append(f"{name}: SCANNED/RECEIPT lines {len(scanned)}/{len(receipts)}")
        return
    head = s["pr"]["headRefOid"]
    if f" head={head[:12]} " not in scanned[0]:
        failures.append(f"{name}: SCANNED head not 12 chars: {scanned[0]}")
    receipt = json.loads(receipts[0][len("RECEIPT: "):])
    if receipt.get("exit") != code or not receipt.get("reason"):
        failures.append(f"{name}: receipt exit/reason {receipt.get('exit')}")
    prefix = {0: "OK: ", 1: "REFUSED: ", 2: "NOT CHECKED: "}[code]
    verdict_lines = [l for l in lines if not l.startswith("NEXT: ")]
    if not verdict_lines or not verdict_lines[-1].startswith(prefix):
        failures.append(f"{name}: last line does not start with {prefix!r}: {verdict_lines[-1:]}")
    result = receipt.get("result")
    has_next = any(l.startswith("NEXT: ") for l in lines)
    if code != 0 and result in sm.NEXT_STEP and not has_next:
        failures.append(f"{name}: refusal {result} printed no NEXT step")
    if code == 0 and has_next:
        failures.append(f"{name}: a merge printed a NEXT step")
    if "base_sha" in receipt and f"@{receipt['base_sha'][:12]} " not in scanned[0]:
        failures.append(f"{name}: SCANNED base not 12 chars: {scanned[0]}")
    if "checks" in receipt and f"checks={receipt['checks']['checks']} passed={receipt['checks']['passed']} " \
            f"allowlisted={len(receipt['checks']['allowlisted'])} " not in scanned[0]:
        failures.append(f"{name}: SCANNED counts differ from receipt: {scanned[0]}")
    if "checks" not in receipt and "checks=0 passed=0 allowlisted=0 " not in scanned[0]:
        failures.append(f"{name}: SCANNED counts without checks: {scanned[0]}")
    updates = [c for c in calls if c[:2] == ["pr", "update-branch"]]
    if bool(updates) != (marker == "updated-waiting-ci"):
        failures.append(f"{name}: update-branch called={bool(updates)}")
    if marker == "updated-waiting-ci" and f"tip {BASE[:12]} (" not in out:
        failures.append(f"{name}: waiting message lacks the 12-char base tip")
    if any("--rebase" in c for c in updates):
        failures.append(f"{name}: update-branch used --rebase")
    reads = [c[-1] for c in calls if c[:1] == ["api"] and "/contents/" in c[-1]]
    default = s.get("default_branch", "master")
    if reads and not all(r.endswith(f"?ref={default}") for r in reads):
        failures.append(f"{name}: policy read from {reads}, not the default branch")
    if code == 0 and marker == "result=merged":
        base = s.get("pr", {}).get("baseRefName", "master")
        want_msg = f"OK: merged {head[:12]} onto {base}@{BASE[:12]} as {'m' * 12}"
        if want_msg not in lines:
            failures.append(f"{name}: merged message is not '{want_msg}': {lines[-1:]}")


def unit_cases(tmp: Path, failures: list[str]) -> None:
    class Garbage(sm.Gh):
        def answer(self, args):
            return 0, "garbage", ""
    try:
        Garbage([]).json("api", "x")
        failures.append("non-JSON gh output must raise")
    except sm.GhError as exc:
        if "exit 0: not JSON: garbage" not in str(exc):
            failures.append(f"non-JSON error message: {exc}")
    gh = sm.ScenarioGh(scenario(check_runs=[{"status": "completed", "conclusion": "failure"}],
                                statuses=[{"state": "failure"}]))
    names = [c["name"] for c in sm.collect_checks(gh, "o/r", HEAD)]
    if names != ["?", "?"]:
        failures.append(f"unnamed checks must be named '?': {names}")
    gh = sm.ScenarioGh(scenario(config=ALLOW("pin", day(5)),
                                check_runs=[OK_RUN, {"name": "pin", "status": "completed", "conclusion": "failure"}]))
    receipt: dict = {}
    try:
        sm.safe_merge(gh, "o/r", 5, tmp / "unit-locks", receipt)
    except sm.Outcome:
        pass
    if receipt.get("checks", {}).get("allowlisted") != ["pin"]:
        failures.append(f"receipt must list the allowlisted check: {receipt.get('checks')}")
    # liveness on this platform: our own pid lives, an exited child does not
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    if not sm._pid_alive(os.getpid()) or sm._pid_alive(child.pid):
        failures.append("pid liveness: own pid must live, exited child must not")
    # the POSIX branch, with a fake os.kill
    calls: list[tuple[int, int]] = []
    real_name, real_kill = os.name, getattr(os, "kill", None)

    def fake_kill(pid: int, sig: int) -> None:
        calls.append((pid, sig))
        if pid == 11:
            raise ProcessLookupError
        if pid == 12:
            raise PermissionError
    try:
        os.name = "posix"
        os.kill = fake_kill
        got = [sm._pid_alive(10), sm._pid_alive(11), sm._pid_alive(12)]
    finally:
        os.name = real_name
        if real_kill is not None:
            os.kill = real_kill
    if got != [True, False, True] or any(sig != 0 for _, sig in calls):
        failures.append(f"POSIX liveness probe: {got} {calls}")
    # pid 1 on the same host is judged by liveness, pid 0 is never a real owner
    real_alive = sm._pid_alive
    sm._pid_alive = lambda pid: True
    try:
        lock = tmp / "unit.lock"
        for pid, want in ((1, False), (0, True), (-3, True)):
            lock.write_text(json.dumps({"host": socket.gethostname(), "pid": pid}), encoding="utf-8")
            if sm._lock_stale(lock) != want:
                failures.append(f"_lock_stale pid={pid}: want {want}")
    finally:
        sm._pid_alive = real_alive


def lock_cases(tmp: Path, failures: list[str]) -> None:
    locks = tmp / "locks-live" / "nested" / "dir"
    code, out, _ = run_case(scenario(), tmp, lock_dir=locks)
    if code != 0:
        failures.append(f"a lock dir that does not exist yet is created: exit {code}\n{out[-300:]}")
    lock = locks / "o__r.lock"
    if lock.exists():
        failures.append("lock left behind after a run")

    def plant(content: str, age: float = 0) -> None:
        lock.write_text(content, encoding="utf-8")
        if age:
            old = time.time() - age
            os.utime(lock, (old, old))

    host = socket.gethostname()
    plant(json.dumps({"token": "x", "host": host, "pid": os.getpid()}))
    code, out, calls = run_case(scenario(), tmp, lock_dir=locks)
    if code != 1 or "result=locked" not in out or merge_calls(calls) or not lock.exists():
        failures.append(f"a live lock must refuse and stay: exit {code}\n{out[-300:]}")
    for label, content, age, want in (
            ("dead pid", json.dumps({"token": "x", "host": host, "pid": 999999}), 0, 0),
            ("pid 0", json.dumps({"token": "x", "host": host, "pid": 0}), 0, 0),
            ("no pid", json.dumps({"token": "x", "host": host}), 0, 0),
            ("pid not a number", json.dumps({"token": "x", "host": host, "pid": "1"}), 0, 0),
            ("garbage", "not json", 0, 0),
            ("old lock of another host", json.dumps({"token": "x", "host": "elsewhere", "pid": 4}),
             sm.LOCK_STALE_SECONDS + 60, 0),
            ("fresh lock of another host", json.dumps({"token": "x", "host": "elsewhere", "pid": 4}), 0, 1),
            ("live pid, lock just under the age limit", json.dumps({"token": "x", "host": host,
                                                                    "pid": os.getpid()}),
             sm.LOCK_STALE_SECONDS - 120, 1)):
        plant(content, age)
        code, out, _ = run_case(scenario(), tmp, lock_dir=locks)
        if code != want:
            failures.append(f"lock '{label}': exit {code}, want {want}\n{out[-300:]}")
        if want == 0 and lock.exists():
            failures.append(f"lock '{label}': taken over but not released")
        if lock.exists():
            lock.unlink()
    # a competitor moved our lock away: the merge must not happen, and ours is not deleted
    code, out, calls = run_case(scenario(steal_lock=str(lock)), tmp, lock_dir=locks)
    if code != 1 or "lock-lost" not in out or merge_calls(calls):
        failures.append(f"lost lock must refuse before merging: exit {code}\n{out[-300:]}")
    if not lock.exists():
        failures.append("release removed a lock that was not ours")
    else:
        lock.unlink()
    direct = sm.RepoLock(tmp / "direct", "o/r", 5)
    direct.acquire()
    if not direct.held():
        failures.append("a freshly taken lock is not held")
    direct.release()
    if direct.path.exists() or direct.held():
        failures.append("release did not remove our own lock")


def receipt_log_cases(tmp: Path, failures: list[str]) -> None:
    log = tmp / "log-dir" / "deeper" / "safe-merge.jsonl"
    run_case(scenario(), tmp, log=log)
    run_case(scenario(check_runs=[]), tmp, log=log)
    try:
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    except (OSError, ValueError) as exc:
        failures.append(f"receipt log unreadable: {exc}")
        return
    if [r.get("exit") for r in rows] != [0, 1]:
        failures.append(f"receipt log rows {[r.get('exit') for r in rows]}, want [0, 1]")


def runner_cases(tmp: Path, failures: list[str]) -> None:
    """The real subprocess runner: through the fake gh executable, and a missing binary."""
    for name, s, want, marker in (CASES[0], CASES[-2], CASES[1]):
        code, out, calls = run_case(s, tmp, inprocess=False)
        check_case(f"[subprocess] {name}", s, want, marker, code, out, calls, failures)
    proc = subprocess.run([sys.executable, str(SCRIPT), "o/r", "5", "--gh", "no-such-gh-binary-xyz",
                           "--lock-dir", str(tmp / "nolocks"), "--receipt-log", str(tmp / "nolog.jsonl")],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 2 or "gh-error" not in proc.stdout:
        failures.append(f"missing gh binary must be exit 2 gh-error: {proc.returncode}\n{proc.stdout[-300:]}")
    code, out, err = sm.invoke([sys.executable, "-c", "import sys; print('o'); "
                                                       "sys.stderr.write('e'); sys.exit(3)"], [])
    if (code, out.strip(), err) != (3, "o", "e"):
        failures.append(f"invoke must return (code, stdout, stderr): {(code, out, err)}")
    code, out, err = sm.invoke(["no-such-gh-binary-xyz"], ["x"])
    if code != sm.NOT_STARTED or code == 0 or out != "" or not err:
        failures.append(f"invoke of a missing binary: {(code, out, err)}")


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        if os.environ.get("SAFE_MERGE_RUNNER_ONLY"):
            runner_cases(tmp, failures)
        else:
            for name, s, want, marker in CASES:
                code, out, calls = run_case(s, tmp)
                check_case(name, s, want, marker, code, out, calls, failures)
            lock_cases(tmp, failures)
            receipt_log_cases(tmp, failures)
            unit_cases(tmp, failures)
            proc = subprocess.run([sys.executable, str(SCRIPT), "not-a-repo", "5"],
                                  capture_output=True, text=True)
            if proc.returncode != 2:
                failures.append(f"bad repo argument must be exit 2: {proc.returncode}")
            proc = subprocess.run([sys.executable, str(SCRIPT), "--self-test"], capture_output=True, text=True)
            if proc.returncode != 0:
                failures.append(f"--self-test failed: {proc.stdout[-400:]}")
            if not INPROCESS:
                runner_cases(tmp, failures)
    for f in failures:
        print("FAIL", f)
    print(f"SCANNED: cases={len(CASES)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
