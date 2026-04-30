# Architecture — `llm-providers` rebuild

Source of truth. Every task references this. Conflict → this wins.

Decisions: 2026-04-30. Audit: `FEATURES_LLM_PROVIDERS.md`.

---

## 1. Scope

In: Anthropic, OpenAI Completions, OpenAI Responses, OpenAI-compatible (thin Completions subclass).
Out: Google, Mistral, Bedrock, Azure, OpenAI Codex, Copilot, faux. Don't foreclose adding any later.
Within in-scope providers: full feature depth (streaming, tools, reasoning round-trip, prompt caching, abort, error normalization, telemetry, cross-provider handoff).

## 2. Async

- Async-first. Provider primitives `async def`. Streaming = `AsyncIterator[Event]`.
- `sync_stream()` / `sync_complete()` thin wrappers via `asyncio.run` (or `anyio.from_thread`).
- HTTP via `httpx.AsyncClient`. No threading, no `run_in_executor`.

## 3. Types

- One module of dataclasses. Old `types.py` + `communication.py` deleted.
- `@dataclass(slots=True)`, frozen for immutable values (events, parts).
- PEP-604 unions, `Literal["..."]` discriminator, `match`/`case` for dispatch.
- Tool input schemas = JSON-Schema dicts supplied by callers. Library does not generate them. No pydantic.

## 4. Public API

- Provider classes (`AnthropicProvider`, `OpenAIChatCompletionsProvider`, `OpenAIResponsesProvider`, `OpenAICompatibleProvider`) usable directly.
- Top-level `stream(model=, messages=, **opts)` / `complete(...)`. Sync: `sync_stream` / `sync_complete`.
- Resolution:
  1. `api=` kwarg → use it (synthesize ModelInfo if model not in catalogue).
  2. Catalogue lookup → dispatch by model's `api`.
  3. Prefix fallback: `claude-*` → anthropic, `gpt-*` → openai-completions, `o1*`/`o3*`/`o4*` → openai-responses. Else raise.
- Self-registration on `import llm_providers.providers`.

## 5. Streaming events

Frozen dataclasses with `type: Literal[...]` discriminator:

```
MessageStart(id, model, provider, api)
TextStart(part_id) / TextDelta(part_id, text) / TextEnd(part_id, text)
ReasoningStart(part_id) / ReasoningDelta(part_id, text)
ReasoningEnd(part_id, text, signature, redacted, provider_metadata)
ToolCallStart(part_id, id, name)
ToolCallDelta(part_id, arguments_delta)         # raw JSON fragment
ToolCallEnd(part_id, id, name, arguments)       # parsed dict
MessageEnd(stop_reason, usage, response_id)
Error(error)
Done()
```

Rules:
- `part_id` = stable string per content part. Different parts may interleave.
- `arguments_delta` = wire fragments verbatim. No buffering, no trim.
- `ToolCallEnd.arguments` = parsed via `utils/json_parse.py`.
- `Usage` only on `MessageEnd`. Mid-stream usage updates folded internally.
- `Done` always last. `Error` precedes `Done` on failure; `MessageEnd(stop_reason="error")` precedes `Error`.
- Cancellation: `MessageEnd(stop_reason="abort")` → `Done`. No `Error`.

`StopReason` literal: `"end_turn" | "max_tokens" | "tool_use" | "stop_sequence" | "refusal" | "error" | "abort"`.

Native → normalized mapping:
- Anthropic: `end_turn`/`max_tokens`/`tool_use`/`stop_sequence` pass through; `refusal` → `refusal`.
- OpenAI: `stop` → `end_turn`, `length` → `max_tokens`, `tool_calls`/`function_call` → `tool_use`, `content_filter` → `refusal`.

## 6. Errors

```
LLMProviderError(message, provider, provider_error: dict | None)
├── AuthError                       # 401/403
├── RateLimitError(retry_after)     # 429
├── ContextOverflowError            # token limit; detected via utils/overflow.py
├── BadRequestError                 # 400 (non-overflow)
├── APIError(status_code)           # 5xx + unexpected
├── TransportError(__cause__)       # network/DNS/TLS — wraps httpx
└── AbortError                      # explicit abort-event path only
```

`ContextOverflowError` triggers compaction in `py-agent`.

## 7. Cancellation

- Primary: `asyncio.CancelledError`. Generator catches it, emits `MessageEnd(stop_reason="abort")` + `Done`, re-raises.
- Optional: `stream(..., abort: asyncio.Event | None = None)`. Polled between chunks; same shutdown path on `.set()`.

## 8. Tools

- `ToolDefinition(name, description, input_schema: dict, cache: bool=False)`. No caller-arg validation.
- Streaming: emit raw `ToolCallDelta(arguments_delta)`. Library buffers per `part_id`, parses with tolerant parser at `ToolCallEnd`. Parser handles unterminated strings, trailing commas, missing closers, mid-string unicode escapes.
- IDs: library issues `call_<8-hex>` at `ToolCallStart`. Per-stream map `library_id → provider_id`. `ToolCallPart.provider_id` carries it on the message; outbound `ToolResultMessage` substitutes the original on the wire. Enables cross-provider handoff.
- Tool-result content = `list[TextPart | ImagePart]`. Anthropic inlines images in `tool_result`. OpenAI Completions splits images into a synthetic follow-up user message. OpenAI-compatible falls back to text-only.

## 9. Prompt caching

- Explicit: `TextPart(text, cache: bool=False)`, `ToolDefinition(..., cache: bool=False)`. Anthropic → `cache_control: {"type": "ephemeral"}`. OpenAI ignores (auto-cache).
- `Context.system_prompt_cache: bool=False`. When True + non-empty prompt → array form on wire with `cache_control`.
- `auto_cache(context) → context` adds markers heuristically (system + tools + last user/assistant text part). Used by callers; not implicit.
- Usage: `Usage.cache_read_tokens` ← Anthropic `cache_read_input_tokens` / OpenAI `prompt_tokens_details.cached_tokens`. `Usage.cache_write_tokens` ← Anthropic `cache_creation_input_tokens`.

