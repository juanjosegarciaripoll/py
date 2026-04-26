"""Unit tests for py-coding-agent integration bridge."""

from __future__ import annotations

import os
import unittest

from src.integration import AgenticResponder, AgentRuntimeError, RuntimeModelConfig


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Tests for integrated py-agent + llm-providers responder behavior."""

    async def test_agentic_responder_echo_provider(self) -> None:
        responder = AgenticResponder(
            RuntimeModelConfig(
                backend="agent",
                provider="echo",
                model="echo-1",
            )
        )
        text = await responder.respond("hello", system_prompt="system")
        assert text == "Echo: hello"

    async def test_agentic_responder_handles_provider_delta_and_tool_calls(
        self,
    ) -> None:
        responder = AgenticResponder(
            RuntimeModelConfig(
                backend="agent",
                provider="echo",
                model="echo-structured",
            )
        )
        llm = responder.llm_types

        class FakeProvider:
            async def stream(
                self,
                model: str,
                system_prompt: str,
                messages: list[object],
                tools: list[object],
            ):
                del model, system_prompt, messages, tools
                delta = llm.Message(
                    role=llm.Role.ASSISTANT,
                    content=[llm.TextContent(type="text", text="partial")],
                    tool_calls=[
                        llm.ToolCall(
                            id="tool-1",
                            function={"name": "read", "arguments": "{bad"},
                        )
                    ],
                )
                yield llm.AssistantMessageEvent(
                    delta=delta,
                    usage=llm.Usage(
                        input_tokens=11,
                        output_tokens=13,
                        total_tokens=24,
                    ),
                    finish_reason="toolUse",
                )

        responder.set_provider(FakeProvider())
        text = await responder.respond("hello", system_prompt="system")
        assert text == "partial"

    async def test_missing_api_key_environment_raises(self) -> None:
        original = os.environ.get("OPENAI_API_KEY")
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
        try:
            failed = False
            try:
                AgenticResponder(
                    RuntimeModelConfig(
                        backend="agent",
                        provider="openai",
                        model="gpt-4o-mini",
                        api_key_env="OPENAI_API_KEY",
                    )
                )
            except AgentRuntimeError:
                failed = True
            assert failed is True
        finally:
            if original is not None:
                os.environ["OPENAI_API_KEY"] = original

    async def test_openai_compatible_requires_base_url(self) -> None:
        original = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            failed = False
            try:
                AgenticResponder(
                    RuntimeModelConfig(
                        backend="agent",
                        provider="openai_compatible",
                        model="model",
                        api_key_env="OPENAI_API_KEY",
                        base_url=None,
                    )
                )
            except AgentRuntimeError:
                failed = True
            assert failed is True
        finally:
            if original is None:
                del os.environ["OPENAI_API_KEY"]
            else:
                os.environ["OPENAI_API_KEY"] = original


if __name__ == "__main__":
    unittest.main()
