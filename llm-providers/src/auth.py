"""Authentication helpers for provider credentials."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from collections.abc import Mapping

from .types import JsonObject, JsonValue  # noqa: TC001


class OAuthToken(BaseModel):
    """Represents an OAuth access token payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    access_token: str = Field(min_length=1)
    token_type: str = "Bearer"  # noqa: S105
    refresh_token: str | None = None
    scope: str | None = None
    expires_at: datetime | None = None

    @field_validator("expires_at", mode="before")
    @classmethod
    def _parse_expires_at(cls, value: object) -> object:
        """Parse ISO string input for ``expires_at``."""
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value

    @field_validator("expires_at")
    @classmethod
    def _ensure_expires_at_timezone(cls, value: datetime | None) -> datetime | None:
        """Normalize ``expires_at`` to timezone-aware UTC."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return ``True`` when the token is expired."""
        if self.expires_at is None:
            return False
        instant = now if now is not None else datetime.now(UTC)
        return instant >= self.expires_at

    def to_dict(self) -> JsonObject:
        """Serialize token to a JSON-compatible dictionary."""
        loaded: JsonValue = json.loads(self.model_dump_json())
        if not isinstance(loaded, dict):
            msg = "Serialized OAuth token must be a JSON object"
            raise TypeError(msg)
        return loaded

    @classmethod
    def from_dict(cls, payload: JsonObject) -> OAuthToken:
        """Create token from a dictionary payload."""
        return cls.model_validate(payload)


class ApiKeyStore:
    """Resolves API keys from explicit overrides and environment values."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        overrides: Mapping[str, str] | None = None,
    ) -> None:
        self._env = env
        self._overrides: dict[str, str] = {
            provider.lower(): value for provider, value in (overrides or {}).items()
        }

    @staticmethod
    def env_var_name(provider: str) -> str:
        """Return the expected environment variable for ``provider``."""
        normalized = provider.strip().replace("-", "_").upper()
        return f"{normalized}_API_KEY"

    def set(self, provider: str, api_key: str) -> None:
        """Set an explicit API key for a provider."""
        if not api_key:
            msg = "API key cannot be empty"
            raise ValueError(msg)
        self._overrides[provider.lower()] = api_key

    def get_optional(self, provider: str) -> str | None:
        """Return API key for a provider when available."""
        provider_name = provider.lower()
        override_value = self._overrides.get(provider_name)
        if override_value:
            return override_value
        env_name = self.env_var_name(provider)
        if self._env is not None:
            return self._env.get(env_name)
        return os.getenv(env_name)

    def get(self, provider: str) -> str:
        """Return API key for a provider or raise when not configured."""
        key = self.get_optional(provider)
        if key is None or not key:
            env_var_name = self.env_var_name(provider)
            msg = (
                f"API key for {provider} not found. "
                f"Expected environment variable {env_var_name}"
            )
            raise ValueError(msg)
        return key


class OAuthTokenStore:
    """In-memory storage for provider OAuth tokens."""

    def __init__(self) -> None:
        self._tokens: dict[str, OAuthToken] = {}

    def set(self, provider: str, token: OAuthToken) -> None:
        """Set OAuth token for provider."""
        self._tokens[provider.lower()] = token

    def get(self, provider: str) -> OAuthToken | None:
        """Return provider token when available."""
        return self._tokens.get(provider.lower())

    def to_dict(self) -> dict[str, JsonObject]:
        """Serialize all tokens."""
        return {
            provider: token.to_dict()
            for provider, token in sorted(self._tokens.items(), key=lambda x: x[0])
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, JsonObject]) -> OAuthTokenStore:
        """Load a token store from a dictionary payload."""
        store = cls()
        for provider, token_payload in payload.items():
            store.set(provider, OAuthToken.from_dict(token_payload))
        return store
