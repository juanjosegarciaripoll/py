"""Unit tests for generated model registry."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_providers.generated_models import GENERATED_MODEL_DEFINITIONS
from llm_providers.model_registry import ModelDefinition, ModelRegistry
from llm_providers.models import MODEL_REGISTRY

EXPECTED_MINI_MAX_OUTPUT_TOKENS = 16_384


class ModelRegistryTests(unittest.TestCase):
    """Tests for model registry APIs."""

    def test_from_generated_contains_expected_entries(self) -> None:
        registry = ModelRegistry.from_generated()
        assert len(GENERATED_MODEL_DEFINITIONS) > 0
        model = registry.get("openai", "gpt-4o-mini")
        assert model.max_output_tokens == EXPECTED_MINI_MAX_OUTPUT_TOKENS
        assert registry.list_providers() == ["anthropic", "openai"]

    def test_register_and_get(self) -> None:
        registry = ModelRegistry()
        definition = ModelDefinition(
            provider="custom",
            name="custom-model",
            context_window=32_000,
            max_output_tokens=2_048,
        )
        registry.register(definition)
        assert registry.get("custom", "custom-model") == definition

    def test_get_missing_raises(self) -> None:
        registry = ModelRegistry()
        try:
            registry.get("missing", "model")
        except KeyError:
            pass
        else:
            msg = "Expected KeyError for missing model"
            raise AssertionError(msg)

    def test_built_in_registry_is_populated(self) -> None:
        openai_models = MODEL_REGISTRY.list_models("openai")
        assert openai_models

    def test_to_dict_and_empty_provider_listing(self) -> None:
        registry = ModelRegistry(
            [
                ModelDefinition(
                    provider="openai",
                    name="gpt-4o-mini",
                    context_window=128_000,
                    max_output_tokens=16_384,
                )
            ]
        )
        serialized = registry.to_dict()
        assert (
            serialized["openai"]["gpt-4o-mini"]["max_tokens"]
            == EXPECTED_MINI_MAX_OUTPUT_TOKENS
        )
        assert registry.list_models("missing") == []


if __name__ == "__main__":
    unittest.main()

