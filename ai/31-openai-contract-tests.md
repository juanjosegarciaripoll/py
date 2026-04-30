# 31 — OpenAI contract tests

## Goal

Same as task 30, for OpenAI Completions, OpenAI Responses, and OpenAI-compatible.

## Refs

- `29-contract-test-infra.md`
- `30-anthropic-contract-tests.md` (parallel; same procedure)
- `pi-mono/packages/ai/test/` (find openai-completions, openai-responses, faux test files)

## Fixtures

### `tests/contract/fixtures/openai_completions/` (8 fixtures)

| # | Scenario |
|---|---|
| 1 | Plain text streaming |
| 2 | Image-bearing user message → text response |
| 3 | Single tool call → tool result round-trip |
| 4 | Tool result with image content (synthetic user follow-up on next request) |
| 5 | Multi-tool-call response |
| 6 | Context-overflow 400 error |
| 7 | Rate-limit 429 with retry-after |
| 8 | Cancellation mid-stream |

### `tests/contract/fixtures/openai_responses/` (8 fixtures)

| # | Scenario |
|---|---|
| 1 | Plain text streaming via Responses API |
| 2 | Reasoning model: reasoning + text response, signature/encrypted_content preserved |
| 3 | Reasoning + tool call round-trip (reasoning item precedes tool call) |
| 4 | Tool call with `function_call_output` round-trip |
| 5 | `response.incomplete` with `reason="max_output_tokens"` → `MessageEnd("max_tokens")` |
| 6 | `response.incomplete` with `reason="content_filter"` → `MessageEnd("refusal")` |
| 7 | `response.failed` mid-stream → `Error` + `MessageEnd("error")` + `Done` |
| 8 | Auth 401 error |

### `tests/contract/fixtures/openai_compatible/` (3 fixtures)

| # | Scenario |
|---|---|
| 1 | Local Ollama-style request: no Authorization header, plain streaming |
| 2 | Compat server with `supports_usage_in_streaming=False` — `stream_options` omitted |
| 3 | Compat server tool call (verifies inheritance of task 23 logic) |

## Drivers

Three driver files, same dynamic-method-attachment pattern as task 30:

- `tests/contract/test_openai_completions.py`
- `tests/contract/test_openai_responses.py`
- `tests/contract/test_openai_compatible.py`

Provider/model factories per file:

```python
# Completions
provider_factory = lambda client: OpenAIChatCompletionsProvider(api_key="sk-test", client=client)
model_factory = lambda: ModelInfo(id="gpt-4o", api="openai-completions", ...)

# Responses
provider_factory = lambda client: OpenAIResponsesProvider(api_key="sk-test", client=client)
model_factory = lambda: ModelInfo(id="o3", api="openai-responses", reasoning=True, ...)

# Compatible
provider_factory = lambda client: OpenAICompatibleProvider(
    api_key=None, base_url="http://localhost:11434/v1", client=client,
)
model_factory = lambda: ModelInfo(
    id="llama3.1", api="openai-compatible", base_url="http://localhost:11434/v1", ...,
    compat={"supports_usage_in_streaming": False},
)
```

## Acceptance

- [ ] 8 fixtures in `fixtures/openai_completions/`.
- [ ] 8 fixtures in `fixtures/openai_responses/`.
- [ ] 3 fixtures in `fixtures/openai_compatible/`.
- [ ] All driver files run via `unittest discover`.
- [ ] Coverage for `providers/openai.py` ≥ 95% line.
- [ ] `basedpyright` clean.

## Notes

- The reasoning fixture (Responses #2) is the most important for verifying task 24 round-trip: golden_events must include `ReasoningEnd(signature="...")` with the encrypted blob, and a *follow-up fixture* (#3) sends an assistant message containing that ReasoningPart back and asserts the wire body has the correct `reasoning` item.
- For the compatible adapter (#1), the request must have **no `Authorization` header**. Add an explicit header check in the driver — `body_match` only checks the body. Implementer should extend `assert_request_matches` (task 29) to optionally check `headers_must_be_absent: ["Authorization"]` if not already supported.
