# 15 — `scripts/generate_models.py` + populate `generated_models.py`

## Goal

Build the model-catalogue generator and run it to produce `src/llm_providers/generated_models.py` with all in-scope Anthropic and OpenAI models.

## Refs

- `00-architecture.md` §11
- `pi-mono/packages/ai/scripts/` (TS generator — for shape, don't port verbatim)
- `pi-mono/packages/ai/src/models.generated.ts` (skim only — too large for end-to-end read; we match the format in Python)

## Data source

[models.dev](https://models.dev) `https://models.dev/api.json` — JSON document keyed by provider; each provider lists models with id, name, pricing, context_window, etc.

If models.dev is unreachable, generator must fail loudly (non-zero exit, clear message). No silent stale-data fallback.

## Filter

Only emit models whose provider is in scope:

- `anthropic`
- `openai`

Within those, include only models with `api: ["chat"]` or `api: ["responses"]` (Completions / Responses). Skip embeddings, images, audio.

## Schema mapping

| `models.dev` field | `ModelInfo` field | Notes |
|---|---|---|
| `id` | `id` | |
| `name` | `name` | |
| `provider` | `provider` | |
| `cost.input` | `input_per_mtok` | source already USD/Mtok; verify with a known model |
| `cost.output` | `output_per_mtok` | |
| `cost.cache_read` | `cache_read_per_mtok` | None if absent |
| `cost.cache_write` | `cache_write_per_mtok` | None if absent |
| `limit.context` | `context_window` | |
| `limit.output` | `max_output` | |
| `tool_call` | `tool_use` | |
| `attachment` or `vision` | `vision` | |
| `reasoning` | `reasoning` | |
| `cache` (bool) | `prompt_caching` | |
| `release_date` | `released_at` | |
| `deprecated` (bool) | `deprecated` | |

Provider → api:

- Anthropic models → `api="anthropic-messages"`
- OpenAI models with `api: ["chat"]` (or absent) → `api="openai-completions"`
- OpenAI models with `api: ["responses"]` → `api="openai-responses"`
- OpenAI o-series (`o1*`, `o3*`, `o4*`) → `api="openai-responses"` regardless

## `base_url`

- Anthropic: `"https://api.anthropic.com"`
- OpenAI: `"https://api.openai.com/v1"`

## Output format

`src/llm_providers/generated_models.py`:

```python
"""Auto-generated model catalogue. Do not edit by hand.

Generated from https://models.dev/api.json on YYYY-MM-DD.
Run scripts/generate_models.py to refresh.
"""
from __future__ import annotations
from decimal import Decimal

from llm_providers.models import ModelInfo

MODELS: dict[str, ModelInfo] = {
    "claude-sonnet-4-5": ModelInfo(
        id="claude-sonnet-4-5",
        api="anthropic-messages",
        name="Claude Sonnet 4.5",
        provider="anthropic",
        base_url="https://api.anthropic.com",
        context_window=200000,
        max_output=64000,
        vision=True,
        tool_use=True,
        reasoning=True,
        prompt_caching=True,
        input_per_mtok=Decimal("3.00"),
        output_per_mtok=Decimal("15.00"),
        cache_read_per_mtok=Decimal("0.30"),
        cache_write_per_mtok=Decimal("3.75"),
        deprecated=False,
        released_at="2025-09-29",
    ),
    # ... etc
}
```

`Decimal` strings preserve exact prices.

## Generator script

`scripts/generate_models.py`:

```python
"""Fetch models.dev API, filter to in-scope providers, write generated_models.py.

Usage:
    uv run python scripts/generate_models.py
"""
from __future__ import annotations
import json
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path
from datetime import date

URL = "https://models.dev/api.json"
OUTPUT = Path(__file__).resolve().parent.parent / "src" / "llm_providers" / "generated_models.py"

IN_SCOPE_PROVIDERS = {"anthropic", "openai"}


def fetch() -> dict:
    with urllib.request.urlopen(URL, timeout=30) as r:
        return json.load(r)


def map_api(provider: str, model_id: str, raw_apis: list[str] | None) -> str | None:
    if provider == "anthropic":
        return "anthropic-messages"
    if provider == "openai":
        if model_id.startswith(("o1", "o3", "o4")):
            return "openai-responses"
        if raw_apis and "responses" in raw_apis:
            return "openai-responses"
        if raw_apis and "chat" in raw_apis:
            return "openai-completions"
        return "openai-completions"
    return None


BASE_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
}


def to_decimal(v: object) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def render(models: list[dict]) -> str:
    head = (
        '"""Auto-generated model catalogue. Do not edit by hand.\n\n'
        f'Generated from {URL} on {date.today().isoformat()}.\n'
        'Run scripts/generate_models.py to refresh.\n'
        '"""\n'
        "from __future__ import annotations\n"
        "from decimal import Decimal\n\n"
        "from llm_providers.models import ModelInfo\n\n"
        "MODELS: dict[str, ModelInfo] = {\n"
    )
    body_parts: list[str] = []
    for m in sorted(models, key=lambda m: m["id"]):
        body_parts.append(_render_one(m))
    return head + "\n".join(body_parts) + "\n}\n"


def _render_one(m: dict) -> str:
    def opt_decimal(key: str) -> str:
        v = to_decimal(m.get(key))
        return "None" if v is None else f'Decimal("{v}")'

    def opt_str(key: str) -> str:
        v = m.get(key)
        return "None" if v is None else f'"{v}"'

    return (
        f'    "{m["id"]}": ModelInfo(\n'
        f'        id="{m["id"]}",\n'
        f'        api="{m["api"]}",\n'
        f'        name="{m["name"]}",\n'
        f'        provider="{m["provider"]}",\n'
        f'        base_url="{m["base_url"]}",\n'
        f'        context_window={int(m["context_window"])},\n'
        f'        max_output={int(m["max_output"])},\n'
        f'        vision={m["vision"]},\n'
        f'        tool_use={m["tool_use"]},\n'
        f'        reasoning={m["reasoning"]},\n'
        f'        prompt_caching={m["prompt_caching"]},\n'
        f'        input_per_mtok=Decimal("{m["input_per_mtok"]}"),\n'
        f'        output_per_mtok=Decimal("{m["output_per_mtok"]}"),\n'
        f'        cache_read_per_mtok={opt_decimal("cache_read_per_mtok")},\n'
        f'        cache_write_per_mtok={opt_decimal("cache_write_per_mtok")},\n'
        f'        deprecated={m["deprecated"]},\n'
        f'        released_at={opt_str("released_at")},\n'
        f'    ),'
    )


def main() -> int:
    raw = fetch()
    out: list[dict] = []
    for provider, pdata in raw.items():
        if provider not in IN_SCOPE_PROVIDERS:
            continue
        models = pdata.get("models", {})
        for model_id, mdata in models.items():
            api = map_api(provider, model_id, mdata.get("api"))
            if api is None:
                continue
            cost = mdata.get("cost") or {}
            limit = mdata.get("limit") or {}
            out.append({
                "id": model_id,
                "api": api,
                "name": mdata.get("name", model_id),
                "provider": provider,
                "base_url": BASE_URLS[provider],
                "context_window": limit.get("context", 0),
                "max_output": limit.get("output", 0),
                "vision": bool(mdata.get("attachment") or mdata.get("vision", False)),
                "tool_use": bool(mdata.get("tool_call", True)),
                "reasoning": bool(mdata.get("reasoning", False)),
                "prompt_caching": bool(mdata.get("cache", False)),
                "input_per_mtok": cost.get("input", 0),
                "output_per_mtok": cost.get("output", 0),
                "cache_read_per_mtok": cost.get("cache_read"),
                "cache_write_per_mtok": cost.get("cache_write"),
                "deprecated": bool(mdata.get("deprecated", False)),
                "released_at": mdata.get("release_date"),
            })
    OUTPUT.write_text(render(out), encoding="utf-8")
    print(f"Wrote {len(out)} models to {OUTPUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> **Field-name caveat:** actual `models.dev` JSON field names may differ from this draft (snake vs camel, nesting). Implementer must inspect the live API response, adjust the mapping, and document the resolved field names in the script's module docstring.

## Acceptance

- [ ] `scripts/generate_models.py` runnable: `uv run python scripts/generate_models.py`.
- [ ] Running produces a valid `src/llm_providers/generated_models.py`.
- [ ] Generated file imports cleanly: `from llm_providers.generated_models import MODELS`.
- [ ] Every entry is a valid `ModelInfo`.
- [ ] At least one Anthropic + one OpenAI model present after running against live `models.dev`.
- [ ] CI-time check: `claude-sonnet-4-5`, `claude-opus-4-7` (or successor), `gpt-4o`, `o3` (if released) present.
- [ ] `tests/test_generated_models.py`:
  - dict non-empty
  - every entry's `id` matches its key
  - every entry's `api` is in the allowed `Api` literal set
  - prices are `Decimal`, not `float`
- [ ] `basedpyright` passes on the generated file.

## Notes

- Stdlib `urllib.request` — no extra dep for one HTTP GET.
- Generated file committed to git. Regenerate quarterly or per new-model need; track in commit messages.
- `models.dev` schema break → fix the generator; don't hand-edit `generated_models.py`.
- Generator does not import the rest of `llm_providers` — only `ModelInfo` for the rendered file. Shallow dependency chain.
- Verify cost units against a known model (Claude Sonnet 4.5 input is $3.00/Mtok).
