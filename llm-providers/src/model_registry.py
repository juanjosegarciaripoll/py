"""Typed model registry for provider model metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .generated_models import GENERATED_MODEL_DEFINITIONS, GeneratedModelDefinition

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class ModelDefinition:
    """Metadata for a model exposed by a provider."""

    provider: str
    name: str
    context_window: int
    max_output_tokens: int

    @classmethod
    def from_generated(cls, generated: GeneratedModelDefinition) -> ModelDefinition:
        """Build model definition from generated source data."""
        return cls(
            provider=generated.provider,
            name=generated.name,
            context_window=generated.context_window,
            max_output_tokens=generated.max_output_tokens,
        )


class ModelRegistry:
    """Registry for provider model definitions."""

    def __init__(self, definitions: Iterable[ModelDefinition] | None = None) -> None:
        self._definitions: dict[str, dict[str, ModelDefinition]] = {}
        for definition in definitions or ():
            self.register(definition)

    def register(self, definition: ModelDefinition) -> None:
        """Register a model definition."""
        provider_models = self._definitions.setdefault(definition.provider, {})
        provider_models[definition.name] = definition

    def get(self, provider: str, name: str) -> ModelDefinition:
        """Return model definition for provider and model name."""
        try:
            return self._definitions[provider][name]
        except KeyError as exc:
            msg = f"Unknown model '{name}' for provider '{provider}'"
            raise KeyError(msg) from exc

    def list_providers(self) -> list[str]:
        """Return provider names with registered models."""
        return sorted(self._definitions.keys())

    def list_models(self, provider: str) -> list[ModelDefinition]:
        """Return sorted model definitions for provider."""
        models_for_provider = self._definitions.get(provider, {})
        return sorted(models_for_provider.values(), key=lambda model: model.name)

    def to_dict(self) -> dict[str, dict[str, dict[str, int]]]:
        """Serialize model registry to JSON-compatible mapping."""
        serialized: dict[str, dict[str, dict[str, int]]] = {}
        for provider in self.list_providers():
            serialized[provider] = {}
            for model in self.list_models(provider):
                serialized[provider][model.name] = {
                    "context_window": model.context_window,
                    "max_tokens": model.max_output_tokens,
                }
        return serialized

    @classmethod
    def from_generated(cls) -> ModelRegistry:
        """Create a registry from generated model definitions."""
        definitions = [
            ModelDefinition.from_generated(generated)
            for generated in GENERATED_MODEL_DEFINITIONS
        ]
        return cls(definitions)
