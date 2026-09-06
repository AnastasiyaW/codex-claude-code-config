#!/usr/bin/env python3
"""Validate the documented DeepSeek thinking-mode tool-call message lifecycle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def fixture_from_payload(payload: object) -> tuple[list[dict], bool]:
    if not isinstance(payload, dict):
        raise ValueError("fixture must be an object with messages and outbound_request.tools")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
        raise ValueError("fixture messages must be an array of objects")
    outbound_request = payload.get("outbound_request")
    if not isinstance(outbound_request, dict) or "tools" not in outbound_request:
        raise ValueError("fixture must declare outbound_request.tools")
    return messages, bool(outbound_request["tools"])


def fixture_from(path: Path) -> tuple[list[dict], bool]:
    return fixture_from_payload(json.loads(path.read_text(encoding="utf-8")))


def validate(messages: list[dict], *, outbound_tools: bool) -> list[str]:
    errors: list[str] = []
    known_calls: set[str] = set()
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant":
            reasoning = message.get("reasoning_content")
            if (outbound_tools or message.get("tool_calls")) and (
                not isinstance(reasoning, str) or not reasoning.strip()
            ):
                errors.append(f"messages[{index}]: assistant message lacks reasoning_content")
        if role == "assistant" and message.get("tool_calls"):
            calls = message.get("tool_calls")
            if not isinstance(calls, list):
                errors.append(f"messages[{index}]: tool_calls must be an array")
            else:
                for call in calls:
                    if isinstance(call, dict) and isinstance(call.get("id"), str):
                        known_calls.add(call["id"])
                    else:
                        errors.append(f"messages[{index}]: tool call lacks string id")
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                errors.append(f"messages[{index}]: tool result lacks tool_call_id")
            elif call_id not in known_calls:
                errors.append(f"messages[{index}]: tool_call_id does not match an earlier assistant call")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="redacted JSON history fixture")
    args = parser.parse_args(argv)
    try:
        messages, outbound_tools = fixture_from(args.fixture)
        errors = validate(messages, outbound_tools=outbound_tools)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[deepseek-history] INVALID: {exc}")
        return 2
    if errors:
        print(f"[deepseek-history] FAIL: {len(errors)} issue(s)")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("[deepseek-history] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
