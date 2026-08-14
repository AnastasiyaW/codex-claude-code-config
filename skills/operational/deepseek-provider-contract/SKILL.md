---
name: deepseek-provider-contract
description: Validate a proposed DeepSeek API integration before any key or project context is sent: check thinking-mode tool-call history, strict-schema assumptions, bounded output, and provider data boundaries. Use when integrating DeepSeek, adding DeepSeek tool calls or streaming, debugging DeepSeek 400 after a tool call, or evaluating a DeepSeek harness/MCP. Do NOT use for a generic model comparison, ordinary local coding, or to send a repository transcript to a provider by default.
---

# DeepSeek Provider Contract

This is a local, offline contract check. It neither reads `DEEPSEEK_API_KEY` nor
sends code, transcripts, or secrets. A third-party harness is an implementation
candidate, not a trusted route.

## Use It In This Order

1. Classify the proposed prompt/data. Private archive, credentials, customer
   data, and whole transcripts stay local unless the user explicitly authorizes
   that provider and scope.
2. Freeze the provider model, endpoint, request budget, and fallback in the
   integration plan. Do not inherit defaults from a community wrapper.
3. Save a redacted request-history fixture and run:

   ```text
   python skills/operational/deepseek-provider-contract/scripts/validate_deepseek_history.py fixture.json
   ```

4. Run the provider only in a bounded, opt-in experiment. Record model, endpoint,
   max output, cache-usage fields, request digest, and observed result.
5. Compare against the incumbent on the same frozen task before adding any route
   to a workflow. A passing history fixture proves message lifecycle only; it
   does not prove quality, price, availability, or data handling.

## Required Invariants

- In thinking mode with tools, preserve the provider's complete assistant
  message, including `reasoning_content` and `tool_calls`. Do not rebuild a
  reduced assistant message from `content` alone.
- Each tool result has the exact prior `tool_call_id`.
- If a later user turn follows an assistant tool call, retain that assistant
  `reasoning_content`; DeepSeek documents this as mandatory.
- Use strict schema only with the beta endpoint and only after validating the
  supported JSON Schema subset. Never call a schema "strict" merely because it
  looks valid locally.
- Set output bounds explicitly and make cache hits/misses observability, not a
  correctness promise.

## Adoption Decision

Adopt a DeepSeek route only when all are true:

1. The offline history validator and its regression tests pass.
2. A redacted live canary succeeds with the exact frozen integration.
3. The frozen benchmark beats or materially supplements the current route.
4. Provider data scope and failure fallback are written down.

Otherwise keep this skill and the fixture only; do not install a global MCP.

## Gotchas

- `reasoning_content` may be omitted between ordinary user turns without tools,
  but not after a tool call in thinking mode.
- A response can say cache-hit while quality or latency still changes; measure
  those separately.
- A history normalizer that strips `reasoning_content` can make the next tool
  request fail with HTTP 400 even if the first request succeeded.
- Model names, limits, pricing, and beta semantics are provider facts: re-check
  the official documentation at the integration date.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| HTTP 400 after a tool result | Assistant reasoning was discarded | Preserve the complete assistant tool-call message and rerun the validator |
| Tool JSON is rejected in strict mode | Wrong endpoint or unsupported schema | Use the beta endpoint, validate the schema subset, or turn strict mode off |
| Wrapper works once then loses context | History was normalized too aggressively | Compare its persisted fixture with the provider contract |
| Temptation to add global MCP | Scope and data boundary were skipped | Keep it opt-in until a frozen canary and benchmark pass |

## Sources

- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)
- [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
