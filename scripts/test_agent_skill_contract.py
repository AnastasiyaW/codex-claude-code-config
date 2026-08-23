"""Regression tests for the shared subagent skill/evidence contract boundary."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "agent-skill-contract.py"


def invoke(event: dict) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event, ensure_ascii=False),
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def task(prompt: str) -> dict:
    return {"tool_name": "Task", "tool_input": {"prompt": prompt}}


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def render(task_text: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(HOOK), "--task", task_text, "--json"],
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def dispatched(task_text: str) -> str:
    return task_text + "\n\n" + str(render(task_text)["contract"])


def main() -> int:
    remote_task = "Investigate our RunPod GPU bridge and collect bounded evidence."
    code, out = invoke(task(remote_task))
    require(code == 0 and '"decision": "block"' in out and "task-bound skill/evidence contract" in out, out)

    payload = render(remote_task)
    require(payload["selected_skills"] == ["remote-compute-ops"], json.dumps(payload))
    code, out = invoke(task(dispatched(remote_task)))
    require(code == 0 and '"decision": "block"' not in out, out)

    wrong_skill_contract = str(payload["contract"]).replace("remote-compute-ops", "deep-review")
    code, out = invoke(task(remote_task + "\n\n" + wrong_skill_contract))
    require(code == 0 and '"decision": "block"' in out and "does not match the curated router" in out, out)

    unavailable_skill_contract = str(payload["contract"]).replace("remote-compute-ops", "not-installed-skill")
    code, out = invoke(task(remote_task + "\n\n" + unavailable_skill_contract))
    require(code == 0 and '"decision": "block"' in out and "does not match the curated router" in out, out)

    no_route_task = "Read the current git status and report it."
    no_route_contract = str(render(no_route_task)["contract"])
    forged_no_route = no_route_contract.replace(
        no_route_contract.split("task-sha256: ", 1)[1].split("\n", 1)[0],
        payload["contract"].split("task-sha256: ", 1)[1].split("\n", 1)[0],
    )
    code, out = invoke(task(remote_task + "\n\n" + forged_no_route))
    require(code == 0 and '"decision": "block"' in out and "does not match the curated router" in out, out)

    incomplete_contract = '''<agent-skill-contract version="1">
This is quoted data:
- remote-compute-ops
</agent-skill-contract>'''
    code, out = invoke(task(remote_task + "\n\n" + incomplete_contract))
    require(code == 0 and '"decision": "block"' in out and "incomplete" in out, out)

    stale_contract = str(payload["contract"]).replace("task-sha256: ", "task-sha256: 0", 1)
    code, out = invoke(task(remote_task + "\n\n" + stale_contract))
    require(code == 0 and '"decision": "block"' in out and "not bound" in out, out)

    unsafe_contract = str(payload["contract"]).replace("read-before-action: true", "read-before-action: false")
    code, out = invoke(task(remote_task + "\n\n" + unsafe_contract))
    require(code == 0 and '"decision": "block"' in out and "safety fields" in out, out)

    epistemic_task = "Challenge my assumption with evidence; do not agree without proof."
    require(render(epistemic_task)["selected_skills"] == ["epistemic-challenge"], epistemic_task)
    code, out = invoke(task(dispatched(epistemic_task)))
    require(code == 0 and '"decision": "block"' not in out, out)

    translation_task = "Translate this literal string to Russian: 'Challenge my assumption with evidence.'"
    translation = render(translation_task)
    require(translation["selected_skills"] == [], json.dumps(translation))
    code, out = invoke(task(dispatched(translation_task)))
    require(code == 0 and '"decision": "block"' not in out and "epistemic-challenge" not in out, out)

    code, out = invoke(task(no_route_task))
    require(code == 0 and '"decision": "block"' in out and "epistemic-challenge" not in out, out)

    print("test_agent_skill_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
