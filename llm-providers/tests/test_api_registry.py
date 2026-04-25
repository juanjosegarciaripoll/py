"""Unit tests for API registry behavior."""

import sys
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api_registry import ApiRegistry, get_api_key
from src.auth import ApiKeyStore
from src.provider import Provider
from src.types import AssistantMessageEvent, Message, Role, TextContent, Tool


class DummyProvider(Provider):
    """Minimal provider used for registry tests."""

    def convert_tool_message(self, message: Message) -> dict[str, object] | None:
        del message
        return None

    def convert_non_tool_message(
        self,
        message: Message,
    ) -> dict[str, object] | None:
        del message
        return None

    def stream(
        self,
        model: str,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool],
    ) -> AsyncIterator[AssistantMessageEvent]:
        del model, system_prompt, messages, tools
        return _empty_stream()

    def check_model_access(self, model: str) -> tuple[bool, str | None]:
        del model
        return True, None


async def _empty_stream() -> AsyncIterator[AssistantMessageEvent]:
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

    def test_get_provider_missing_raises(self) -> None:
        registry = ApiRegistry()
        try:
            registry.get_provider("missing")
        except KeyError:
            pass
        else:
            msg = "Expected KeyError for missing provider"
            raise AssertionError(msg)

    def test_empty_provider_name_raises(self) -> None:
        registry = ApiRegistry()
        try:
            registry.register("", DummyProvider())
        except ValueError:
            pass
        else:
            msg = "Expected ValueError for empty provider name"
            raise AssertionError(msg)

    def test_get_api_key_success(self) -> None:
        assert get_api_key("openai", env={"OPENAI_API_KEY": "secret"}) == "secret"

    def test_get_api_key_missing_raises(self) -> None:
        try:
            get_api_key("anthropic", env={})
        except ValueError:
            pass
        else:
            msg = "Expected ValueError when key is missing"
            raise AssertionError(msg)

    def test_registry_uses_custom_store(self) -> None:
        store = ApiKeyStore(overrides={"openai": "token"})
        registry = ApiRegistry(api_key_store=store)
        assert registry.get_api_key("openai") == "token"

    def test_provider_helpers_convert_message_and_text_blocks(self) -> None:
        provider = DummyProvider()
        message = Message(
            role=Role.USER,
            content=[TextContent(type="text", text="hello")],
        )
        tool_message = Message(
            role=Role.TOOL,
            content=[TextContent(type="text", text="tool")],
        )
        assert provider.convert_message(message) is None
        assert provider.convert_message(tool_message) is None
        assert provider.convert_messages([message, tool_message]) == []
        assert provider.text_values(message) == ["hello"]
        assert provider.text_blocks(message) == [{"type": "text", "text": "hello"}]


if __name__ == "__main__":
    unittest.main()
