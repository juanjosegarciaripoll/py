# Feature audit: `pi-mono/packages/ai` (TypeScript) vs `llm-providers` (Python)

Generated 2026-04-30. Audits parity claimed by `PLAN.md` Phase 2.

## Executive summary

- **Phase 2 is marked "Completed" but actual parity is on the order of 10-15%.** The Python port covers the public surface for Anthropic and OpenAI Chat Completions only; the rest of the TS feature set is either absent or stubbed.
- **Two competing data models live in the Python tree.** `llm_providers/types.py` (dataclasses, `Role` enum, `Message.tool_calls`/`tool_call_id`, `Usage(input_tokens/output_tokens)`) is what the providers actually use. `llm_providers/communication.py` is a separate, pydantic-based reimplementation of pi-ai's discriminated-union schema (`UserMessage`/`AssistantMessage`/`ToolResultMessage`, content blocks, `AssistantEvent` union, `Usage(input/output/cache_*/cost)`). The two are not glued together — providers stream `types.AssistantMessageEvent`, while `communication.AssistantMessageEventStream` is a parallel public type that is never produced by any provider.
- **Provider catalog:** TS ships 10 first-class APIs (Anthropic Messages, OpenAI Chat Completions, OpenAI Responses, OpenAI Codex Responses, Azure OpenAI Responses, Mistral Conversations, Google Generative AI, Google Gemini CLI, Google Vertex, Bedrock Converse) plus a `faux` test harness and proxy support for ~25 named vendors via the OpenAI-compat layer. Python ships 3 classes (Anthropic, OpenAI, OpenAI-compatible-as-subclass).
- **OAuth: 0% parity.** TS implements PKCE login flows, callback servers, refresh, and credential storage for 5 OAuth providers (Anthropic, GitHub Copilot, Gemini CLI, Antigravity, OpenAI Codex). Python has only `OAuthToken`/`OAuthTokenStore` data containers — no login, no refresh, no PKCE, no callback server.
- **No registration/dispatch parity.** TS has a global `apiProviderRegistry` keyed by `Api` string with lazy ESM imports. Python's `ApiRegistry` is an unused container — no Python provider self-registers, no `stream(model, context, options)` entry point exists.
- **No `stream()`/`complete()`/`streamSimple()`/`completeSimple()` top-level API.** Users must instantiate a `Provider` subclass directly. There is no model-driven dispatch.
- **No model metadata model.** The TS `Model<TApi>` carries `api`, `provider`, `baseUrl`, `reasoning`, `input`, `cost{input,output,cacheRead,cacheWrite}`, `contextWindow`, `maxTokens`, `headers`, and `compat` overrides. The Python `ModelDefinition` carries 4 fields (`provider`, `name`, `context_window`, `max_output_tokens`). No cost, no API ID, no compat, no capabilities.
- **No `models.generated`.** TS has 15K lines of generated model metadata (~200+ models). Python ships 4 hand-coded entries: `claude-3-5-sonnet-20241022`, `claude-3-5-haiku-20241022`, `gpt-4o`, `gpt-4o-mini`.
- **Reasoning/thinking, prompt caching, tool-result images, citations, vendor headers, GitHub Copilot session affinity, Bedrock SigV4, Vertex ADC, partial-JSON eager streaming: all absent from the Python providers.** They exist as data shapes in `communication.py` but no streaming code path emits them.
- **Cross-provider handoff is implemented in `communication.py` but unreachable in practice** — providers operate on `types.Message`, not `communication.Message`, so the handoff transformer cannot consume or feed real provider runs.
- **No CLI.** TS has `cli.ts` for `login`/`list` of OAuth providers. Python has `tui.py`, which is a different feature: an interactive *configuration wizard* for `ProviderConfig` entries. They serve different purposes.
- **Tests:** TS has ~70 test files covering vendor-specific behavior (Anthropic SSE parsing, eager tool input, OAuth, Bedrock SigV4, Google thinking signatures, OpenAI Codex affinity, etc.). Python has 7 test files covering the public API of the Python implementation; vendor-edge-case coverage is absent.

## Coverage matrix

