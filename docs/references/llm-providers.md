# llm-providers Reference

## Core modules

- `llm_providers.provider`
- `llm_providers.types`
- `llm_providers.communication`
- `llm_providers.api_registry`
- `llm_providers.config`
- `llm_providers.auth`
- `llm_providers.model_registry`
- `llm_providers.models`
- `llm_providers.providers.openai`
- `llm_providers.providers.anthropic`
- `llm_providers.providers.openai_compatible`

## Public API exports

From `llm_providers.__init__`:

- `Provider`
- `ApiRegistry`, `get_api_key`
- `ApiKeyStore`, `OAuthToken`, `OAuthTokenStore`
- `ProviderConfig`, `ProvidersConfig`
- `ModelDefinition`, `ModelRegistry`, `MODEL_REGISTRY`
- `UserMessage`, `AssistantMessage`, `ToolResultMessage`, `Context`
- `AssistantMessageEventStream`

## Provider contract

`Provider` requires:

- `stream(model, system_prompt, messages, tools)`
- `check_model_access(model)`
- `convert_tool_message(message)`
- `convert_non_tool_message(message)`

## Streaming event model (`llm_providers.types`)

`AssistantMessageEvent` contains optional:

- `delta`: incremental assistant `Message`
- `usage`: token counts
- `finish_reason`: end reason (`stop`, `length`, `toolUse`, ...)

## Package docs replaced by this page

This page subsumes package-level README material in `llm-providers/README.md`.
