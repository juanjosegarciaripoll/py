"""Provider configuration models and serialization helpers."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from .auth import OAuthToken  # noqa: TC001
from .types import JsonObject, JsonValue  # noqa: TC001


class ProviderConfig(BaseModel):
    """Configuration entry for a provider target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    oauth_token: OAuthToken | None = None
    options: JsonObject = Field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        """Serialize provider config to dictionary."""
        loaded: JsonValue = json.loads(self.model_dump_json(exclude_none=True))
        if not isinstance(loaded, dict):
            msg = "Serialized provider config must be a JSON object"
            raise TypeError(msg)
        return loaded

    @classmethod
    def from_dict(cls, payload: JsonObject) -> ProviderConfig:
        """Create provider config from dictionary payload."""
        return cls.model_validate(payload)


class ProvidersConfig(BaseModel):
    """Top-level config containing multiple provider entries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    providers: tuple[ProviderConfig, ...]
    default_provider: str | None = None

    def to_dict(self) -> JsonObject:
        """Serialize to dictionary."""
        loaded: JsonValue = json.loads(self.model_dump_json(exclude_none=True))
        if not isinstance(loaded, dict):
            msg = "Serialized providers config must be a JSON object"
            raise TypeError(msg)
        return loaded

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, payload: JsonObject) -> ProvidersConfig:
        """Create config from dictionary payload."""
        return cls.model_validate(payload)

    @classmethod
    def from_json(cls, payload: str) -> ProvidersConfig:
        """Create config from JSON string."""
        loaded: JsonValue = json.loads(payload)
        if not isinstance(loaded, dict):
            msg = "Provider config JSON must decode to an object"
            raise TypeError(msg)
        return cls.from_dict(loaded)
