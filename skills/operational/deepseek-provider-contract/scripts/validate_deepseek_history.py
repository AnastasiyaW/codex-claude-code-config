#!/usr/bin/env python3
"""Validate the documented DeepSeek thinking-mode tool-call message lifecycle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def messages_from(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    messages = payload.get("messages") if isinstance(payload, dict) else payload
    if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
        raise ValueError("fixture must be a JSON message array or an object with a messages array")
    return messages


def validate(messages: list[dict]) -> list[str]:
    errors: list[str] = []
    known_calls: set[str] = set()
    tool_reasoning_required = False
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            reasoning = message.get("reasoning_content")
            if not isinstance(reasoning, str) or not reasoning.strip():
                errors.append(f"messages[{index}]: tool-call assistant message lacks reasoning_content")
            calls = message.get("tool_calls")
            if not isinstance(calls, list):
                errors.append(f"messages[{index}]: tool_calls must be an array")
            else:
                for call in calls:
                    if isinstance(call, dict) and isinstance(call.get("id"), str):
                        known_calls.add(call["id"])
                    else:
                        errors.append(f"messages[{index}]: tool call lacks string id")
            tool_reasoning_required = True
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                errors.append(f"messages[{index}]: tool result lacks tool_call_id")
            elif call_id not in known_calls:
                errors.append(f"messages[{index}]: tool_call_id does not match an earlier assistant call")
        elif role == "user" and tool_reasoning_required:
            # The earlier assistant record is still present in this fixture; that is
            # the observable local proof that the next request will retain it.
            tool_reasoning_required = False
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="redacted JSON history fixture")
    args = parser.parse_args(argv)
    try:
        errors = validate(messages_from(args.fixture))
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
