# 26 — OpenAI-compatible adapter

## Goal

Add `OpenAICompatibleProvider` to `src/llm_providers/providers/openai.py`. Subclasses `OpenAIChatCompletionsProvider` (tasks 21+23+25). Targets local servers (Ollama, vLLM, llama.cpp) and third-party gateways (OpenRouter, Together, Groq, …) that expose an OpenAI-compatible Chat Completions endpoint.

OpenAI **Responses** API isn't widely implemented by third parties; this adapter wraps Completions only.

## Refs

- `00-architecture.md` §1 (scope), §12 (env vars)
- `21-openai-completions-basics.md` (parent class)
- `23-openai-tools.md`, `25-openai-errors-abort.md` (inherited capabilities)
- `pi-mono/packages/ai/src/types.ts:277-314` (`OpenAICompletionsCompat` taxonomy — partial mirror)
- `pi-mono/packages/ai/src/providers/openai-completions.ts:1020-1093` (`detectCompat` — URL-based auto-detection)

## Differences from `OpenAIChatCompletionsProvider`

Soften some OpenAI-specific behavior:

1. **Authentication is optional.** Local servers (Ollama, llama.cpp) accept any key including none. Don't raise `BadRequestError` if `api_key` is missing — pass through with no Authorization header.
2. **`stream_options.include_usage` may be unsupported.** Conditional on `model.compat["supports_usage_in_streaming"]` (default True; set False in `compat` for known offenders).
3. **`max_tokens` field name varies.** Already handled by `_max_tokens_field` (task 21) reading `model.compat["max_tokens_field"]`.
4. **`developer` role unsupported.** Already a no-op for Completions adapter.
5. **`strict` field on tools** — some servers reject it. Conditional on `model.compat["supports_strict_mode"]` (default False — we don't emit it anyway in task 23).
6. **Cache-control format for Anthropic-compat servers** — out of scope; `cache_control_format` ignored.

## Implementation

```python
class OpenAICompatibleProvider(OpenAIChatCompletionsProvider):
    name: ClassVar[str] = "openai_compatible"
    api: ClassVar[str] = "openai-compatible"
    default_base_url: ClassVar[str] = ""  # must be supplied; no sensible default

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 600.0,
    ) -> None:
        if not base_url:
            raise BadRequestError(
                "openai_compatible provider requires base_url",
                provider=self.name,
            )
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            client=client,
            timeout=timeout,
        )

    def _build_headers(self) -> dict[str, str]:
        # api_key optional for compat servers
        if self.api_key:
            return json_headers(api_key=self.api_key)
        return json_headers()  # no Authorization header

    def _build_request(
        self,
        model: ModelInfo,
        context: Context,
        max_tokens: int | None,
        temperature: float | None,
    ) -> dict[str, object]:
        body = super()._build_request(model, context, max_tokens, temperature)
        # Drop stream_options.include_usage if the server doesn't support it
        if model.compat and not model.compat.get("supports_usage_in_streaming", True):
            body.pop("stream_options", None)
        return body

    async def check_model_access(self, model: ModelInfo) -> bool:
        # Compat servers may not require an API key. True if base_url is set.
        return bool(self.base_url)
```

## Registry hook

`providers/__init__.py` registers only when configured. Compat provider has no useful default:

- Env vars `OPENAI_COMPATIBLE_BASE_URL` (and optional `OPENAI_COMPATIBLE_API_KEY`) → instantiate.
- Otherwise skip — caller instantiates manually.

```python
# in providers/__init__.py
def _register_openai_compatible():
    base_url = env.get_base_url("openai_compatible")
    if not base_url:
        return
    api_key = env.get_api_key("openai_compatible")
    provider = OpenAICompatibleProvider(api_key=api_key, base_url=base_url)
    register_provider("openai-compatible", provider)
```

> **Conflict resolved:** `OpenAIChatCompletionsProvider` and `OpenAICompatibleProvider` cannot share `api="openai-completions"` — registering both would overwrite. Solution: compat declares `api="openai-compatible"`. Registry resolves via explicit `api=` kwarg or via models in `generated_models.py` declared with `api="openai-compatible"`.

This means:

- Task 04's `Api` literal includes `"openai-compatible"` (already specified there).
- Compat provider's `api` ClassVar is `"openai-compatible"`.
- Compat-served models declared with `api="openai-compatible"` (in `generated_models.py` or via prefix-fallback synthesis with explicit `api=`).

## Acceptance

- [ ] `OpenAICompatibleProvider` exported from `providers/openai.py`.
- [ ] Constructor requires `base_url` (raises `BadRequestError` if missing).
- [ ] `api_key=None` permitted; resulting requests have no `Authorization` header.
- [ ] `model.compat["supports_usage_in_streaming"] = False` removes `stream_options` from request body.
- [ ] Inherits all task 21/23/25 behavior unchanged.
- [ ] `providers/__init__.py` registers compat provider when `OPENAI_COMPATIBLE_BASE_URL` set.
- [ ] `tests/test_openai_compatible.py`:
  - missing base_url → `BadRequestError`
  - request without api_key omits Authorization header
  - `supports_usage_in_streaming=False` drops `stream_options` field
  - smoke streaming through inherited `_iter_events` (mocked)
  - registration only when env var set
- [ ] `basedpyright` clean.

## Notes

- Thin subclass intentionally. Don't special-case OpenRouter / Groq / Ollama — server-specific quirks belong in the user's `compat` dict on the `ModelInfo`.
- "OpenAI-compatible" is a misnomer in practice. Each server is OpenAI-*-ish*. Best-effort + per-server `compat` overrides is a doc concern (`README`), not a code concern.
- `provider="openai_compatible"` is the env-var key (task 11). `api="openai-compatible"` is the registry key. Different identifiers — env-var lookup uses `_API_KEY_ENV_VARS["openai_compatible"]`; api literal is the dispatch key. Keep straight.
