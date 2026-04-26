# py-agent User Guide

`py-agent` is the runtime loop that turns message streams and tools into a stateful agent.

## What it solves

- Stateful transcript management
- Tool execution (sequential or parallel)
- Event lifecycle hooks (`message_*`, `tool_execution_*`, turn start/end)
- Steering and follow-up message queues

## Typical integration pattern

1. Create `AgentOptions` with a model definition and `stream_fn`.
2. Register tools implementing `AgentTool`.
3. Call `await agent.prompt(...)`.
4. Observe state or subscribe to events.

## Minimal skeleton

```python
from py_agent.agent import Agent, AgentOptions
from py_agent.types import AgentModel

agent = Agent(
    AgentOptions(
        initial_model=AgentModel(id="gpt-4o-mini", api="openai", provider="openai"),
        stream_fn=...,  # your provider bridge
        initial_tools=[...],
    )
)

await agent.prompt("Summarize this changelog")
```

## Tooling and callbacks

- Use `before_tool_call` to block or rewrite tool arguments.
- Use `after_tool_call` to normalize results or stop the run (`terminate=True`).
- Use `agent.subscribe(...)` for UI/event-driven systems.

## Recommended examples

- [Create and run a custom agent tool](../examples/custom-agent-tool.md)

## Next reading

- [py-agent reference](../references/py-agent.md)
