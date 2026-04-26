# Example: Summarize a Document with OpenAI

This example shows how to call `llm-providers` from an external script to summarize a local text document.

## 1) Create `summarize_document.py`

```python
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from llm_providers.providers.openai import OpenAIProvider
from llm_providers.types import Message, Role, TextContent

DOC_PATH = Path("./example-doc.txt")
MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = "You are a precise summarizer. Respond in 5 bullet points."


async def summarize_document(path: Path) -> str:
    source_text = path.read_text(encoding="utf-8")
    provider = OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"])
    user_prompt = (
        "Summarize the following document for a product manager:\n\n"
        f"{source_text}"
    )
    messages = [
        Message(
            role=Role.USER,
            content=[TextContent(type="text", text=user_prompt)],
        )
    ]

    chunks: list[str] = []
    async for event in provider.stream(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        messages=messages,
        tools=[],
    ):
        if event.delta is None:
            continue
        for block in event.delta.content:
            if isinstance(block, TextContent):
                chunks.append(block.text)

    return "".join(chunks).strip()


def main() -> None:
    summary = asyncio.run(summarize_document(DOC_PATH))
    print(summary)


if __name__ == "__main__":
    main()
```

## 2) Run

```bash
export OPENAI_API_KEY="your-key"
uv run --no-cache python summarize_document.py
```

## Notes

- Swap `OpenAIProvider` for `AnthropicProvider` to change backend.
- For local model servers, use `OpenAICompatibleProvider` with a custom `base_url`.

## Related docs

- [llm-providers guide](../libraries/llm-providers.md)
- [llm-providers reference](../references/llm-providers.md)
