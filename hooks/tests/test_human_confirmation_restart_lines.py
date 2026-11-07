"""A question on its own line does not void the owner's restart request; doubt about the restart still does."""
import importlib.util
import pathlib
import tempfile

HOOK = pathlib.Path(__file__).resolve().parents[1] / "human-confirmation-guard.py"
spec = importlib.util.spec_from_file_location("hcg_restart_lines", HOOK)
hcg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hcg)
hcg.APPROVAL_LOG = pathlib.Path(tempfile.mkdtemp()) / "approvals.jsonl"

CMD = "ssh admin@testvm shutdown /r /t 5"
CASES = [
    ("что имеем?\nперезапусти test-gpu-20261101", True),
    ("перезапусти test-gpu-20261101", True),
    ("перезапусти test-gpu-20261101?", False),
    ("что имеем? перезапусти test-gpu-20261101", False),
    ("погоди\nперезапусти test-gpu-20261101", False),
    ("что имеем?\nне перезапускай test-gpu-20261101", False),
    ("что имеем?\nнет, перезапусти потом", False),
    ("что имеем?", False),
]


def test_restart_lines():
    for prompt, want in CASES:
        ok, why = hcg._restart_approval(CMD, prompt, "", {"session_id": "t"})
        assert ok is want, (prompt, ok, why)


if __name__ == "__main__":
    test_restart_lines()
    print("ok", len(CASES))
