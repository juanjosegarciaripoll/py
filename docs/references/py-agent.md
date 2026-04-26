# py-agent Reference

## Core modules

- `py_agent.types`
- `py_agent.agent_loop`
- `py_agent.agent`
- `py_agent.proxy`

## Public API exports

From `py_agent.__init__`:

- High-level runtime:
  - `Agent`, `AgentOptions`
- Low-level loop:
  - `agent_loop`, `agent_loop_continue`
  - `run_agent_loop`, `run_agent_loop_continue`
  - `AgentEventStream`
- Proxy helper:
  - `stream_proxy_from_events`
- Types:
  - `AgentModel`, `AgentContext`, `AgentMessage`, `AgentTool`, `AgentToolResult`
  - `AgentEvent`, `AssistantMessageEvent`
  - `ToolExecutionMode`, `QueueMode`, `ThinkingLevel`, `StopReason`

## Agent lifecycle

Common event sequence:

1. `agent_start`
2. `turn_start`
3. `message_start` / `message_update` / `message_end`
4. `tool_execution_start` / `tool_execution_update` / `tool_execution_end` (if tools run)
5. `turn_end`
6. `agent_end`

## Integration notes

- `stream_fn` bridges `py-agent` to any LLM backend.
- `convert_to_llm` controls transcript transformation before provider calls.
- `before_tool_call` and `after_tool_call` are primary policy/hook extension points.

## Package docs replaced by this page

This page subsumes package-level README material in `py-agent/README.md`.
