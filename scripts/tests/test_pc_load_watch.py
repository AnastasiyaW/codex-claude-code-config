"""pc_load_watch: what gets killed and what stays protected.

Every case here came from the live process list on 2026-10-11, when a broader rule would
have killed the agent's own shell, the owner's terminal tabs, the rclone sftp transport
and the Codex app.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("w", Path(__file__).resolve().parents[1] / "pc_load_watch.py")
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

HOME = "C:/" + "/".join(("Users", "u"))      # assembled so no literal home path ships in the repo
PY = HOME.replace("/", "\\") + r"\AppData\Local\Python\pythoncore-3.14-64\python.exe"
CFG = HOME + "/.claude/claude-code-config"

HOOK_CASES = {
    f"{PY} {CFG}/hooks/api-key-leak-detector.py": True,
    f'"{PY}"  {HOME}/.claude/private-hooks/retouch-security-test-router.py': True,
    rf'"C:\Program Files\Git\bin\..\usr\bin\bash.exe" -c "python \"{CFG}/hooks/live-tree-guard.py\""': True,
    f'python "{CFG}/hooks/keyword-skill-router.py" --profile codex': True,
    f'bash -c "cd x; python {CFG}/hooks/a.py && sleep 900"': False,
    f"python -c import time; time.sleep(900) {HOME}/.claude/zz-fake-hooks/neg.py": False,
    "python -m pytest tests/hooks/test_x.py": False,
    r"C:\x\claude.exe --type=renderer": False,
}

BOOT = 1_000_000
NOW = BOOT + 6 * 3600


def row(pid, name, cmd, *, parent=True, age_min=60, tree_cpu=5.0, delta=0.0, ppid=1):
    return {"pid": pid, "ppid": ppid, "name": name, "cmd": cmd, "parent_alive": parent,
            "ctime": NOW - age_min * 60, "age_min": age_min, "cpu_delta_s": delta,
            "tree_cpu_s": tree_cpu, "tree_delta_s": delta, "priv_mb": 50}


def verdicts(rows, history, listeners=()):
    w.psutil.boot_time = lambda: BOOT
    w._protect_list = lambda: ["lan-forward"]
    w._listening_pids = lambda: set(listeners)
    s = {"epoch": NOW, "ram_avail_gb": 10, "ram_total_gb": 32, "appinfo_handles": None, "procs": rows}
    _, kills = w.analyse(s, history, do_kill=False)
    return {k["pid"]: k["why"] for k in kills}


def test_hook_matcher():
    assert [c for c, want in HOOK_CASES.items() if w._is_hook(c) != want] == []


def test_kill_policy():
    long_mcp = "node.exe " + "x" * 400 + " npx-cli.js chrome-devtools-mcp@1.9.0"
    rows = [
        row(10, "python.exe", "python worker.py", parent=False),                     # orphan -> kill
        row(11, "powershell.exe", "powershell -File a.ps1 -Loop", parent=False, age_min=60 * 5),
        row(12, "powershell.exe", "powershell -File lan-forward.ps1", parent=False),  # protect.txt
        row(13, "pwsh.exe", "C:\\x\\pwsh.exe"),                                       # bare shell
        row(14, "ssh.exe", "ssh nas -s sftp"),                                # rclone transport
        row(15, "ssh.exe", "ssh -W host:22 jump"),                                    # tunnel
        row(16, "node.exe", long_mcp),                                                # mcp past 300 chars
        row(17, "codex.exe", "codex.exe -c features.prefer_mxc=true -c x=exec_policy"),  # the app
        row(18, "codex.exe", "codex.exe exec -s read-only hello"),                   # idle one-shot
        row(19, "node.exe", "node server.mjs"),                                       # idle 30+ -> kill
        row(20, "node.exe", "node busy.js", tree_cpu=50.0),                           # spent CPU -> keep
        row(21, "node.exe", "node young.js", age_min=10),                             # too young
        row(22, "telegram.exe", "telegram.exe"),                                      # not a worker
        row(23, "python.exe", "python child.py", ppid=19),                            # dies with 19
    ]
    rows[1]["ctime"] = BOOT + 120                                                     # logon autostart
    hist = [{"epoch": NOW - 31 * 60, "cpu": {f"{r['pid']}:{r['ctime']}": 5.0 for r in rows}}]
    got = verdicts(rows, hist)
    assert got == {10: "ORPHAN", 18: "IDLE 30+ min", 19: "IDLE 30+ min"}, got


def test_idle_needs_history():
    rows = [row(30, "node.exe", "node server.mjs")]
    assert verdicts(rows, []) == {}                                    # no 30-min record -> not idle yet


def test_listening_server_is_not_idle():
    rows = [row(40, "python.exe", "python -m http.server 4488")]       # killed for real on 2026-10-11
    hist = [{"epoch": NOW - 31 * 60, "cpu": {f"40:{rows[0]['ctime']}": 5.0}}]
    assert verdicts(rows, hist) == {40: "IDLE 30+ min"}
    assert verdicts(rows, hist, listeners={40}) == {}


def test_remount_only_when_hung_across_runs(tmp_path=None):
    import tempfile
    state = Path(tempfile.mkdtemp())

    class P:
        info = {"pid": 999999, "name": "rclone.exe", "cwd": None,
                "cmdline": ["rclone.exe", "mount", "remote:/", "Z:"]}
    saved = (w.STATE, w._probe_letters, w.psutil.process_iter, w.time.time)
    clock = [1_000_000.0]
    w.STATE, w._probe_letters = state, (lambda L: {"Z"} & set(L))
    w.psutil.process_iter = lambda attrs=None: [P()]
    w.time.time = lambda: clock[0]
    try:
        first = w.check_mounts(do_fix=False)
        assert first and first[0].startswith("SLOW MOUNT Z"), first          # first strike: no remount
        clock[0] += w.MOUNT_CONFIRM_S + 60
        second = w.check_mounts(do_fix=False)
        assert second and second[0].startswith("HUNG MOUNT Z"), second       # still hung next run
        w._probe_letters = lambda L: set()
        assert w.check_mounts(do_fix=False) == []                            # recovered: strike cleared
        w._probe_letters = lambda L: {"Z"} & set(L)
        assert w.check_mounts(do_fix=False)[0].startswith("SLOW MOUNT Z")
    finally:
        w.STATE, w._probe_letters, w.psutil.process_iter, w.time.time = saved


def test_mount_probe_flags_silence():
    real_popen, real_timeout = w.subprocess.Popen, w.MOUNT_TIMEOUT_S

    def fake(argv, **kw):                     # "Z" never answers, "Y" answers at once
        silent = "Z:" in argv[-1]
        cmd = ["ping", "-n", "30", "127.0.0.1"] if silent else ["cmd.exe", "/d", "/c", "exit 0"]
        return real_popen(cmd, **kw)
    w.subprocess.Popen, w.MOUNT_TIMEOUT_S = fake, 2
    try:
        assert w._probe_letters(["Y", "Z"]) == {"Z"}
    finally:
        w.subprocess.Popen, w.MOUNT_TIMEOUT_S = real_popen, real_timeout


if __name__ == "__main__":
    test_hook_matcher()
    test_kill_policy()
    test_idle_needs_history()
    test_listening_server_is_not_idle()
    test_remount_only_when_hung_across_runs()
    test_mount_probe_flags_silence()
    print("ok")
