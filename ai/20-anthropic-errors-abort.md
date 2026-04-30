# 20 — Anthropic provider: error mapping, overflow detection, cancellation

## Goal

Replace placeholder error handling in `AnthropicProvider` (task 16) with full mapping to the unified exception hierarchy, including overflow detection and proper cancellation handshake.

## Refs

- `00-architecture.md` §6, §7
- `03-errors.md`, `06-utils-overflow.md`, `10-cancellation.md`
- Anthropic errors: https://docs.anthropic.com/en/api/errors

## Anthropic error payload

```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "..."
  }
}
```

Common `error.type`:

| `error.type` | HTTP | Map to |
|---|---|---|
| `invalid_request_error` | 400 | `BadRequestError`, OR `ContextOverflowError` if message matches overflow patterns |
| `authentication_error` | 401 | `AuthError` |
| `permission_error` | 403 | `AuthError` |
| `not_found_error` | 404 | `BadRequestError` |
| `rate_limit_error` | 429 | `RateLimitError` (read `retry-after`) |
| `request_too_large` | 413 | `ContextOverflowError` |
| `api_error` | 5xx | `APIError(status_code=...)` |
| `overloaded_error` | 529 | `APIError(status_code=529)` |

In-stream errors (SSE `event: error`) carry the same shape.

## Implementation

```python
def _raise_for_status(
    self, status_code: int, body: bytes, headers: httpx.Headers
) -> None:
    """Translate non-2xx HTTP responses to the unified exception hierarchy."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"raw": body.decode("utf-8", "replace")}
    err = payload.get("error", {})
    err_type = err.get("type", "")
    err_message = err.get("message", f"anthropic returned {status_code}")
    raise _classify_error(status_code, err_type, err_message, payload, headers)


def _classify_error(
    status_code: int,
    err_type: str,
    err_message: str,
    payload: dict,
    headers: httpx.Headers,
) -> LLMProviderError:
    if status_code == 401 or err_type == "authentication_error":
        return AuthError(err_message, provider="anthropic", provider_error=payload)
    if status_code == 403 or err_type == "permission_error":
        return AuthError(err_message, provider="anthropic", provider_error=payload)
    if status_code == 429 or err_type == "rate_limit_error":
        retry_after = _parse_retry_after(headers)
        return RateLimitError(
            err_message,
            provider="anthropic",
            provider_error=payload,
            retry_after=retry_after,
        )
    if status_code == 413 or err_type == "request_too_large":
        return ContextOverflowError(
            err_message, provider="anthropic", provider_error=payload
        )
    if status_code == 400 and is_overflow_message(err_message):
        return ContextOverflowError(
            err_message, provider="anthropic", provider_error=payload
        )
    if status_code == 400 or err_type == "invalid_request_error":
        return BadRequestError(
            err_message, provider="anthropic", provider_error=payload
        )
    if status_code == 404 or err_type == "not_found_error":
        return BadRequestError(
            err_message, provider="anthropic", provider_error=payload
        )
    if status_code >= 500:
        return APIError(
            err_message,
            provider="anthropic",
            provider_error=payload,
            status_code=status_code,
        )
    return APIError(
        err_message,
        provider="anthropic",
        provider_error=payload,
        status_code=status_code,
    )


def _parse_retry_after(headers: httpx.Headers) -> float | None:
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        # Could be HTTP-date; we accept float only for now.
        return None
```

## In-stream error events

If SSE delivers `event: error` mid-flight (after `MessageStart` was already emitted), the §5 contract says: emit `Error(error=...)` then `MessageEnd(stop_reason="error")` then `Done`. **Do not raise** from the generator — caller already received `MessageStart` and would otherwise be left mid-protocol.

```python
elif ev_type == "error":
    err = payload.get("error", {})
    error = _classify_error(
        status_code=200,  # in-stream error, no HTTP status
        err_type=err.get("type", ""),
        err_message=err.get("message", "unknown stream error"),
        payload=payload,
        headers=httpx.Headers(),
    )
    yield Error(error=error)
    yield MessageEnd(
        stop_reason="error",
        usage=_finalize_usage(usage),
        response_id=message_id,
    )
    yield Done()
    return
```

## Cancellation handshake

Re-spec'd from task 16:

```python
async def stream(self, model, context, *, abort=None, **opts):
    async with watch_abort(abort, provider=self.name):
        try:
            async with self._client.stream(...) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    self._raise_for_status(response.status_code, body, response.headers)
                # ... yield events from _iter_events ...
        except asyncio.CancelledError:
            # Either caller cancelled OUR task, OR our watch_abort cancelled
            # us in response to abort.set(). Contract: emit abort tail and
            # re-raise (preserving cancellation semantics).
            yield MessageEnd(
                stop_reason="abort",
                usage=Usage(),  # partial usage acceptable; see note
                response_id="",
            )
            yield Done()
            raise
        except httpx.TransportError as exc:
            raise TransportError(
                f"anthropic transport failure: {exc}",
                provider=self.name,
                cause=exc,
            )
```

> Implementer: `usage` at abort time is partial. Recommend forwarding accumulator state on the abort `MessageEnd`. Tests should verify it reflects what was streamed before abort.

## Acceptance

- [ ] HTTP 401 → `AuthError`
- [ ] HTTP 403 → `AuthError`
- [ ] HTTP 429 with `retry-after: 12` → `RateLimitError(retry_after=12.0)`
- [ ] HTTP 413 → `ContextOverflowError`
- [ ] HTTP 400 with `prompt is too long` → `ContextOverflowError`
- [ ] HTTP 400 (other) → `BadRequestError`
- [ ] HTTP 500 → `APIError(status_code=500)`
- [ ] In-stream `event: error` → `Error` + `MessageEnd("error")` + `Done`, no exception
- [ ] `httpx.TransportError` → `TransportError`
- [ ] Abort during streaming emits `MessageEnd(stop_reason="abort")` + `Done`, re-raises `CancelledError`
- [ ] Abort after `MessageStart` but before any content delivers a well-formed terminating sequence
- [ ] `tests/test_anthropic_errors.py` covers each table row
- [ ] `tests/test_anthropic_abort.py` covers cancellation + abort-event scenarios
- [ ] All prior Anthropic tests still pass
- [ ] `basedpyright` clean
- [ ] After this task, the placeholder `APIError` raising from task 16 is gone

## Notes

- Don't raise inside the async generator after the first event has been yielded. Yield error tail events instead and `return`.
- For in-stream errors, `status_code=200` is overloaded for "what HTTP status would this be". Document in `_classify_error` docstring.
- Some Anthropic 5xx errors come through as `event: error` after a 200 response. Handler covers it.
- `is_overflow_message` (task 06) — don't roll patterns here.
