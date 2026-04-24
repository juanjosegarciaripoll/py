# llm-providers

`llm-providers` is the Python package that encapsulates LLM API integrations for this workspace.
It provides a shared provider interface, common message/tool types, and concrete provider implementations.

## Goals

- Keep provider logic isolated from agent/runtime code.
- Offer a consistent streaming API across vendors.
- Maintain strict typing with minimal dependencies.

## Package Layout

- `src/types.py`: Shared dataclasses and JSON typing aliases used by providers.
- `src/provider.py`: Abstract `Provider` interface.
- `src/api_registry.py`: Provider registry and API-key helper.
- `src/models.py`: Static model metadata registry.
- `src/providers/anthropic.py`: Anthropic streaming implementation.
- `src/providers/openai.py`: OpenAI chat-completions streaming implementation.
- `src/providers/openai_compatible.py`: OpenAI-compatible streaming implementation (custom base URL).

## Core Interface

All providers implement:

- `Provider.stream(model, system_prompt, messages, tools) -> AsyncIterator[AssistantMessageEvent]`

Streaming yields `AssistantMessageEvent` values containing:

- `delta`: partial assistant message content
- `usage`: token usage information (when available)
- `finish_reason`: stream completion reason (when available)

## Basic Usage

```python
from llm_providers.src.providers.openai import OpenAIProvider
from llm_providers.src.types import Message, Role, TextContent

provider = OpenAIProvider(api_key="...")
messages = [
    Message(role=Role.USER, content=[TextContent(type="text", text="Hello")]),
]

async for event in provider.stream(
    model="gpt-4o-mini",
    system_prompt="You are helpful.",
    messages=messages,
    tools=[],
):
    if event.delta:
        print(event.delta.content)
```

## Validation

From the repository root:

```bash
uv run ruff check .
uv run basedpyright .
uv run mypy .
```

## Notes

- Current implementations prioritize text streaming; image/tool-result conversion is intentionally minimal and can be expanded in later phases.
- Unit test scaffolding exists, but provider behavior tests should be expanded as implementation evolves.
