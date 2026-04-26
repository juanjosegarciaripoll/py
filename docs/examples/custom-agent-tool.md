# Example: Create and Run a Custom Agent Tool

This example wires `py-agent` and `py-agent-tools` together with a simple custom tool.

## 1) Create `agent_with_tool.py`

```python
from __future__ import annotations

from collections.abc import AsyncIterator

from py_agent.agent import Agent, AgentOptions
from py_agent.types import (
    AgentModel,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    Context,
    DoneEvent,
    JsonObject,
    TextContent,
)


class WordCountTool(AgentTool):
    name = "word_count"
    label = "Word Count"
    description = "Count words in a text string"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
        "required": ["text"],
    }

    async def execute(
        self,
        tool_call_id: str,
        params: JsonObject,
        signal: object | None = None,
        on_update: object | None = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        text = str(params["text"])
        count = len(text.split())
        return AgentToolResult(content=[TextContent(text=f"Word count: {count}")])


class StaticStream:
    def __init__(self, message: AssistantMessage) -> None:
        self._message = message

    async def __aiter__(self) -> AsyncIterator[DoneEvent]:
        yield DoneEvent(reason="stop", message=self._message)

    async def result(self) -> AssistantMessage:
        return self._message


async def stream_fn(model: AgentModel, context: Context, config: object) -> StaticStream:
    del model, context, config
    return StaticStream(
        AssistantMessage(content=[TextContent(text="Tooling is configured.")])
    )


async def run() -> Agent:
    agent = Agent(
        AgentOptions(
            initial_model=AgentModel(id="demo", api="demo", provider="demo"),
            initial_tools=[WordCountTool()],
            stream_fn=stream_fn,
        )
    )
    await agent.prompt("Count words in: hello world from py-agent")
    return agent
```

## 2) Why this matters

- Demonstrates `AgentTool` implementation for third-party apps.
- Shows the minimal `stream_fn` bridge contract used by `py-agent`.
- Gives a template for swapping a real provider stream in place of `StaticStream`.

## Related docs

- [py-agent guide](../libraries/py-agent.md)
- [py-agent reference](../references/py-agent.md)
