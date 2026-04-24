"""API registry for LLM providers."""

from collections.abc import Mapping

from .auth import ApiKeyStore
from .provider import Provider


class ApiRegistry:
    """Registry for LLM providers."""

    def __init__(self, *, api_key_store: ApiKeyStore | None = None) -> None:
        self._providers: dict[str, Provider] = {}
        self._api_key_store = api_key_store or ApiKeyStore()

    def register(self, name: str, provider: Provider) -> None:
        """Register a provider."""
        if not name:
            msg = "Provider name cannot be empty"
            raise ValueError(msg)
        self._providers[name] = provider

    def get_provider(self, name: str) -> Provider:
        """Get a provider by name."""
        try:
            return self._providers[name]
        except KeyError as exc:
            msg = f"Provider '{name}' is not registered"
            raise KeyError(msg) from exc

    def list_providers(self) -> list[str]:
        """List registered provider names."""
        return list(self._providers.keys())

    def get_api_key(self, provider: str) -> str:
        """Get API key for ``provider`` from configured key store."""
        return self._api_key_store.get(provider)


def get_api_key(provider: str, *, env: Mapping[str, str] | None = None) -> str:
    """Get API key for a provider from environment."""
    return ApiKeyStore(env=env).get(provider)
