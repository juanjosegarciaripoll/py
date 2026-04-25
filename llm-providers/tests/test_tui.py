"""Unit tests for optional provider selection TUI."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model_registry import ModelDefinition, ModelRegistry
from src.tui import configure_providers_interactive, select_provider

EXPECTED_TWO_PROVIDERS = 2


class SelectProviderTests(unittest.TestCase):
    """Tests for provider selection prompt logic."""

    def test_single_provider_returns_without_prompt(self) -> None:
        selected = select_provider(["openai"])
        assert selected == "openai"

    def test_invalid_then_valid_input(self) -> None:
        inputs = iter(["abc", "4", "2"])
        printed: list[str] = []

        def _input(_: str) -> str:
            return next(inputs)

        def _print(message: str) -> None:
            printed.append(message)

        selected = select_provider(
            ["openai", "anthropic", "openai-compatible"],
            input_fn=_input,
            output_fn=_print,
        )
        assert selected == "anthropic"
        assert any("Invalid choice" in message for message in printed)
        assert any("Choice out of range" in message for message in printed)

    def test_empty_provider_list_raises(self) -> None:
        try:
            select_provider([])
        except ValueError:
            pass
        else:
            msg = "Expected ValueError when provider list is empty"
            raise AssertionError(msg)


class ConfigureProvidersInteractiveTests(unittest.TestCase):
    """Tests for interactive provider configuration wizard."""

    def test_single_provider_collects_required_fields(self) -> None:
        inputs = iter(
            [
                "local-ollama",
                "2",
                "http://localhost:11434/v1/",
                "",
                "n",
                "n",
                "n",
            ]
        )
        printed: list[str] = []
        registry = ModelRegistry(
            [
                ModelDefinition(
                    provider="openai-compatible",
                    name="gpt-local",
                    context_window=32_000,
                    max_output_tokens=8_000,
                ),
                ModelDefinition(
                    provider="openai-compatible",
                    name="llama-3.1",
                    context_window=128_000,
                    max_output_tokens=8_000,
                ),
            ]
        )

        def _input(_: str) -> str:
            return next(inputs)

        def _print(message: str) -> None:
            printed.append(message)

        config = configure_providers_interactive(
            ["openai-compatible"],
            model_registry=registry,
            input_fn=_input,
            output_fn=_print,
        )
        assert len(config.providers) == 1
        first = config.providers[0]
        assert first.name == "local-ollama"
        assert first.provider == "openai-compatible"
        assert first.model == "llama-3.1"
        assert first.base_url == "http://localhost:11434/v1"
        assert first.api_key_env == "OPENAI_COMPATIBLE_API_KEY"
        assert config.default_provider == "local-ollama"

    def test_accessibility_check_failure_can_abort(self) -> None:
        inputs = iter(
            [
                "work-openai",
                "1",
                "",
                "",
                "n",
                "y",
                "n",
            ]
        )
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

        def _input(_: str) -> str:
            return next(inputs)

        try:
            configure_providers_interactive(
                ["openai"],
                model_registry=registry,
                input_fn=_input,
                output_fn=lambda _: None,
                model_access_checker=lambda _: (False, "not reachable"),
            )
        except ValueError as exc:
            message = str(exc)
        else:
            msg = "Expected ValueError when user aborts after failed model check"
            raise AssertionError(msg)
        assert "aborted" in message

    def test_multiple_entries_choose_default(self) -> None:
        inputs = iter(
            [
                "first",
                "1",
                "",
                "",
                "n",
                "n",
                "y",
                "second",
                "2",
                "",
                "",
                "n",
                "n",
                "n",
                "2",
            ]
        )
        registry = ModelRegistry(
            [
                ModelDefinition(
                    provider="openai",
                    name="gpt-4o-mini",
                    context_window=128_000,
                    max_output_tokens=16_384,
                ),
                ModelDefinition(
                    provider="anthropic",
                    name="claude-3-5-haiku-20241022",
                    context_window=200_000,
                    max_output_tokens=8_192,
                ),
            ]
        )

        def _input(_: str) -> str:
            return next(inputs)

        config = configure_providers_interactive(
            ["openai", "anthropic"],
            model_registry=registry,
            input_fn=_input,
            output_fn=lambda _: None,
        )
        assert len(config.providers) == EXPECTED_TWO_PROVIDERS
        assert config.default_provider == "second"

    def test_wizard_handles_duplicate_names_custom_model_env_and_success_check(
        self,
    ) -> None:
        previous_openai_env = os.environ.get("OPENAI_API_KEY")
        inputs = iter(
            [
                "dup",
                "1",
                "",
                "",
                "bad env",
                "y",
                "secret-value",
                "y",
                "y",
                "dup",
                "unique",
                "2",
                "",
                "custom-model",
                "",
                "http://localhost:8000/v1/",
                "",
                "n",
                "y",
                "n",
                "2",
            ]
        )
        printed: list[str] = []
        registry = ModelRegistry(
            [
                ModelDefinition(
                    provider="openai",
                    name="gpt-4o-mini",
                    context_window=128_000,
                    max_output_tokens=16_384,
                ),
            ]
        )

        def _input(_: str) -> str:
            return next(inputs)

        def _print(message: str) -> None:
            printed.append(message)

        configured_openai_env: str | None = None
        try:
            config = configure_providers_interactive(
                ["openai", "openai-compatible"],
                model_registry=registry,
                input_fn=_input,
                output_fn=_print,
                model_access_checker=lambda provider_config: (
                    True,
                    f"checked {provider_config.name}",
                ),
            )
            configured_openai_env = os.environ.get("OPENAI_API_KEY")
        finally:
            if previous_openai_env is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = previous_openai_env

        assert len(config.providers) == EXPECTED_TWO_PROVIDERS
        assert config.providers[0].name == "dup"
        assert config.providers[0].api_key_env == "OPENAI_API_KEY"
        assert config.providers[1].name == "unique"
        assert config.providers[1].provider == "openai-compatible"
        assert config.providers[1].model == "custom-model"
        assert config.providers[1].base_url == "http://localhost:8000/v1"
        assert config.default_provider == "unique"
        assert any("already exists" in message for message in printed)
        assert any(
            "Base URL is required for openai-compatible providers." in message
            for message in printed
        )
        assert any(
            "Invalid env var name. Using default." in message for message in printed
        )
        assert any("Value cannot be empty." in message for message in printed)
        assert any("Model access check passed." in message for message in printed)
        assert any("checked dup" in message for message in printed)
        assert any("checked unique" in message for message in printed)
        assert configured_openai_env == "secret-value"

    def test_empty_provider_list_raises_in_configure(self) -> None:
        try:
            configure_providers_interactive([])
        except ValueError:
            pass
        else:
            msg = "Expected ValueError for empty provider list in wizard"
            raise AssertionError(msg)


if __name__ == "__main__":
    unittest.main()
