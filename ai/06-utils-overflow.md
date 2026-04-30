# 06 — Context-overflow detection

## Goal

`src/llm_providers/utils/overflow.py`: classify error messages (or finished `AssistantMessage`s) as context-window overflow. Used by adapters to decide `ContextOverflowError` vs `BadRequestError`, and by `py-agent`'s compaction.

## Refs

- `00-architecture.md` §6
- `pi-mono/packages/ai/src/utils/overflow.ts` (full file — port both functions and pattern list)

## Module

```python
from __future__ import annotations
import re

from llm_providers.types import AssistantMessage, Usage


_OVERFLOW_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"prompt is too long",                                   # Anthropic
        r"request_too_large",                                    # Anthropic 413
        r"input is too long for requested model",                # Bedrock
        r"exceeds the context window",                           # OpenAI
        r"input token count.*exceeds the maximum",               # Google
        r"maximum prompt length is \d+",                         # xAI
        r"reduce the length of the messages",                    # Groq
        r"maximum context length is \d+ tokens",                 # OpenRouter
        r"exceeds the limit of \d+",                             # Copilot
        r"exceeds the available context size",                   # llama.cpp
        r"greater than the context length",                      # LM Studio
        r"context window exceeds limit",                         # MiniMax
        r"exceeded model token limit",                           # Kimi
        r"too large for model with \d+ maximum context length",  # Mistral
        r"model_context_window_exceeded",                        # z.ai
        r"prompt too long; exceeded (?:max )?context length",    # Ollama
        r"context[_ ]length[_ ]exceeded",                        # generic
        r"too many tokens",                                      # generic
        r"token limit exceeded",                                 # generic
        r"^4(?:00|13)\s*(?:status code)?\s*\(no body\)",         # Cerebras
    )
)


_NON_OVERFLOW_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^(Throttling error|Service unavailable):",   # Bedrock
        r"rate limit",                                  # generic
        r"too many requests",                           # generic 429
    )
)


def is_overflow_message(error_message: str) -> bool:
    """True if the error string indicates context-window overflow.

    Excludes throttling / rate-limit messages even if they happen to also
    match an overflow pattern (Bedrock formats some of those misleadingly).
    """
    if not error_message:
        return False
    if any(p.search(error_message) for p in _NON_OVERFLOW_PATTERNS):
        return False
    return any(p.search(error_message) for p in _OVERFLOW_PATTERNS)


def is_context_overflow(message: AssistantMessage, context_window: int | None = None) -> bool:
    """True if `message` represents a context-overflow outcome.

    Two cases:
      1. error-based: stop_reason == "error" and error_message matches a known pattern.
      2. silent overflow (z.ai-style): stop_reason == "end_turn" but
         input_tokens + cache_read_tokens > context_window.
    """
    if message.stop_reason == "error" and message.error_message:
        if is_overflow_message(message.error_message):
            return True
    if context_window and message.stop_reason == "end_turn":
        usage = message.usage or Usage()
        if usage.input_tokens + usage.cache_read_tokens > context_window:
            return True
    return False


def overflow_patterns() -> tuple[re.Pattern[str], ...]:
    """Read-only view of the patterns. For tests only."""
    return _OVERFLOW_PATTERNS
```

## Acceptance

- [ ] All three functions exported.
- [ ] All 20 patterns from `pi-ai/utils/overflow.ts` ported. Verify count matches.
- [ ] `tests/test_overflow.py`:
  - one positive case per pattern using example messages from the TS docstring
  - all four `_NON_OVERFLOW_PATTERNS` exclusions (e.g. `Throttling error: too many tokens` → `False`)
  - silent overflow: `AssistantMessage(stop_reason="end_turn", usage=Usage(input_tokens=300_000))` with `context_window=200_000` → `True`
  - silent overflow without `context_window` → `False` even with huge usage
  - empty error message → `False`
- [ ] `basedpyright` clean.

## Notes

- Adapters call `is_overflow_message(text)` *before* deciding between `ContextOverflowError` vs `BadRequestError`.
- `is_context_overflow(message, ...)` for post-hoc inspection (compaction).
- New provider format unsupported → add to pattern list, not provider-specific code.
