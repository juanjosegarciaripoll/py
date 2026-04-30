# 07 — Surrogate / invalid-unicode scrub

## Goal

`src/llm_providers/utils/sanitize_unicode.py`: `sanitize_surrogates(text: str) -> str` strips lone (unpaired) Unicode surrogates before JSON serialization. Anthropic + OpenAI both 400 on these, often after an LLM emits a partial multi-byte char that the consumer concatenates into a follow-up request.

## Refs

- `pi-mono/packages/ai/src/utils/sanitize-unicode.ts` (25 lines)

## Module

In Python `str`, characters in U+D800–U+DFFF appear as individual code points; they are always "unpaired" by definition (properly paired surrogates would have already been combined into a supplementary-plane code point). Strip them all.

```python
from __future__ import annotations
import re


_SURROGATES = re.compile(r"[\ud800-\udfff]")


def sanitize_surrogates(text: str) -> str:
    """Remove Unicode surrogate code points.

    Properly paired surrogates do not exist as separate code points in
    Python `str` — they would already have been combined into the
    supplementary-plane code point. So any code point in U+D800..U+DFFF
    is by definition unpaired and should be stripped before JSON
    serialization.

    Valid emoji and other supra-BMP characters are unaffected.
    """
    return _SURROGATES.sub("", text)
```

## Acceptance

- [ ] `sanitize_surrogates` exported.
- [ ] `tests/test_sanitize_unicode.py`:
  - emoji preserved (`"\U0001F648"` round-trips)
  - lone high surrogate `"\ud83d"` removed
  - lone low surrogate `"\udc00"` removed
  - empty string + ASCII unchanged
  - `json.dumps(sanitize_surrogates(s))` doesn't raise on any test input
- [ ] No imports from other `llm_providers` modules.
- [ ] `basedpyright` clean.

## Notes

- Adapters call this on every outbound text content part (defense in depth).
- Don't extend to "scrub other invalid unicode" without a documented provider failure. Control chars in JSON strings → `repair_json` (task 05).
