"""sched_task.py `run`: the log, not Task Scheduler, is the proof - so it must tell OK, FAILED,
TIMED_OUT apart, kill the child on a timeout, and refuse a WindowsApps alias."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("st", HERE / "sched_task.py")
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)
PY = sys.executable


def run(*args):
    log = Path(tempfile.mkdtemp())
    env = dict(os.environ, USERPROFILE=str(log), HOME=str(log))
    r = subprocess.run([PY, str(HERE / "sched_task.py"), "run", "--name", "t", *args],
                       capture_output=True, text=True, env=env, timeout=120)
    recs = [json.loads(x) for x in (log / ".claude/state/sched/t.jsonl").read_text(encoding="utf-8").splitlines()]
    return r.returncode, recs[-1]


def test_ok_failed_timeout():
    rc, end = run("--", PY, "-c", "print('hello')")
    assert (rc, end["status"], end["rc"]) == (0, "OK", 0) and "hello" in end["tail"], end
    rc, end = run("--", PY, "-c", "import sys; sys.exit(3)")
    assert (rc, end["status"], end["rc"]) == (1, "FAILED", 3), end
    rc, end = run("--ok-codes", "0,1", "--", PY, "-c", "import sys; sys.exit(1)")
    assert (rc, end["status"]) == (0, "OK"), end
    marker = tempfile.mktemp()
    t0 = time.time()
    rc, end = run("--limit-min", "0.05", "--", PY, "-c",
                  f"import time; time.sleep(60); open(r'{marker}','w').write('x')")
    assert (rc, end["status"], end["rc"]) == (2, "TIMED_OUT", None), end
    assert time.time() - t0 < 30, "limit not enforced"
    time.sleep(2)
    assert not os.path.exists(marker), "child survived the timeout"


def test_alias_refused():
    alias = os.path.join(os.environ.get("LOCALAPPDATA", "C:/x"), "Microsoft", "WindowsApps", "python.exe")
    if not os.path.exists(alias):
        return
    try:
        st.resolve_exe(alias)
    except SystemExit as e:
        assert "WindowsApps" in str(e)
    else:
        raise AssertionError("alias accepted")


if __name__ == "__main__":
    test_ok_failed_timeout()
    test_alias_refused()
    print("ok")
