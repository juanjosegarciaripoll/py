# 32 — Live smoke harness (env-gated)

## Goal

`tests/live/` with smoke tests hitting real provider APIs. Gated by `LLM_PROVIDERS_LIVE=1` so they don't run in normal CI; manual pre-release verification.

## Refs

- `00-architecture.md` §14

## Files

```
tests/live/
  __init__.py
  README.md
  test_anthropic_live.py
  test_openai_live.py
```

## Layout

Each test:

1. Skips if `os.environ.get("LLM_PROVIDERS_LIVE") != "1"`.
2. Skips if the relevant API key isn't set.
3. Hits the real API with the smallest meaningful request.
4. Asserts a small invariant (event types present, final `MessageEnd` has positive `output_tokens`, etc.).

## `test_anthropic_live.py`

```python
import os
import unittest

import llm_providers
from llm_providers import Context, TextPart, UserMessage


@unittest.skipIf(
    os.environ.get("LLM_PROVIDERS_LIVE") != "1",
    "live tests skipped (set LLM_PROVIDERS_LIVE=1 to run)",
)
@unittest.skipIf(
    not os.environ.get("ANTHROPIC_API_KEY"),
    "ANTHROPIC_API_KEY not set",
)
class AnthropicLive(unittest.IsolatedAsyncioTestCase):
    async def test_basic_streaming(self):
        ctx = Context(
            system_prompt="Reply with exactly: OK",
            messages=[UserMessage(content=[TextPart(text="Hello.")])],
        )
        events = []
        async for ev in llm_providers.stream(
            "claude-haiku-4-5",  # fast + cheap
            ctx,
            max_tokens=32,
        ):
            events.append(ev)
        types = [type(e).__name__ for e in events]
        self.assertIn("MessageStart", types)
        self.assertIn("TextDelta", types)
        self.assertIn("MessageEnd", types)
        self.assertEqual(types[-1], "Done")

    async def test_tool_call(self):
        ctx = Context(
            messages=[UserMessage(content=[TextPart(
                text="Read the file /tmp/x using the read_file tool, then say done."
            )])],
            tools=[llm_providers.ToolDefinition(
                name="read_file",
                description="Read a file from disk",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            )],
        )
        result = await llm_providers.complete("claude-haiku-4-5", ctx, max_tokens=128)
        from llm_providers import ToolCallPart
        tool_calls = [p for p in result.content if isinstance(p, ToolCallPart)]
        self.assertGreater(len(tool_calls), 0)
        self.assertEqual(tool_calls[0].name, "read_file")
```

## `test_openai_live.py`

Same shape, hitting `gpt-4o-mini` (cheap) for Completions and `o3-mini` (when available) for Responses. Two test methods: `test_basic_streaming_completions` and `test_basic_streaming_responses`.

## `README.md`

```markdown
# Live smoke tests

These tests hit real provider APIs. Skipped by default.

## Run

    LLM_PROVIDERS_LIVE=1 ANTHROPIC_API_KEY=... uv run python -m unittest tests.live.test_anthropic_live
    LLM_PROVIDERS_LIVE=1 OPENAI_API_KEY=... uv run python -m unittest tests.live.test_openai_live

## Cost

Each test makes one or two small requests against cheap models (haiku,
gpt-4o-mini). Total cost per full run < $0.01.

## When to run

- Before tagging a release.
- After any provider-adapter change touching request shape or streaming.
- Never in CI — manual.
```

## Acceptance

- [ ] `tests/live/test_anthropic_live.py` and `tests/live/test_openai_live.py` exist with the structure above.
- [ ] Both files skip cleanly when `LLM_PROVIDERS_LIVE` is unset (no module-import errors, clean skip messages).
- [ ] Both files skip cleanly when API keys aren't set, even with `LLM_PROVIDERS_LIVE=1`.
- [ ] Running with real keys against a known-good environment passes (recorded in PR description).
- [ ] `tests/live/README.md` documents how to run, cost, when to run.
- [ ] `basedpyright` clean.

## Notes

- Smoke, not contract. Don't try to make them deterministic — model outputs vary. Assert structural invariants only (event types present, token counts positive, tool call name correct).
- Use the cheapest model in each family. Reasoning tests cost more — gate behind a second env var like `LLM_PROVIDERS_LIVE_REASONING=1` if the implementer wants to keep the default cheap.
- Don't add live tests for the OpenAI-compatible adapter unless a free local server is in scope. Document that compat-adapter live testing is the user's responsibility (each compat server is different).
