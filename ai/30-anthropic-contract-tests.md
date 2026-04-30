# 30 — Anthropic contract tests

## Goal

Populate `tests/contract/fixtures/anthropic/` with fixtures captured from the TS `pi-mono/packages/ai/test/` suite, then add a `unittest` driver that runs all fixtures through the harness from task 29.

## Refs

- `29-contract-test-infra.md`
- `pi-mono/packages/ai/test/` (find Anthropic test files; capture HTTP fixtures)
- `00-architecture.md` §14

## Fixtures (8–12 covering the full feature surface, tasks 16–20)

| # | Scenario | Tests |
|---|---|---|
| 1 | Plain text request → text response | basic streaming, MessageStart/Text*/MessageEnd/Done |
| 2 | Multi-block response (text + text) | content blocks with different indices |
| 3 | Single tool call request → tool_use response | tool calling, partial JSON, ID normalization |
| 4 | Tool result round-trip | follow-up request shape with `tool_use_id` substitution |
| 5 | Tool result with text + image content | image block routing |
| 6 | Reasoning enabled — thinking + text response | extended thinking, signature accumulation |
| 7 | Reasoning + tool call (round-trip) | thinking signature preservation through tool-use |
| 8 | Prompt caching enabled | `cache_control` on system + tool defs + last user message |
| 9 | Context overflow error response | error mapping → `ContextOverflowError` |
| 10 | Rate limit response with retry-after | error mapping → `RateLimitError` |
| 11 | In-stream error event | `Error` + `MessageEnd("error")` + `Done`, no exception |
| 12 | Cancellation mid-stream | abort tail emission |

## How to capture

For each scenario:

1. **Locate the TS test.** `pi-mono/packages/ai/test/anthropic.test.ts` (or split files).
2. **Extract the canned SSE body.** TS tests use `vitest` mocks; copy verbatim into `response.txt`.
3. **Extract the expected outbound request shape.** Capture as `request.json` with `method`, `url`, and a `body_match` of fields we care about (e.g. `model`, `messages`, `tools`, `system`, `thinking`).
4. **Compose Python input.** Mirror TS input as `Context(...)` JSON in `input.json`:
   ```json
   {
     "context": {
       "system_prompt": "You are helpful.",
       "messages": [
         {"role": "user", "content": [{"type": "text", "text": "Hi"}]}
       ],
       "tools": []
     },
     "stream_kwargs": {"max_tokens": 1024}
   }
   ```
5. **Generate the golden.** Run the harness; capture actual events. Hand-review against architecture §5; only after review save as `golden_events.json`.
6. **Verify.** Re-run the harness and confirm a passing diff.

For cancellation (#12), `response.txt` is partial (cut mid-stream); input has `stream_kwargs.abort_at_event=N` (a hook the harness understands to set the abort event after N events). Golden ends with `MessageEnd(stop_reason="abort") + Done`.

> Implementer note: task 29's harness doesn't currently support `abort_at_event`. Add it: parse the field, count yielded events, set the abort event at the right point. Document in the harness docstring.

## Driver

`tests/contract/test_anthropic.py`:

```python
import unittest
from pathlib import Path

from llm_providers.providers.anthropic import AnthropicProvider
from llm_providers.models import ModelInfo
from tests.contract.harness import ContractTestCase

FIXTURES = Path(__file__).parent / "fixtures" / "anthropic"


def _model() -> ModelInfo:
    return ModelInfo(
        id="claude-sonnet-4-5",
        api="anthropic-messages",
        name="Claude Sonnet 4.5",
        provider="anthropic",
        base_url="https://api.anthropic.com",
        context_window=200000,
        max_output=8192,
    )


def _make_test(fixture_dir: Path):
    async def test(self):
        await self.run_fixture(fixture_dir)
    test.__name__ = f"test_{fixture_dir.name}"
    return test


class AnthropicContractTests(ContractTestCase):
    fixture_path = FIXTURES
    provider_factory = staticmethod(
        lambda client: AnthropicProvider(api_key="sk-test", client=client)
    )
    model_factory = staticmethod(_model)


# Dynamically attach a method per fixture directory
for d in sorted(FIXTURES.iterdir()):
    if d.is_dir():
        setattr(AnthropicContractTests, f"test_{d.name}", _make_test(d))


if __name__ == "__main__":
    unittest.main()
```

## Acceptance

- [ ] At least 10 fixtures in `tests/contract/fixtures/anthropic/`, covering items 1–11.
- [ ] Item 12 (cancellation) requires the harness extension; if skipped, document why in the fixtures README.
- [ ] `tests/contract/test_anthropic.py` discovers and runs all fixtures.
- [ ] Each fixture's golden hand-reviewed before commit (note in PR description).
- [ ] Coverage for `providers/anthropic.py` ≥ 95% line after this task.
- [ ] `basedpyright` clean.

## Notes

- 15–30 minutes per fixture if HTTP capture is careful. Worth it: a passing contract suite is the only place where the parity claim is auditable.
- TS scenario unreproducible (TS test mocks something we lack equivalent for) → skip + note in fixtures README.
- Hand-edit `golden_events.json` only when sure architecture §5 is wrong about that case — don't force the test to match a buggy provider.
