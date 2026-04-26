# llm-providers User Guide

`llm-providers` gives you a provider-neutral interface for streaming LLM responses and handling tool call deltas.

## What it solves

- Unified provider interface for Anthropic, OpenAI, and OpenAI-compatible backends
- Shared message and tool datatypes
- Streaming events with text/tool-call deltas and usage information
- Model accessibility checks for interactive setup flows

## Main workflow

1. Build your transcript as `Message` objects.
2. Choose a provider (`OpenAIProvider`, `AnthropicProvider`, or `OpenAICompatibleProvider`).
3. Call `provider.stream(...)` and consume events.
4. Aggregate text/tool-call deltas into your app state.

## Basic usage shape

```python
from llm_providers.providers.openai import OpenAIProvider
from llm_providers.types import Message, Role, TextContent

provider = OpenAIProvider(api_key="...")
messages = [
    Message(
        role=Role.USER,
        content=[TextContent(type="text", text="Summarize this text")],
    )
]
```

Then stream:

```python
async for event in provider.stream(
    model="gpt-4o-mini",
    system_prompt="You are a concise assistant.",
    messages=messages,
    tools=[],
):
    ...
```

## Recommended examples

- [Summarize a document with OpenAI](../examples/summarize-document.md)

## Next reading

- [llm-providers reference](../references/llm-providers.md)
