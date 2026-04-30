# 05 — Tolerant partial-JSON parser

## Goal

`src/llm_providers/utils/json_parse.py`:

- `parse_streaming_json(text: str) -> dict[str, Any]` — best-effort parse of a possibly-incomplete JSON fragment.
- `repair_json(text: str) -> str` — repair common malformations in JSON string literals (raw control chars, invalid escapes).

Used at every `ToolCallEnd` and by live tool-call UIs for incremental views.

## Refs

- `00-architecture.md` §8
- `pi-mono/packages/ai/src/utils/json-parse.ts` (read all 125 lines — this is the spec)

## Strategy

`parse_streaming_json`:

1. Try `json.loads(text)`. If it works and result is a dict → return. Otherwise `{}`.
2. On `json.JSONDecodeError`: try `repair_json(text)` then `json.loads`. If repaired version differs from original and parses → return.
3. Still failing: close partial structure (state machine tracking string/escape/brace/bracket); parse the closed form.
4. Anything else → `{}`.

May use `partial-json-parser` PyPI package if approved; declare in `llm-providers/pyproject.toml`. Otherwise hand-roll the closer below.

## Hand-rolled closer

```python
def _close_partial_json(text: str) -> str:
    """Append closing characters to make `text` a parseable JSON value.

    Tracks: in-string state, escape state, brace/bracket stack.
    Returns the smallest extension that produces a parseable value.
    """
    stack: list[str] = []           # entries: '}' or ']'
    in_string = False
    escape = False
    last_complete_index = 0

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
                last_complete_index = i + 1
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
                last_complete_index = i + 1

    suffix = text[:last_complete_index]
    while stack:
        suffix += stack.pop()
    return suffix
```

Wrap with: try parse → if fails, close and parse → if fails, return `{}`.

## `repair_json` port

The TS implementation does two things inside string literals:

1. Escape raw control characters (0x00–0x1F) → `\b`/`\f`/`\n`/`\r`/`\t`/`\uXXXX`.
2. Double-escape backslashes not followed by a valid escape character (`"`, `\`, `/`, `b`, `f`, `n`, `r`, `t`, `u`).

Port faithfully. Verify against TS unit tests if available; otherwise mirror the same cases in Python tests.

## Acceptance

- [ ] `src/llm_providers/utils/__init__.py` empty (or just `"""Utility modules."""`).
- [ ] `src/llm_providers/utils/json_parse.py` exports `parse_streaming_json`, `repair_json`.
- [ ] `tests/test_json_parse.py`:
  - complete JSON object → exact parse
  - object with unterminated string → `{}` (mid-token) or partial dict (string complete) — fix the spec in the docstring and test for it consistently
  - missing closing brace → partial dict with completed keys
  - object with raw `\n` in a string → `repair_json` escapes it; result parses
  - object with invalid escape (`\x`) → `repair_json` doubles the backslash; result parses
  - empty / whitespace-only → `{}`
  - top-level array → `{}` (not a dict)
  - top-level scalar → `{}`
  - nested object needing both stripping and bracket-completion
- [ ] No imports from other `llm_providers` modules — pure utility.
- [ ] No external dependency unless `partial-json-parser` is approved (record the choice in module docstring).
- [ ] `basedpyright` clean.

## Notes

- Catch only `json.JSONDecodeError` (TS catches the JS analogue). Other exceptions propagate.
- Goal: best-effort, never raises. `{}` on irrecoverable input is acceptable.
- Production path: streamed args are normally well-formed by `ToolCallEnd`. The tolerant path is a safety net for provider truncation, not the primary code path.
