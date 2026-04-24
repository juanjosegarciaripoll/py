"""OpenAI-compatible provider implementation."""

from .openai import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    """OpenAI-compatible LLM provider."""

    def __init__(self, api_key: str, base_url: str) -> None:
        super().__init__(api_key=api_key, base_url=base_url)