| Feature                                                  | TS  | Python                          | Notes                                                              |
| -------------------------------------------------------- | --- | ------------------------------- | ------------------------------------------------------------------ |
| Top-level `stream()` / `complete()` dispatch by model    | yes | no                              | Python users instantiate `Provider` classes directly.              |
| `streamSimple()` / `completeSimple()` (unified `reasoning`) | yes | no                           | No simple wrapper; no `ThinkingLevel` plumbing.                    |
| Global `apiProviderRegistry` keyed by `Api`              | yes | unused                          | `ApiRegistry` exists but no provider self-registers.               |
| Lazy provider module loading                             | yes | no                              | Python providers eagerly import at module load.                    |
| `Model<TApi>` metadata (cost, capabilities, compat)      | yes | partial (4 fields, no cost)     | `ModelDefinition` is ~10% of TS `Model`.                           |
| Generated model catalog                                  | ~200| 4 hardcoded                     | `generated_models.py` has 4 entries.                               |
| `calculateCost` from usage + model                       | yes | partial (`Usage.with_cost`)     | Method exists in `communication.py`; no provider produces `communication.Usage`. |
| `supportsXhigh` / `modelsAreEqual`                       | yes | no                              | Not ported.                                                        |
| Discriminated-union message schema                       | yes | yes (in `communication.py`)     | But not used by providers.                                         |
| Content blocks: text / thinking / image / toolCall       | yes | yes (`communication.py`)        | Providers emit a *different* shape (`types.Message.tool_calls`).   |
| `ToolResultMessage` with text+image content              | yes | yes (`communication.py`)        | Anthropic provider's `convert_tool_message` only handles text.     |
| `textSignature` / `thinkingSignature` / `thoughtSignature` | yes | shape only, never populated   | No provider streaming code reads/writes these.                     |
| Redacted thinking handling                               | yes | shape only                      | No streaming path.                                                 |
| `responseId`                                             | yes | shape only                      | No provider emits.                                                 |
| `timestamp` ms on every message                          | yes | yes (default factory)           | Python populates via pydantic default.                             |
| Stream events: `start`/`*_start`/`*_delta`/`*_end`/`done`/`error` | yes | type-defined; not produced | Python providers yield a much simpler `AssistantMessageEvent(delta=Message?, usage=?, finish_reason=?)`. |
| Partial-JSON streaming for tool args                     | yes | yes (helper)                    | `parse_streaming_json` exists; Anthropic/OpenAI providers do call it. |
| `repair_json` for control chars / bad escapes            | yes | yes (`_repair_json_string`)     | Equivalent.                                                        |
| Surrogate sanitization                                   | yes | yes (`sanitize_surrogates`)     | Equivalent.                                                        |
| Context overflow detection (regex+silent)                | yes | yes (subset of patterns)        | Python has 11 patterns vs TS's 19.                                 |
| Tool-call ID normalization (cross-provider)              | yes | yes (`normalize_tool_call_id`)  | Helper exists; not invoked by any streaming code path.             |
| `transformMessages` (handoff: thinking, IDs, orphans)    | yes | yes (`transform_messages_for_handoff`) | Pydantic-only; cannot consume `types.Message`.            |
| Synthetic tool-result insertion for orphans              | yes | yes                             | In `communication.py` only.                                        |
| TypeBox tool-arg validation + JSON-Schema coercion       | yes | no                              | `validate_tool_call` not ported.                                   |
| `StringEnum` helper                                      | yes | no                              | Not ported.                                                        |
| Anthropic Messages provider                              | full (1157 lines) | partial (358) | No prompt caching, no thinking, no eager tool input, no vision, no headers/timeouts/retries, no SDK reuse. |
| OpenAI Chat Completions provider                         | full (1120 lines) | partial (250) | No reasoning_effort, no thinking-as-text, no cache control, no compat layer, no vision tool results. |
| OpenAI Responses API                                     | yes | no                              | Not ported.                                                        |
| OpenAI Codex Responses (ChatGPT OAuth)                   | yes | no                              | Not ported.                                                        |
| Azure OpenAI Responses                                   | yes | no                              | Not ported.                                                        |
| Anthropic via Amazon Bedrock (SigV4)                     | yes | no                              | Not ported.                                                        |
| Google Generative AI / Gemini                            | yes | no                              | Not ported.                                                        |
| Google Gemini CLI                                        | yes | no                              | Not ported.                                                        |
| Google Vertex (ADC, API key, region)                     | yes | no                              | Not ported.                                                        |
| Mistral Conversations                                    | yes | no                              | Not ported.                                                        |
| `faux` test provider                                     | yes | no                              | Not ported.                                                        |
| OpenAI-compatible compat profile (OpenRouter / DeepSeek / Groq / xAI / etc.) | yes (rich `OpenAICompletionsCompat`) | thin subclass | `OpenAICompatibleProvider` is a 4-line subclass that only changes `base_url`. |
| OpenRouter / Vercel Gateway routing options              | yes | no                              | Not ported.                                                        |
| GitHub Copilot dynamic headers + vision detection        | yes | no                              | Not ported.                                                        |
| OAuth: Anthropic / Copilot / Gemini CLI / Antigravity / Codex | yes (5 providers, PKCE, callback server, refresh) | no | Only `OAuthToken` data class + in-memory store. |
| OAuth CLI (`login`/`list`)                               | yes (`cli.ts`) | no                  | Python `tui.py` is a config wizard, not an OAuth tool.             |
| Env-var resolution per provider (multi-key precedence)   | yes (`env-api-keys.ts`) | partial (`<NAME>_API_KEY` only) | TS has provider-specific lookups (e.g. `GEMINI_API_KEY`, `HF_TOKEN`, `ANTHROPIC_OAUTH_TOKEN > ANTHROPIC_API_KEY`). |
| Bedrock IAM/profile/STS detection                        | yes | no                              | Not ported.                                                        |
| Vertex ADC detection                                     | yes | no                              | Not ported.                                                        |
| Custom HTTP headers / timeoutMs / maxRetries / metadata  | yes | no                              | Not honored by Python providers.                                   |
| `cacheRetention` short/long                              | yes | shape only                      | No provider applies it.                                            |
| `sessionId` cache affinity                               | yes | no                              | Not honored.                                                       |
| `onPayload` / `onResponse` callbacks                     | yes | no                              | Not honored.                                                       |
| Abort signal                                             | yes | no                              | `httpx.AsyncClient` calls don't accept a cancel token from caller. |
| Interactive provider config wizard                       | no  | yes (`tui.py`)                  | This is a Python-only feature.                                     |
| `ProvidersConfig` JSON serialization                     | no  | yes                             | Python-only feature.                                               |
| `check_model_access`                                     | no  | yes (per provider)              | Python-only feature; called from the wizard.                       |

