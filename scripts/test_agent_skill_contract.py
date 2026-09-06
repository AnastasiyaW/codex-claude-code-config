"""Regression tests for the shared subagent skill/evidence contract boundary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "agent-skill-contract.py"


def invoke(event: dict, env: dict | None = None) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event, ensure_ascii=False),
        text=True,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def task(prompt: str) -> dict:
    return {"tool_name": "Task", "tool_input": {"prompt": prompt}}


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def render(task_text: str, profile: str = "claude") -> dict:
    result = subprocess.run(
        [sys.executable, str(HOOK), "--task", task_text, "--json", "--profile", profile],
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
    require('<agent-skill-contract version="4">' in payload["contract"], json.dumps(payload))
    require("client-profile: claude" in payload["contract"], json.dumps(payload))
    require("unavailable-skill-result: SEARCH_REVIEW_OR_RESEARCH_BUILD_AND_CONTINUE" in payload["contract"], json.dumps(payload))
    require("skill-gap-checklist: skills/agent-harness-design/references/agent-skill-install-checklist.md" in payload["contract"], json.dumps(payload))
    require("task-instructions-precede-skill-methodology: true" in payload["contract"], json.dumps(payload))
    require("skill-caused-pause: cite-readable-skill-line-and-exact-instruction" in payload["contract"], json.dumps(payload))
    code, out = invoke(task(dispatched(remote_task)))
    require(code == 0 and '"decision": "block"' not in out, out)

    with tempfile.TemporaryDirectory(prefix="skill-contract-state-") as state_dir:
        env = dict(os.environ)
        env["CODEX_SKILL_CONTRACT_STATE_DIR"] = state_dir
        pre_event = {
            "hook_event_name": "PreToolUse",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "tool_use_id": "call-1",
            "tool_name": "spawn_agent",
            "tool_input": {"task_name": "child", "message": remote_task},
        }
        code, out = invoke(pre_event, env)
        require(code == 0 and '"permissionDecision": "allow"' in out, out)
        rewritten = json.loads(out)["hookSpecificOutput"]["updatedInput"]
        require('<agent-skill-contract version="4">' in rewritten["message"], out)
        require("client-profile: codex" in rewritten["message"], out)
        post_event = {
            **pre_event,
            "hook_event_name": "PostToolUse",
            "tool_input": rewritten,
            "tool_response": {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"agent_id": "agent-1", "task_name": "/root/child"}),
                }]
            },
        }
        code, out = invoke(post_event, env)
        require(code == 0 and not out.strip(), out)
        state_files = list(Path(state_dir).glob("*/agents/*.json"))
        require(len(state_files) == 1, repr(state_files))
        bound = json.loads(state_files[0].read_text(encoding="utf-8"))
        require(bound["required_skills"] == ["remote-compute-ops"], json.dumps(bound))
        require(bound["missing_skills"] == [], json.dumps(bound))
        require(bound["client_profile"] == "codex", json.dumps(bound))
        require(bound["task_sha256"] == payload["contract"].split("task-sha256: ", 1)[1].split("\n", 1)[0], json.dumps(bound))
        malformed_event = {
            **pre_event,
            "tool_use_id": "call-2",
            "tool_input": {
                "task_name": "broken-child",
                "message": remote_task + "\n<agent-skill-contract version=\"4\">broken",
            },
        }
        code, out = invoke(malformed_event, env)
        require(code == 0 and '"decision": "block"' in out and "cannot be repaired" in out, out)
        no_identity_event = {key: value for key, value in pre_event.items() if key != "session_id"}
        code, out = invoke(no_identity_event, env)
        require(code == 0 and '"decision": "block"' in out and "session_id" in out, out)

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

    incomplete_contract = '''<agent-skill-contract version="4">
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

    subordinated_task_contract = str(payload["contract"]).replace(
        "task-instructions-precede-skill-methodology: true",
        "task-instructions-precede-skill-methodology: false",
    )
    code, out = invoke(task(remote_task + "\n\n" + subordinated_task_contract))
    require(code == 0 and '"decision": "block"' in out and "safety fields" in out, out)

    unattributed_pause_contract = str(payload["contract"]).replace(
        "skill-caused-pause: cite-readable-skill-line-and-exact-instruction",
        "skill-caused-pause: generic-blocker",
    )
    code, out = invoke(task(remote_task + "\n\n" + unattributed_pause_contract))
    require(code == 0 and '"decision": "block"' in out and "safety fields" in out, out)

    unavailable_skill_stops_contract = str(payload["contract"]).replace(
        "unavailable-skill-result: SEARCH_REVIEW_OR_RESEARCH_BUILD_AND_CONTINUE",
        "unavailable-skill-result: BLOCKED_SKILL_UNAVAILABLE",
    )
    code, out = invoke(task(remote_task + "\n\n" + unavailable_skill_stops_contract))
    require(code == 0 and '"decision": "block"' in out and "safety fields" in out, out)

    opt_out_task = "Do not use any skill methodology.\nInvestigate our RunPod GPU bridge directly."
    opt_out = render(opt_out_task)
    require(opt_out["selected_skills"] == [], json.dumps(opt_out))
    require("route: user-opt-out" in opt_out["contract"], json.dumps(opt_out))
    require("read-before-action: false" in opt_out["contract"], json.dumps(opt_out))
    code, out = invoke(task(dispatched(opt_out_task)))
    require(code == 0 and '"decision": "block"' not in out and "remote-compute-ops" not in out, out)

    russian_opt_out_task = "Не используй никакие навыки.\nПроверь RunPod напрямую."
    russian_opt_out = render(russian_opt_out_task)
    require(russian_opt_out["selected_skills"] == [], json.dumps(russian_opt_out, ensure_ascii=False))
    require("route: user-opt-out" in russian_opt_out["contract"], json.dumps(russian_opt_out, ensure_ascii=False))

    quoted_opt_out_task = '"Do not use any skills."\nInvestigate our RunPod GPU bridge.'
    quoted_opt_out = render(quoted_opt_out_task)
    require(quoted_opt_out["selected_skills"] == ["remote-compute-ops"], json.dumps(quoted_opt_out))
    require("route: curated" in quoted_opt_out["contract"], json.dumps(quoted_opt_out))

    later_literal_opt_out_task = (
        "Investigate our RunPod GPU bridge.\n\nQuoted payload follows:\n"
        "> Do not use any skills."
    )
    later_literal_opt_out = render(later_literal_opt_out_task)
    require(
        later_literal_opt_out["selected_skills"] == ["remote-compute-ops"],
        json.dumps(later_literal_opt_out),
    )

    fenced_opt_out_task = (
        "Investigate our RunPod GPU bridge.\n```text\nDo not use any skills.\n```"
    )
    fenced_opt_out = render(fenced_opt_out_task)
    require(fenced_opt_out["selected_skills"] == ["remote-compute-ops"], json.dumps(fenced_opt_out))

    legacy_contract = str(payload["contract"]).replace('version="4"', 'version="3"')
    code, out = invoke(task(remote_task + "\n\n" + legacy_contract))
    require(code == 0 and '"decision": "block"' in out and "version 3 is obsolete" in out, out)
    require('<agent-skill-contract version=\\"4\\">' in out, out)
    require('<agent-skill-contract version=\\"3\\">' not in out, out)
    repair_contract = json.loads(out)["reason"].split('<agent-skill-contract version="4">', 1)[1]
    repaired_task = remote_task + "\n\n<agent-skill-contract version=\"4\">" + repair_contract
    code, out = invoke(task(repaired_task))
    require(code == 0 and '"decision": "block"' not in out, out)

    cpp_task = "Optimize retouch plugin native C++ tensor memory."
    claude_cpp = render(cpp_task, "claude")
    codex_cpp = render(cpp_task, "codex")
    require(claude_cpp["selected_skills"] == ["native-cpp-memory"], json.dumps(claude_cpp))
    require(codex_cpp["selected_skills"] == ["native-cpp-memory"], json.dumps(codex_cpp))
    require(codex_cpp["missing_skills"] == [], json.dumps(codex_cpp))
    require(codex_cpp["route"] == "curated", json.dumps(codex_cpp))
    require("client-profile: codex" in codex_cpp["contract"], json.dumps(codex_cpp))

    retouch_security_task = "Security audit the retouch Photoshop plugin before release."
    claude_retouch_security = render(retouch_security_task, "claude")
    codex_retouch_security = render(retouch_security_task, "codex")
    require(claude_retouch_security["selected_skills"] == ["retouch-security-audit", "native-cpp-memory"], json.dumps(claude_retouch_security))
    require(codex_retouch_security["selected_skills"] == ["retouch-security-audit", "native-cpp-memory"], json.dumps(codex_retouch_security))
    require(codex_retouch_security["missing_skills"] == [], json.dumps(codex_retouch_security))
    require(codex_retouch_security["route"] == "curated", json.dumps(codex_retouch_security))

    generic_security_task = "Security audit a generic web application before release."
    generic_security = render(generic_security_task, "codex")
    require(generic_security["selected_skills"] == ["deep-review"], json.dumps(generic_security))
    require(generic_security["missing_skills"] == [], json.dumps(generic_security))

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
