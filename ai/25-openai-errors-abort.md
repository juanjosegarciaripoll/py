# 25 — OpenAI: error mapping, overflow detection, cancellation

## Goal

Replace placeholder error handling in both OpenAI providers (tasks 21, 22) with full mapping to the unified exception hierarchy, plus the cancellation handshake.

## Refs

- `00-architecture.md` §6, §7
- `03-errors.md`, `06-utils-overflow.md`, `10-cancellation.md`
- `20-anthropic-errors-abort.md` (parallel — same pattern)
- OpenAI errors: https://platform.openai.com/docs/guides/error-codes

## OpenAI error payload (both APIs)

```json
{
  "error": {
    "message": "...",
    "type": "invalid_request_error",
    "code": "rate_limit_exceeded",
    "param": "messages"
  }
}
```

| HTTP | `error.type` | Map to |
|---|---|---|
| 401 | `invalid_request_error` | `AuthError` |
| 403 | (any) | `AuthError` |
| 404 | (any) | `BadRequestError` |
| 400 | `invalid_request_error` with overflow message | `ContextOverflowError` |
| 400 | `invalid_request_error` (other) | `BadRequestError` |
| 422 | (any) | `BadRequestError` |
| 429 | `rate_limit_error` / `tokens_exceeded` | `RateLimitError(retry_after)` |
| 500/502/503 | `server_error` | `APIError` |

For Responses API, in-stream `response.failed` events carry the same shape under `response.error`.

## Implementation pattern

Single `_classify_openai_error` shared by both adapters (place as top-level function in `openai.py` or in a private module):

```python
def _classify_openai_error(
    status_code: int,
    err_type: str,
    err_code: str,
    err_message: str,
    payload: dict,
    headers: httpx.Headers,
    *,
    provider_name: str = "openai",
) -> LLMProviderError:
    if status_code in (401, 403):
        return AuthError(err_message, provider=provider_name, provider_error=payload)
    if status_code == 429:
        retry_after = _parse_retry_after(headers)
        return RateLimitError(
            err_message,
            provider=provider_name,
            provider_error=payload,
            retry_after=retry_after,
        )
    if status_code == 400 and is_overflow_message(err_message):
        return ContextOverflowError(
            err_message, provider=provider_name, provider_error=payload
        )
    if status_code in (400, 404, 422):
        return BadRequestError(err_message, provider=provider_name, provider_error=payload)
    if status_code >= 500:
        return APIError(
            err_message,
            provider=provider_name,
            provider_error=payload,
            status_code=status_code,
        )
    return APIError(
        err_message,
        provider=provider_name,
        provider_error=payload,
        status_code=status_code,
    )
```

Both adapters call from a shared `_raise_for_status(response: httpx.Response)` helper that reads body and dispatches.

## In-stream errors

### Completions

Completions doesn't deliver explicit error events mid-stream — errors arrive as 400-class HTTP before any chunk, or the stream simply stops. Treat any non-`[DONE]` chunk lacking `choices` and containing `"error"` as a stream-error case (rare; happens with proxy timeouts).

### Responses

`response.failed` and `response.incomplete` events deliver the error inline. Replace task 22's placeholder:

```python
elif ev in {"response.failed", "response.incomplete"}:
    resp = payload.get("response", {})
    err = resp.get("error", {}) or resp.get("incomplete_details", {})
    error_obj = _classify_openai_error(
        status_code=200,  # in-stream error, no HTTP status
        err_type=err.get("type", "") if isinstance(err, dict) else "",
        err_code=err.get("code", "") if isinstance(err, dict) else "",
        err_message=err.get("message", err.get("reason", "openai responses failed")) if isinstance(err, dict) else "openai responses failed",
        payload=payload,
        headers=httpx.Headers(),
    )
    yield Error(error=error_obj)
    yield MessageEnd(
        stop_reason="error",
        usage=usage,
        response_id=message_id,
    )
    yield Done()
    return
```

`incomplete` for `reason: "max_output_tokens"` should produce `MessageEnd(stop_reason="max_tokens")` instead of `error`. Handle specifically:

```python
if ev == "response.incomplete":
    reason = payload.get("response", {}).get("incomplete_details", {}).get("reason", "")
    if reason in {"max_output_tokens", "content_filter"}:
        stop = "max_tokens" if reason == "max_output_tokens" else "refusal"
        yield MessageEnd(stop_reason=stop, usage=usage, response_id=message_id)
        yield Done()
        return
    # else: fall through to error path
```

## Cancellation handshake

Same pattern as task 20 (`watch_abort` + try/except `CancelledError` + abort tail emission + re-raise). Both OpenAI adapters get the same wrapping. Don't duplicate — extract a small helper:

```python
async def _yield_abort_tail(usage: Usage, message_id: str) -> AsyncIterator[Event]:
    yield MessageEnd(stop_reason="abort", usage=usage, response_id=message_id)
    yield Done()
```

Both `_iter_events` methods catch `CancelledError`, yield from `_yield_abort_tail`, then re-raise.

## Acceptance

- [ ] `_classify_openai_error` maps each row of the error table correctly.
- [ ] `is_overflow_message` (task 06) detects OpenAI overflow ("exceeds the context window") → `ContextOverflowError`.
- [ ] HTTP 429 with `retry-after: 30` → `RateLimitError(retry_after=30.0)`.
- [ ] HTTP 401 → `AuthError`.
- [ ] HTTP 500 → `APIError(status_code=500)`.
- [ ] `httpx.TransportError` → `TransportError` in both adapters.
- [ ] Responses `response.failed` → `Error` + `MessageEnd("error")` + `Done`, no exception raised.
- [ ] Responses `response.incomplete` with `reason="max_output_tokens"` → `MessageEnd(stop_reason="max_tokens")` + `Done`, no error event.
- [ ] Responses `response.incomplete` with `reason="content_filter"` → `MessageEnd(stop_reason="refusal")` + `Done`, no error event.
- [ ] Cancellation in either adapter emits `MessageEnd(stop_reason="abort")` + `Done` and re-raises.
- [ ] `tests/test_openai_errors.py` and `tests/test_openai_abort.py` cover each case for both adapters.
- [ ] All prior OpenAI tests still pass.
- [ ] `basedpyright` clean.
- [ ] Placeholder `APIError` raises in tasks 21/22 are gone after this task.

## Notes

- Don't raise inside the async generator after `MessageStart` — yield error tail events instead. Same rule as task 20.
- OpenAI `retry-after` may be float-seconds string or HTTP-date. Accept float only; HTTP-date returns None. Document in helper.
- OpenAI-compatible adapter (task 26) inherits the Completions error mapping. No separate logic, but should override `provider_name` so messages say the right thing.
- 400 with `error.message` "Invalid 'tools' length" is a tool-schema violation, not overflow. `is_overflow_message` correctly skips it.
