"""Generated model definitions for built-in providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedModelDefinition:
    """Immutable model definition generated for distribution."""

    provider: str
    name: str
    context_window: int
    max_output_tokens: int


GENERATED_MODEL_DEFINITIONS: tuple[GeneratedModelDefinition, ...] = (
    GeneratedModelDefinition(
        provider="anthropic",
        name="claude-3-5-sonnet-20241022",
        context_window=200_000,
        max_output_tokens=8_192,
    ),
    GeneratedModelDefinition(
        provider="anthropic",
        name="claude-3-5-haiku-20241022",
        context_window=200_000,
        max_output_tokens=8_192,
    ),
    GeneratedModelDefinition(
        provider="openai",
        name="gpt-4o",
        context_window=128_000,
        max_output_tokens=4_096,
    ),
    GeneratedModelDefinition(
        provider="openai",
        name="gpt-4o-mini",
        context_window=128_000,
        max_output_tokens=16_384,
    ),
)