## 10. Reasoning round-trip

- `ReasoningPart(text, signature, redacted, provider_metadata)`. Signature opaque, mandatory for Anthropic round-trip; OpenAI Responses uses `encrypted_content` blob in `signature` + opaque IDs in `provider_metadata`.
- Default behavior: preserve. `strip_reasoning(messages)` available for callers who don't want it.
- Anthropic redacted thinking → `redacted=True`, encrypted blob in `provider_metadata["data"]`.

## 11. Models

```python
ModelInfo(
    id, api, name, provider, base_url,
    context_window, max_output,
    vision: bool, tool_use: bool, reasoning: bool, prompt_caching: bool,
    input_per_mtok: Decimal, output_per_mtok: Decimal,
    cache_write_per_mtok: Decimal | None, cache_read_per_mtok: Decimal | None,
    deprecated: bool, released_at: str | None,
    compat: dict[str, Any],     # provider-specific overrides
)
```

- Pricing in `Decimal`, USD per 1M tokens.
- `Api` literal: `"anthropic-messages" | "openai-completions" | "openai-responses" | "openai-compatible"`.
- Generator: `scripts/generate_models.py` fetches `models.dev`, writes `generated_models.py` (typed `dict[str, ModelInfo]`).
- Cost: `compute_cost(model, usage) → Decimal`. Override via `set_cost_function(fn)` (single hook, not list).

## 12. Configuration

- Env-var precedence per provider:
  - Anthropic: `ANTHROPIC_API_KEY` → `CLAUDE_API_KEY`.
  - OpenAI: `OPENAI_API_KEY`.
  - OpenAI-compatible: `OPENAI_COMPATIBLE_API_KEY` → `OPENAI_API_KEY`; `OPENAI_COMPATIBLE_BASE_URL` required.
- TOML config at `$XDG_CONFIG_HOME/llm-providers/config.toml` (Windows: `%APPDATA%\llm-providers\config.toml`). Override: `LLM_PROVIDERS_CONFIG`.
  ```toml
  default_model = "claude-sonnet-4-5"
  [providers.anthropic]
  api_key = "..."
  [providers.openai]
  api_key = "..."
  [providers.openai_compatible]
  api_key = "..."
  base_url = "http://localhost:11434/v1"
  ```
- Credential resolution order: explicit kwarg → config file → env vars → `AuthError`.
- Read: stdlib `tomllib`. Write: hand-rolled (schema small) or `tomli-w`.

## 13. Layout

```
llm-providers/
  src/llm_providers/
    __init__.py        # public re-exports
    types.py           # NEW unified schema
    events.py
    errors.py
    registry.py
    models.py
    generated_models.py    # auto-generated
    config.py
    env.py
    cancellation.py
    provider.py
    caching.py             # auto_cache
    assemble.py            # event-stream → AssistantMessage
    _sync.py               # sync wrappers
    providers/
      __init__.py          # built-in registration
      anthropic.py
      openai.py            # both Completions + Responses + Compatible
    utils/
      json_parse.py overflow.py sanitize_unicode.py
      event_stream.py headers.py
  scripts/
    generate_models.py
  tests/
    test_*.py
    contract/{harness.py, helpers.py, fixtures/, ...}
    live/                  # env-gated
```

Deleted vs current: `auth.py`, `tui.py`, `communication.py`, `api_registry.py`, `model_registry.py`. Old `provider.py`, `types.py` rewritten.

## 14. Tests

Three layers, all mandatory:

1. **Unit** (`tests/test_*.py`) — `httpx.MockTransport` against canned fixtures. CI gate ≥ 90% line.
2. **Contract** (`tests/contract/`) — replay HTTP captures, diff against golden event sequence. Defends parity claim.
3. **Live smoke** (`tests/live/`) — env-gated by `LLM_PROVIDERS_LIVE=1`. Manual.

Framework: `unittest.IsolatedAsyncioTestCase` for async.

## 15. pi-ai source map

| Concept | TS | Python |
|---|---|---|
| Public types | `types.ts` | `types.py` + `events.py` + `errors.py` |
| Registry | `api-registry.ts` | `registry.py` |
| Models | `models.ts`, `models.generated.ts` | `models.py`, `generated_models.py` |
| Stream helper | `stream.ts` | `__init__.py` + `assemble.py` |
| Env keys | `env-api-keys.ts` | `env.py` |
| Anthropic | `providers/anthropic.ts` | `providers/anthropic.py` |
| OpenAI Completions | `providers/openai-completions.ts` | `providers/openai.py` (Completions) |
| OpenAI Responses | `providers/openai-responses{,-shared}.ts` | `providers/openai.py` (Responses) |
| Tolerant JSON | `utils/json-parse.ts` | `utils/json_parse.py` |
| Overflow | `utils/overflow.ts` | `utils/overflow.py` |
| Unicode | `utils/sanitize-unicode.ts` | `utils/sanitize_unicode.py` |
| SSE | `utils/event-stream.ts` (per-provider in TS) | `utils/event_stream.py` (shared) |

Don't port: `oauth.ts`, `providers/google*.ts`, `providers/mistral.ts`, `providers/amazon-bedrock.ts`, `providers/azure-openai-responses.ts`, `providers/openai-codex-responses.ts`, `providers/faux.ts`, `providers/github-copilot-headers.ts`, `cli.ts`, `bedrock-provider.ts`, `utils/oauth/`, `utils/typebox-helpers.ts`, `utils/validation.ts`.