## Detailed comparison

### 1. Public API surface

**TypeScript (pi-mono/packages/ai):** `src/index.ts:1-35` exports a model-driven entry point: `getModel(provider, modelId)` returns a typed `Model<TApi>`; `stream(model, context, options)` and `complete(model, context, options)` (`src/stream.ts:25-41`) dispatch through a global `apiProviderRegistry` (`src/api-registry.ts:40-98`) by `model.api`. There is also `streamSimple`/`completeSimple` for a unified `reasoning: ThinkingLevel` knob across providers. The package re-exports TypeBox `Type`/`Static`/`TSchema`, all event types, `getEnvApiKey`/`findEnvKeys`, OAuth provider interface, overflow utilities, JSON-parse utilities, validation utilities, and per-provider option types.

**Python (llm-providers):** `src/llm_providers/__init__.py:17-34` exports: `ApiKeyStore`, `ApiRegistry`, `AssistantMessage`, `AssistantMessageEventStream`, `Context`, `ModelDefinition`, `ModelRegistry`, `OAuthToken`, `OAuthTokenStore`, `Provider`, `ProviderConfig`, `ProvidersConfig`, `ToolResultMessage`, `UserMessage`, `MODEL_REGISTRY`, `get_api_key`. Notably absent: `stream`, `complete`, any concrete provider class, any tool helper, any reasoning enum.

**Gap / divergence:** Python has *no top-level `stream()` function*. To use a provider, callers must `from llm_providers.providers.openai import OpenAIProvider`, instantiate with an api key, and call `provider.stream(model, system_prompt, messages, tools)`. The dispatch layer (registry + lazy module loading + `model.api` switch) is missing. The `ApiRegistry` class is exported but never populated by built-ins — `register_builtins.ts:366-433` has no Python equivalent.

### 2. Provider catalog

**TypeScript:** 10 first-class APIs in `src/providers/`, lazy-loaded via `register-builtins.ts`: `anthropic-messages`, `openai-completions`, `openai-responses`, `openai-codex-responses`, `azure-openai-responses`, `mistral-conversations`, `google-generative-ai`, `google-gemini-cli`, `google-vertex`, `bedrock-converse-stream`. Plus a `faux` test provider (`providers/faux.ts`, 499 lines) and OpenAI-compat auto-detection covering DeepSeek, Groq, Cerebras, xAI, OpenRouter, Vercel AI Gateway, MiniMax, Fireworks, Kimi, OpenCode, Z.AI, HuggingFace, Ollama, vLLM, LM Studio, llama.cpp.

**Python:** 3 classes in `src/llm_providers/providers/`: `AnthropicProvider` (`providers/anthropic.py`, 358 lines), `OpenAIProvider` (`providers/openai.py`, 250 lines), `OpenAICompatibleProvider` (`providers/openai_compatible.py`, 10 lines — a subclass that just sets `base_url`).

**Gap / divergence:** 7 of the 10 TS APIs are not ported (Responses, Codex, Azure, Mistral, all 3 Google variants, Bedrock). The OpenAI-compatible path is a structural subclass without any of the per-vendor compat flags TS uses (`OpenAICompletionsCompat` in `types.ts:277-314` carries 16+ feature toggles that auto-detect from URL). The `faux` provider is missing, which limits the testability of agent-level code. Anthropic via Bedrock and Anthropic via Vertex pathways are also absent.

### 3. Authentication

