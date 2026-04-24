"""Unit tests for API registry behavior."""

import os
import sys
import typing as t
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api_registry import ApiRegistry, get_api_key
from src.provider import Provider
from src.types import AssistantMessageEvent, Message, Tool


class DummyProvider(Provider):
    """Minimal provider used for registry tests."""

    def stream(
        self,
        model: str,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> t.AsyncIterator[AssistantMessageEvent]:
        del model, system_prompt, messages, tools
        return _empty_stream()


async def _empty_stream() -> t.AsyncIterator[AssistantMessageEvent]:
    if False:
        yield AssistantMessageEvent()


class ApiRegistryTests(unittest.TestCase):
    """Tests for provider registration and API key resolution."""

    def test_register_and_get_provider(self) -> None:
        registry = ApiRegistry()
        provider = DummyProvider()
        registry.register("dummy", provider)
        assert registry.get_provider("dummy") is provider

    def test_list_providers(self) -> None:
        registry = ApiRegistry()
        registry.register("a", DummyProvider())
        registry.register("b", DummyProvider())
        assert registry.list_providers() == ["a", "b"]

    def test_get_api_key_success(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret"}, clear=False):
            assert get_api_key("openai") == "secret"

    def test_get_api_key_missing_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            try:
                get_api_key("anthropic")
            except ValueError:
                pass
            else:
                msg = "Expected ValueError when API key is missing"
                raise AssertionError(msg)


if __name__ == "__main__":
    unittest.main()
