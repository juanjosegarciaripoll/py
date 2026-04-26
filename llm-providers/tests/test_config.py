"""Unit tests for provider configuration serialization."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_providers.auth import OAuthToken
from llm_providers.config import ProviderConfig, ProvidersConfig


class ProviderConfigTests(unittest.TestCase):
    """Tests for provider config payload conversions."""

    def test_provider_config_to_from_dict(self) -> None:
        config = ProviderConfig(
            name="local-ollama",
            provider="openai-compatible",
            model="llama3.1",
            base_url="http://localhost:11434/v1",
            api_key_env="OLLAMA_API_KEY",
            oauth_token=OAuthToken(
                access_token="token",  # noqa: S106
                expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            ),
            options={"temperature": 0.2},
        )
        loaded = ProviderConfig.from_dict(config.to_dict())
        assert loaded == config

    def test_provider_config_requires_mandatory_fields(self) -> None:
        try:
            ProviderConfig.from_dict({"name": "x"})
        except ValidationError:
            pass
        else:
            msg = "Expected ValidationError for missing provider/model"
            raise AssertionError(msg)

    def test_provider_config_from_json_payload_must_be_object(self) -> None:
        try:
            ProvidersConfig.from_json("[]")
        except TypeError:
            pass
        else:
            msg = "Expected TypeError when ProvidersConfig JSON is not an object"
            raise AssertionError(msg)


class ProvidersConfigTests(unittest.TestCase):
    """Tests for top-level providers config."""

    def test_json_round_trip(self) -> None:
        providers_config = ProvidersConfig(
            providers=(
                ProviderConfig(
                    name="main-openai",
                    provider="openai",
                    model="gpt-4o-mini",
                    api_key_env="OPENAI_API_KEY",
                ),
            ),
            default_provider="main-openai",
        )
        payload = providers_config.to_json()
        loaded = ProvidersConfig.from_json(payload)
        assert loaded == providers_config

        parsed = json.loads(payload)
        assert parsed["default_provider"] == "main-openai"

    def test_from_dict_requires_provider_list(self) -> None:
        try:
            ProvidersConfig.from_dict({"providers": "invalid"})
        except ValidationError:
            pass
        else:
            msg = "Expected ValidationError for non-list providers"
            raise AssertionError(msg)


if __name__ == "__main__":
    unittest.main()