**TypeScript:** Per-provider env-var resolution with precedence (`src/env-api-keys.ts:58-92`): e.g. `ANTHROPIC_OAUTH_TOKEN > ANTHROPIC_API_KEY`; GitHub Copilot tries `COPILOT_GITHUB_TOKEN > GH_TOKEN > GITHUB_TOKEN`; Vertex resolves `<authenticated>` if ADC + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION`; Bedrock checks `AWS_PROFILE`, `AWS_ACCESS_KEY_ID+SECRET`, `AWS_BEARER_TOKEN_BEDROCK`, IRSA (`AWS_WEB_IDENTITY_TOKEN_FILE`), ECS task roles (`AWS_CONTAINER_CREDENTIALS_*`). OAuth is full-featured (`src/utils/oauth/`): `anthropic.ts:1-402`, `github-copilot.ts:1-396`, `google-gemini-cli.ts:1-597`, `google-antigravity.ts:1-455`, `openai-codex.ts:1-451` — each implements PKCE, callback server, login, refresh, `getApiKey`, `modifyModels` for baseUrl rewrites. `cli.ts` provides interactive `login`/`list`. Anthropic OAuth uses Claude's own `claude.ai/oauth/authorize` and a localhost callback server on port 53692.

**Python:** `auth.py:81-114` derives env-var name with a single rule: `<PROVIDER_UPPER>_API_KEY` (`anthropic` → `ANTHROPIC_API_KEY`, `openai` → `OPENAI_API_KEY`). No multi-key precedence, no OAuth fallback, no Bedrock or Vertex ambient credential detection. `OAuthToken` (`auth.py:18-63`) is a pydantic model with `access_token`, `refresh_token`, `expires_at`, `is_expired()`, `to_dict`/`from_dict`. `OAuthTokenStore` (`auth.py:117-144`) is an in-memory dict. **There is no login flow, no PKCE, no callback server, no refresh logic, no provider-specific OAuth provider class.**

**Gap / divergence:** OAuth is the largest single gap. ~2300 lines of TS OAuth code with no Python counterpart. The env-var helper does not match TS's per-provider resolution table — calling `get_api_key("github-copilot")` will look for `GITHUB_COPILOT_API_KEY`, not the actual GitHub Copilot env vars. Vertex ADC and Bedrock SigV4/IAM credential discovery have no equivalents.

### 4. Message / communication schema

**TypeScript:** Strict discriminated union in `types.ts:159-235`: `UserMessage` (string|content), `AssistantMessage` (text|thinking|toolCall blocks, `api`, `provider`, `model`, `responseId`, `usage`, `stopReason`, `errorMessage`, `timestamp`), `ToolResultMessage` (text|image content, `details`, `isError`, `toolCallId`, `toolName`). `ToolCall` carries optional `thoughtSignature`. `ThinkingContent` carries `thinkingSignature` and `redacted`. `TextContent` carries `textSignature`.

**Python:** TWO PARALLEL SCHEMAS:
- `types.py:12-67` (used by providers): `Role(USER/ASSISTANT/TOOL)`, `TextContent`, `ImageContent` with `image_url: dict`, `Tool`, single `Message` dataclass that has `role`, `content`, `tool_calls: list[ToolCall] | None`, `tool_call_id: str | None`. `ToolCall` is `{id, function: {name, arguments}}` (OpenAI-shaped). `Usage(input_tokens, output_tokens, total_tokens)`. `AssistantMessage = Message` alias.
- `communication.py:27-176` (pydantic; closer parity to TS): `TextContent`, `ThinkingContent`, `ImageContent` (with `data` + `mime_type` like TS), `ToolCallContent` (with `thought_signature`, `partial_json`), `UserMessage`, `AssistantMessage` (with `api`, `provider`, `model`, `response_id`, `usage`, `stop_reason`, `error_message`, `timestamp`), `ToolResultMessage`, `Usage(input, output, cache_read, cache_write, total_tokens, cost: UsageCost)`, `UsageCost`. This is the schema that mirrors `types.ts`.

**Gap / divergence:** The two schemas are not bridged. Providers in `providers/anthropic.py` and `providers/openai.py` import from `types.py` and emit `types.Message` with `role=Role.ASSISTANT` and an OpenAI-shaped `ToolCall.function: dict[str, str]`. They never produce `communication.AssistantMessage` or any of its event types. Result:
- `AssistantMessageEventStream` (the pydantic one in `communication.py:325-362`) is exported as part of the public API but no built-in provider feeds it.
- `transform_messages_for_handoff` cannot operate on what providers produce.
- `is_context_overflow` expects `communication.AssistantMessage` (with `stop_reason`/`error_message` fields) but providers never produce one.
- The Anthropic provider's `convert_tool_message` (`providers/anthropic.py:30-42`) only handles text content; image tool-results — fully supported in TS — are silently dropped.

### 5. Streaming

**TypeScript:** `AssistantMessageEvent` is a 12-variant discriminated union (`types.ts:259-271`): `start` / `text_start` / `text_delta` / `text_end` / `thinking_start` / `thinking_delta` / `thinking_end` / `toolcall_start` / `toolcall_delta` / `toolcall_end` / `done(reason, message)` / `error(reason, error)`. Each event carries the running `partial: AssistantMessage` so consumers can render incremental state without separate state. `AssistantMessageEventStream` (`utils/event-stream.ts:68-87`) is async-iterable and resolves a final `result()` promise on `done`/`error`. Per-block lifecycle events let consumers attribute deltas to a specific content block index. Tool-call deltas stream raw partial JSON chunks; consumers can call `parseStreamingJson` to render in real-time.

**Python:** Two systems again:
- The pydantic event schema in `communication.py:220-322` mirrors TS exactly (12 events, `content_index`, `partial`, `delta`, `done`, `error`). `AssistantMessageEventStream` (`communication.py:325-362`) is async-iterable with a `result()` future. **But no provider emits these events.**
- The actual provider event type (`types.py:62-66`) is `AssistantMessageEvent(delta: Message | None, usage: Usage | None, finish_reason: str | None)`. There are no `start`/`text_start`/`text_end`/`thinking_*`/`toolcall_*` events. The provider yields `AsyncIterator[AssistantMessageEvent]` directly (not wrapped in a stream class).

**Gap / divergence:** The streaming protocol that the public API documents and tests is not the protocol that providers implement. Reasoning/thinking deltas and per-block start/end events are not emitted by Python's Anthropic provider even though Anthropic SSE provides them. The `partial: AssistantMessage` running snapshot is missing entirely. Consumers cannot detect block boundaries, cannot get a final `result()` from a Python stream (unless they hand-build the wrapper).

### 6. Tool calling

**TypeScript:** `Tool { name, description, parameters: TSchema }` (`types.ts:239-243`). `ToolCall { id, name, arguments: Record<string, any>, thoughtSignature? }`. Streaming emits `toolcall_start`/`toolcall_delta(delta: string)`/`toolcall_end(toolCall: ToolCall)`; `parseStreamingJson` (`utils/json-parse.ts:104-124`) is exported for partial rendering. `validateToolCall` / `validateToolArguments` (`utils/validation.ts:277-324`) compile a TypeBox validator (cached), apply `Value.Convert` coercion, and run JSON-schema-based primitive coercion (string→number, "true"→true, etc.) before validation. `transformMessages` (`providers/transform-messages.ts:64-220`) performs cross-provider tool-call ID normalization and inserts synthetic tool-results for orphan tool calls.

**Python:** `ToolDefinition { name, description, parameters: JsonObject }` (`communication.py:178-185`) — uses raw JSON Schema, no TypeBox. `ToolCallContent { type, id, name, arguments, thought_signature, partial_json }` exists in `communication.py:58-68`. But providers use `types.ToolCall { id, function: {name, arguments} }` — OpenAI-shaped, with arguments as a JSON string buffer in `function["arguments"]`. `parse_streaming_json` is implemented and used by the Anthropic provider during accumulation. **No tool-arg validation. No JSON-Schema coercion. No `validate_tool_call` equivalent.** `normalize_tool_call_id` exists in `communication.py:429-439` but is invoked only by `transform_messages_for_handoff`, never by a provider.

**Gap / divergence:**
- No validation pipeline. Pi-ai callers can `validateToolCall(tools, toolCall)` and get back coerced/validated arguments before execution; Python callers cannot.
- ID normalization is dead code from the providers' perspective.
- `thought_signature` (Google) is shape-only; nothing emits it.
- TypeBox vs raw JSON-Schema is a real architectural choice — the Python design-decision is to skip the schema-builder and pass JSON Schema dicts directly. That is fine, but the validation+coercion work that TypeBox enables is not replicated with `jsonschema`/`pydantic`.

### 7. Model registry & generated models

**TypeScript:** `Model<TApi>` (`types.ts:426-451`) with `id`, `name`, `api`, `provider`, `baseUrl`, `reasoning: boolean`, `input: ("text"|"image")[]`, `cost: {input, output, cacheRead, cacheWrite}` ($/M tokens), `contextWindow`, `maxTokens`, `headers`, `compat` (typed by API). `models.generated.ts` is ~15K lines of declarative model metadata covering ~200+ models across all providers. `getModel(provider, modelId)` is fully typed (returns `Model<ModelApi<P,M>>`); `getProviders()`, `getModels(provider)` enumerate. `calculateCost(model, usage)` derives cost from per-million-token rates (`models.ts:39-46`).

**Python:** `ModelDefinition { provider, name, context_window, max_output_tokens }` (`model_registry.py:14-31`). `MODEL_REGISTRY` (`models.py:5`) is loaded from `generated_models.py` which contains 4 entries: 2 Anthropic, 2 OpenAI. No cost, no API/provider routing, no capabilities, no reasoning flag, no compat. There is no generation pipeline — entries are hand-written in `generated_models.py`. `Usage.with_cost(...)` in `communication.py:107-123` exists but takes per-million rates as kwargs from the caller, not from a model.

**Gap / divergence:** ~99% of model metadata is missing. There is no automatic cost computation tied to a model lookup, because models do not carry costs. The TS `Model<TApi>` discriminated-by-API design (which lets `compat` be statically typed per API) has no Python equivalent.

### 8. Stop reasons / interruption / abort

**TypeScript:** `StopReason = "stop" | "length" | "toolUse" | "error" | "aborted"`. Each provider maps vendor-specific stop reasons (e.g. Anthropic `tool_use` → `toolUse`, `end_turn` → `stop`, `max_tokens` → `length`; OpenAI `tool_calls` → `toolUse`). `StreamOptions.signal: AbortSignal` is honored (provider passes to the SDK). On abort, the stream emits `error(reason: "aborted", error: AssistantMessage{stopReason: "aborted"})` and resolves `result()` with that message. There is a dedicated `test/abort.test.ts`.

**Python:** `communication.StopReason = "stop" | "length" | "toolUse" | "error" | "aborted"` (`communication.py:20`). Providers in `types.AssistantMessageEvent.finish_reason` only return loosely-typed strings — the Anthropic provider does map `tool_use → toolUse` (`providers/anthropic.py:305-307`) and OpenAI maps `tool_calls → toolUse` (`providers/openai.py:210-211`), but they do not cover `length`/`error`/`aborted`. **No abort/cancel plumbing.** `httpx.AsyncClient` is used without an externally provided cancel token; callers cannot terminate a stream cleanly.

**Gap / divergence:** Abort signal handling is absent. The full set of normalized stop reasons is also not consistently produced.

### 9. Cross-provider handoff / context serialization

**TypeScript:** `transformMessages(messages, model, normalizeToolCallId?)` in `providers/transform-messages.ts`:
- Replaces images with placeholders for non-vision models.
- Drops or keeps thinking blocks based on same-model identity (`provider+api+id`) and `redacted` flag.
- Preserves `thinkingSignature` for replay against the same model.
- Strips `thoughtSignature` (Google) when crossing providers.
- Normalizes tool-call IDs (callable by provider, e.g. Anthropic enforces `^[a-zA-Z0-9_-]{1,64}$`).
- Skips `error`/`aborted` assistant turns.
- Inserts synthetic `"No result provided"` tool results for orphans.

`Context` is plain JSON (`{systemPrompt, messages, tools}`) so serialization is `JSON.stringify(context)`.

**Python:** `transform_messages_for_handoff` (`communication.py:535-620`) implements all of: thinking-block downgrade, redacted-block dropping, tool-call ID normalization, orphan-result synthesis, error/abort skip. It operates on `communication.UserMessage | AssistantMessage | ToolResultMessage`, **not on `types.Message`**, so it cannot accept what providers produce. Image-placeholder downgrade (TS `downgradeUnsupportedImages`) is **not implemented** — non-vision models receiving image content will fail at the API layer.

`Context` (`communication.py:188-217`) has `to_dict()`, `to_json()`, `from_dict()`, `from_json()`. This is the closest piece to TS parity — it works correctly *if* you build a `communication.Message` graph yourself.

**Gap / divergence:** The handoff path is implemented but unreachable from the provider runtime. Image downgrade is missing. There is no equivalent of `Model<TApi>`-aware handoff (the Python signature takes `target_provider`, `target_api`, `target_model` strings).

### 10. Robustness utilities

**TypeScript:** `repairJson` (`utils/json-parse.ts:32-83`) escapes raw control chars and doubles bad backslashes; `parseStreamingJson` falls back through native parse → repair-and-parse → `partial-json` library → repair-and-partial-parse → `{}`. `sanitizeSurrogates` (`utils/sanitize-unicode.ts:21-25`). `isContextOverflow` (`utils/overflow.ts:112-131`) with 19 patterns + 3 non-overflow exclusions + silent-overflow detection via `usage.input > contextWindow`. `headersToRecord` for `Headers` → plain object.

**Python:**
- `_repair_json_string` (`communication.py:445-488`) — equivalent.
- `_close_partial_json` (`communication.py:491-512`) — closes unbalanced `{`/`[`/`"` in incomplete JSON. Functionally similar to but not identical to TS's reliance on the `partial-json` npm package.
- `parse_streaming_json` (`communication.py:515-532`) — falls through 4 candidates (raw / repaired / closed / repaired+closed). Equivalent.
- `sanitize_surrogates` (`communication.py:386-388`) — equivalent regex.
- `is_context_overflow` (`communication.py:412-426`) — 11 overflow patterns, 3 non-overflow patterns, silent overflow check. **Missing patterns vs TS:** Anthropic `request_too_large` (HTTP 413), Bedrock `input is too long for requested model`, GitHub Copilot `exceeds the limit of N`, llama.cpp, LM Studio, MiniMax, Kimi, Mistral, Z.AI silent, Ollama, Cerebras 400/413 no-body. (Wait — `request_too_long` is present, but the others aren't.) Recheck: Python has 11 patterns, TS has 19; ~8 vendor-specific patterns are not matched.

**Gap / divergence:** Overflow detection is the most-divergent of the robustness utilities; everything else is roughly equivalent. No `headersToRecord` equivalent because Python's `httpx.Headers` is already mapping-like.

### 11. Telemetry

**TypeScript:** `Usage { input, output, cacheRead, cacheWrite, totalTokens, cost: {input, output, cacheRead, cacheWrite, total} }` (`types.ts:189-202`). `calculateCost(model, usage)` derives cost from `model.cost.*`. Each provider populates the full `Usage` (cache read/write are populated by Anthropic and OpenAI Responses; Bedrock fills `cacheRead`/`cacheWrite` from `cacheReadInputTokens`/`cacheCreationInputTokens`). `responseId` populated where the upstream API exposes one (e.g. OpenAI `chatcmpl-…`, Anthropic `msg_…`). `onResponse(response, model)` callback gives access to HTTP status + headers (e.g. for ratelimit headers).

**Python:**
- `communication.Usage` mirrors TS (`communication.py:95-123`) including `cache_read`/`cache_write`/`cost`/`UsageCost`. Has a `with_cost()` method that needs per-million rates passed in (model lookup is the caller's job because models don't carry cost).
- `types.Usage` (`types.py:54-58`) only has `input_tokens`/`output_tokens`/`total_tokens`. **This is what providers populate** (`providers/anthropic.py:197-203`, `providers/openai.py:243-249`). `cache_read`/`cache_write` are zero. `response_id` is not populated. `cost` is not populated. There is no `onResponse` hook.

**Gap / divergence:** Real provider runs do not produce cache token counts, response IDs, or cost. Telemetry parity depends on the unified `communication.Usage` schema, but providers don't write into it.

### 12. Config

**TypeScript:** Per-call config via `StreamOptions` (`types.ts:67-128`): `temperature`, `maxTokens`, `signal`, `apiKey`, `transport`, `cacheRetention`, `sessionId`, `onPayload`, `onResponse`, `headers`, `timeoutMs`, `maxRetries`, `maxRetryDelayMs`, `metadata`. `SimpleStreamOptions` adds `reasoning: ThinkingLevel` and `thinkingBudgets`. There is no top-level "providers config" file format — the library is stateless; configuration is per-call. Models can override `compat`, `headers`, etc. directly.

**Python:** Static config via `ProviderConfig`/`ProvidersConfig` (`config.py`):
- `ProviderConfig { name, provider, model, base_url, api_key_env, oauth_token, options }` — pydantic, frozen, JSON-serializable.
- `ProvidersConfig { providers: tuple, default_provider }`.

Per-call config: providers' `stream(model, system_prompt, messages, tools)` accepts no options at all. `temperature`, `max_tokens`, retries, timeouts, headers, cache retention, session ID — none are configurable per-call.

**Gap / divergence:** Different design: TS is library-first (per-call options), Python is application-first (`ProvidersConfig` is something a CLI saves to disk). The two can coexist, but the Python provider streaming surface lacks a `StreamOptions`-equivalent. `oauth_token` on `ProviderConfig` is a reference to `OAuthToken`, but no provider consumes it.

### 13. CLI / TUI

**TypeScript:** `src/cli.ts` is an OAuth login CLI: `npx @mariozechner/pi-ai login [provider]`, `list`, prompts user via Node `readline`, calls `OAuthProvider.login()` with `onAuth`/`onPrompt`/`onProgress` callbacks, writes `auth.json`. Strictly OAuth credential flow. No model picker, no message wizard.

**Python:** `tui.py` is an interactive provider-config wizard: `select_provider` (numeric menu), `configure_providers_interactive` (full flow building `ProvidersConfig` entries: name, provider, model, base URL, API key env var, optional in-process API key capture, optional accessibility check via `model_access_checker` callback). Builds the static config that `ProvidersConfig.to_json()` then persists. Uses pure stdin `input()` — no network calls, no PKCE, no OAuth.

**Gap / divergence:** They are different programs. The Python wizard is a feature TS lacks. The TS OAuth CLI has no Python equivalent. `provider.check_model_access(model)` (`providers/anthropic.py:335-358`, `providers/openai.py:219-229`) is a Python-only addition consumed by the wizard.

### 14. Tests

**TypeScript** (`test/`, ~70 files):
- Anthropic-specific: SSE parsing, eager tool input streaming, long cache retention E2E, OAuth, Opus 4.7 smoke, thinking disable, tool name normalization.
- OpenAI Completions: cache control format, empty tools, prompt cache, thinking-as-text, tool choice, tool result images.
- OpenAI Responses: cache affinity E2E, copilot provider, foreign tool-call IDs, partial JSON cleanup, reasoning replay, tool result images.
- OpenAI Codex: cache affinity E2E, stream parsing.
- Google: shared `convertTools`, gemini3 unsigned tool call, image tool result routing, thinking disable, thinking signature, tool call missing args, vertex API key resolution, gemini-cli claude thinking header / empty stream / retry delay.
- Bedrock: endpoint resolution, models, thinking payload.
- Mistral: reasoning mode, tool schema.
- Cross-cutting: abort, cache retention, context overflow, cross-provider handoff, image tool result, interleaved thinking, response ID, stream behavior, supports-xhigh, tokens, total tokens, tool-call ID normalization, tool-call without result, transform-messages copilot openai-to-anthropic, unicode surrogate, validation, xhigh, faux provider, lazy module load.

**Python** (`tests/`, 7 files):
- `test_api_registry.py` (121 lines): registers/retrieves providers, env API key resolution.
- `test_auth.py` (117 lines): `OAuthToken` parsing, `is_expired`, `ApiKeyStore` env-name derivation + overrides + missing-key error.
- `test_communication.py` (357 lines): `Context` JSON roundtrip, `Usage.with_cost`, `transform_messages_for_handoff` (same-model preservation, cross-model thinking downgrade, orphan synthesis), `parse_streaming_json` (repair, close), `is_context_overflow` (overflow + non-overflow), `normalize_tool_call_id` (length cap + sha256 hash suffix), `parse_assistant_event` for each event type, `AssistantMessageEventStream` push/result.
- `test_config.py` (91 lines): `ProviderConfig`/`ProvidersConfig` JSON roundtrip.
- `test_model_registry.py` (74 lines): registration/list, `from_generated()`, `to_dict`.
- `test_provider_streaming.py` (581 lines): mocks `httpx.AsyncClient`, asserts `OpenAIProvider`/`AnthropicProvider`/`OpenAICompatibleProvider` produce expected `AssistantMessageEvent` sequences for text + tool calls + usage, asserts request body shape, asserts tool-arg accumulation, asserts `check_model_access` happy path + httpx error.
- `test_tui.py` (298 lines): drives `select_provider`/`configure_providers_interactive` with stub input/output callables.

**Gap / divergence:** Python tests cover the public surface of the Python implementation. They do not test the parity claims (no test exercises `communication.AssistantMessageEventStream` being produced by a provider, because no provider produces it). All vendor edge cases — Anthropic SSE quirks, prompt caching, eager tool input, reasoning replay, foreign tool-call IDs, abort handling, surrogate handling end-to-end through a stream — have no Python equivalents.

## Recommendations

Top porting priorities, ranked by impact on actual feature parity vs the current "Phase 2 complete" claim:

1. **Unify the Python data model.** Pick one of `types.py` or `communication.py` and delete the other. The pragmatic choice is `communication.py` (it is the parity schema). Rewrite `Provider` and the two concrete providers to emit `communication.AssistantEvent` and operate on `communication.UserMessage|AssistantMessage|ToolResultMessage`. This is a prerequisite for *every* other parity claim — handoff, telemetry, replay, overflow detection, normalization — to work end-to-end.
2. **Add the top-level `stream()` / `complete()` / `streamSimple()` / `completeSimple()` dispatch.** Implement `ApiRegistry.register_builtins()` and a lazy import shim. Without this, the "API registry" is decorative and consumers can't write provider-agnostic code (which is the package's stated goal).
3. **Expand the Anthropic provider to feature-complete.** Port: thinking blocks (start/delta/end events + signatures + redacted), prompt caching with `cache_control` and short/long retention, eager tool input streaming, vision image input, custom headers / timeoutMs / maxRetries from options, abort signal handling, response ID, full `Usage` with cache_read/cache_write/cost.
4. **Expand the OpenAI Chat Completions provider similarly:** reasoning_effort, thinking-as-text fallback, tool-result image routing, vision detection, cache-control format flag, the `OpenAICompletionsCompat` profile (auto-detected from baseUrl) — that compat object is what makes a single provider class work for OpenRouter/DeepSeek/Groq/xAI/Cerebras/etc.
5. **Implement OAuth.** Start with Anthropic (PKCE + localhost callback server on port 53692 + refresh) since it is the single highest-value flow. Then GitHub Copilot, Gemini CLI, Codex. Provide a CLI that mirrors `cli.ts`'s `login`/`list`. This is ~2300 lines in TS; it is the largest single missing surface area.
6. **Port OpenAI Responses + Azure OpenAI Responses.** These are required for any consumer using GPT-5/o-series models or Azure tenancy. Reuses much of the OpenAI Chat Completions work but has its own response-id reasoning replay semantics.
7. **Port Google (Generative AI + Vertex + Gemini CLI).** Vertex needs ADC discovery (mirror `env-api-keys.ts`'s `hasVertexAdcCredentials`). Vision and `thoughtSignature` must round-trip across handoffs.
8. **Port Bedrock with SigV4 / IRSA / ECS / profile credential discovery.** Note pi-ai keeps Bedrock as a Node-only lazy module; the Python equivalent should keep `boto3`/`aiobotocore` as an optional dep behind an `extras` feature.
9. **Add the `faux` provider for tests.** Without it, downstream agent code in `py-agent` cannot be tested without hitting real APIs.
10. **Replace `ModelDefinition` with the full `Model` schema and ship a generated catalog.** Add `api`, `base_url`, `cost: ModelCost`, `input: list[Literal["text","image"]]`, `reasoning: bool`, `headers`, `compat` fields, then generate `generated_models.py` from the same source as `pi-mono`'s `models.generated.ts` (or import a JSON dump of it). Wire `Usage.with_cost` to look up the model so callers don't pass per-million rates manually.
