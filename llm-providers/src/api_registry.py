"""API registry for LLM providers."""

import os

from .provider import Provider


class ApiRegistry:
    """Registry for LLM providers."""

    def __init__(self) -> None:
        self.providers: dict[str, Provider] = {}

    def register(self, name: str, provider: Provider) -> None:
        """Register a provider."""
        self.providers[name] = provider

    def get_provider(self, name: str) -> Provider:
        """Get a provider by name."""
        return self.providers[name]

    def list_providers(self) -> list[str]:
        """List registered provider names."""
        return list(self.providers.keys())


def get_api_key(provider: str) -> str:
    """Get API key for a provider from environment."""
    key = os.getenv(f"{provider.upper()}_API_KEY")
    if not key:
        msg = f"API key for {provider} not found in environment"
        raise ValueError(msg)
    return key
