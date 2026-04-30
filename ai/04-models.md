# 04 — `ModelInfo` + cost helper

## Goal

`src/llm_providers/models.py`: `ModelInfo` dataclass + `compute_cost_default` + `CostFunction` alias. The catalogue itself is task 15.

## Refs

- `00-architecture.md` §11
- `pi-mono/packages/ai/src/types.ts:426-451` (TS `Model<TApi>` shape)
- `pi-mono/packages/ai/src/models.ts` (TS schema declarations)

## Module

```python
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Literal

from llm_providers.types import Usage


Api = Literal[
    "anthropic-messages",
    "openai-completions",
    "openai-responses",
    "openai-compatible",
]
"""APIs the rebuild supports. Adding more requires a new provider adapter."""


ProviderId = str
"""Free-form provider identifier (anthropic, openai, deepseek, openrouter, ...)."""


@dataclass(slots=True, frozen=True)
class ModelInfo:
    id: str
    api: Api
    name: str
    provider: ProviderId
    base_url: str
    context_window: int
    max_output: int
    # capabilities
    vision: bool = False
    tool_use: bool = True
    reasoning: bool = False
    prompt_caching: bool = False
    # pricing — USD per million tokens
    input_per_mtok: Decimal = Decimal(0)
    output_per_mtok: Decimal = Decimal(0)
    cache_write_per_mtok: Decimal | None = None
    cache_read_per_mtok: Decimal | None = None
    # lifecycle
    deprecated: bool = False
    released_at: str | None = None       # ISO-8601 date, e.g. "2024-10-22"
    # provider-specific compat overrides (free-form; consumed by adapter)
    compat: dict[str, Any] = field(default_factory=dict)


def compute_cost_default(model: ModelInfo, usage: Usage) -> Decimal:
    """Default cost calculator. Returns USD as Decimal."""
    mtok = Decimal(1_000_000)
    cost = (
        Decimal(usage.input_tokens) * model.input_per_mtok / mtok
        + Decimal(usage.output_tokens) * model.output_per_mtok / mtok
    )
    if model.cache_read_per_mtok is not None:
        cost += Decimal(usage.cache_read_tokens) * model.cache_read_per_mtok / mtok
    if model.cache_write_per_mtok is not None:
        cost += Decimal(usage.cache_write_tokens) * model.cache_write_per_mtok / mtok
    return cost


CostFunction = Callable[[ModelInfo, Usage], Decimal]
"""Callable signature for replaceable cost calculators."""
```

The active hook lives on the registry (task 13). This module exposes the default + alias only.

```python
# in registry.py (task 13)
from llm_providers.models import compute_cost_default, CostFunction

_cost_fn: CostFunction = compute_cost_default

def set_cost_function(fn: CostFunction) -> None: ...
def compute_cost(model: ModelInfo, usage: Usage) -> Decimal: ...
```

## Acceptance

- [ ] Exports: `Api`, `ProviderId`, `ModelInfo`, `compute_cost_default`, `CostFunction`.
- [ ] `tests/test_models.py`:
  - construction with required fields only
  - `compute_cost_default` over a synthetic `Usage` with all four token classes returns expected `Decimal` (exact-digit equality)
  - `cache_write_per_mtok=None` doesn't raise, contributes nothing
  - `compute_cost_default` returns `Decimal(0)` for zero-usage
- [ ] `basedpyright` clean. No `Any` in `compute_cost_default`. No `float` in cost path.

## Notes

- `Decimal` not `float` for pricing. Cents matter.
- `Api` is intentionally narrow. Widening forces a corresponding adapter change.
- `compat: dict[str, Any]` is the escape hatch for OpenAI-compat / Anthropic-compat flags (`OpenAICompletionsCompat` / `AnthropicMessagesCompat` from `types.ts:277-336`). Adapters pull keys they recognize. Add a `TypedDict` per provider only if it grows large.
- No `__post_init__`. Generator script enforces shape.
