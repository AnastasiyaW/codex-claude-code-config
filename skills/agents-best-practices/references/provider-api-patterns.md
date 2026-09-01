# Provider API Patterns

## Provider-neutral view

Most provider APIs can support the same architecture:

```text
instructions + context + tool schemas
  -> model output
  -> final response or tool call
  -> application executes tool
  -> application returns tool result
  -> repeat
```

Provider differences are mostly in message shape, state handling, hosted tools, streaming events, and reasoning/tool item formats.

## OpenAI Responses-style APIs

Use Responses-style APIs for new OpenAI-native agent work when available. They provide typed output items, hosted tools, remote MCP support, stateful chaining options, and richer agent-like primitives.

Implementation pattern:

```python
response = client.responses.create(
    model=model,
    instructions=instructions,
    input=input_items,
    tools=visible_tools,
    store=True,
)

for item in response.output:
    if item.type == "function_call":
        result = execute_tool(item.name, item.arguments)
        next_response = client.responses.create(
            model=model,
            previous_response_id=response.id,
            input=[{
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": result,
            }],
        )
```

Use the harness for private/business tools, permission checks, durable state, and audit logs even when hosted tools are available.

## Chat Completions-style and OpenAI-compatible APIs

Use Chat Completions-style APIs when you need compatibility with OpenAI-compatible providers or when your harness already owns message history manually.

Implementation pattern:

```python
messages = [
    {"role": "system", "content": instructions},
    {"role": "user", "content": task},
]

while True:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=visible_tools,
    )
    msg = response.choices[0].message
    messages.append(msg)

    if not msg.tool_calls:
        return msg.content

    for call in msg.tool_calls:
        result = execute_tool(call.function.name, call.function.arguments)
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": result,
        })
```

In this pattern, the harness owns:

- conversation state;
- message trimming;
- compaction;
- previous tool results;
- tool-call ID matching;
- approval pauses;
- retries;
- finalization.

## Anthropic API pattern

With Anthropic APIs, use structured tool-use and tool-result blocks. The model emits a tool-use request; the application executes the operation and returns the corresponding result in the next request.

Provider-neutral shape:

```text
request: messages + tools
response: assistant content with tool-use blocks
application: validate and execute tool-use blocks
next request: user/tool-result content blocks
repeat until final answer
```

Keep the same harness rules: validate arguments locally, check permissions, return structured results, preserve budgets, and trace every step.

## API adapter layer

Use an adapter so the rest of the harness is provider-neutral.

Adapter responsibilities:

```text
normalize input messages/items
normalize tool schemas
normalize model output into ToolCall or FinalAnswer events
normalize tool results back to provider format
handle streaming event conversion
handle provider-specific state chaining
capture token/cost/latency metadata
```

Internal event types should be stable even when provider APIs differ.

## Hosted tools versus client tools

Hosted tools run in provider infrastructure. Client tools run in your application or sandbox.

Hosted tools are useful for:

- web search;
- file search;
- code execution;
- image generation;
- general computer/browser use;
- remote connector calls supported by the provider.

Client tools are preferred for:

- private business APIs;
- tenant-specific permissions;
- regulated data;
- financial actions;
- communication sends;
- state-changing operations;
- custom audit requirements.

Do not outsource business authorization to a hosted tool unless the product explicitly supports and logs the required approval policy.

## Strict schemas

Use strict function schemas where available:

```text
required fields explicit
unknown fields rejected
enums for actions
minimum/maximum constraints
validated IDs
structured outputs
```

Then validate again in the harness before execution.

## Streaming

Streaming can reduce latency but adds complexity.

Rules:

- buffer enough data to validate complete tool calls;
- execute only when a tool call is complete;
- keep result ordering deterministic;
- handle aborts by sending synthetic tool results if required;
- do not stream partial sensitive data to users before output guardrails run.

## State strategies

Options:

```text
stateless: every request sends full selected context
previous-response chaining: provider stores prior state references
conversation object: provider stores conversation items
application event store: harness stores full operational history
```

Even when provider state is used, maintain an application event store for audit, replay, approvals, and evals.

## OpenAI-compatible provider caveats

OpenAI-compatible APIs vary in:

- tool-call schema fidelity;
- support for parallel tool calls;
- strict schema behavior;
- streaming event shapes;
- reasoning item visibility;
- multimodal support;
- context windows;
- storage defaults;
- hosted tools;
- safety behavior.

Do not assume full OpenAI parity. Test the exact provider and model.

## Prompt caching and retention

Provider APIs differ in prompt-cache controls, but the harness rules are provider-neutral:

```text
stable content first
volatile content late
deterministic tool/schema ordering
append-only history until compaction
cache usage fields logged on every call
prompt/tool bundle versions tracked
```

OpenAI APIs expose prompt caching automatically on supported requests and report cached-token usage in response metadata. Some OpenAI APIs also support retention controls for longer-lived cached prefixes.

Anthropic APIs expose prompt caching through provider-specific cache controls and usage fields. Use provider documentation for current marker syntax, TTL behavior, and breakpoint limits.

OpenAI-compatible APIs vary. Confirm whether the provider actually implements prompt caching, how it reports cache hits, and whether routing keys or backend cache settings are available.

See [prompt-caching-and-cost.md](prompt-caching-and-cost.md) for the detailed provider-neutral design pattern.

## Source links

- OpenAI Responses migration: https://developers.openai.com/api/docs/guides/migrate-to-responses
- OpenAI function calling: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI tools: https://developers.openai.com/api/docs/guides/tools
- OpenAI Agents SDK: https://developers.openai.com/api/docs/guides/agents
- OpenAI guardrails and human review: https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- OpenAI prompt caching: https://developers.openai.com/api/docs/guides/prompt-caching
- OpenAI Prompt Caching 201: https://developers.openai.com/cookbook/examples/prompt_caching_201
- Anthropic building effective agents: https://www.anthropic.com/research/building-effective-agents
- Anthropic writing effective tools for agents: https://www.anthropic.com/engineering/writing-tools-for-agents
