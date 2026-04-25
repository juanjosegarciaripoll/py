"""Unit tests for auth helpers."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.auth import ApiKeyStore, OAuthToken, OAuthTokenStore


class OAuthTokenTests(unittest.TestCase):
    """Tests for OAuth token serialization and expiry behavior."""

    def test_to_from_dict_round_trip(self) -> None:
        expires_at = datetime(2030, 1, 1, tzinfo=UTC)
        token = OAuthToken(
            access_token="token-123",  # noqa: S106
            refresh_token="refresh-456",  # noqa: S106
            scope="read write",
            expires_at=expires_at,
        )
        loaded = OAuthToken.from_dict(token.to_dict())
        assert loaded == token

    def test_is_expired(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        expired = OAuthToken(
            access_token="old",  # noqa: S106
            expires_at=now - timedelta(seconds=1),
        )
        active = OAuthToken(
            access_token="new",  # noqa: S106
            expires_at=now + timedelta(seconds=1),
        )
        assert expired.is_expired(now) is True
        assert active.is_expired(now) is False

    def test_from_dict_requires_access_token(self) -> None:
        try:
            OAuthToken.from_dict({})
        except ValidationError:
            pass
        else:
            msg = "Expected ValidationError when access_token is missing"
            raise AssertionError(msg)

    def test_naive_expiry_is_normalized_and_missing_expiry_is_not_expired(self) -> None:
        token = OAuthToken.from_dict(
            {
                "access_token": "token-value",
                "expires_at": "2030-01-01T00:00:00",
            }
        )
        assert token.expires_at is not None
        assert token.expires_at.tzinfo is not None
        assert OAuthToken(access_token="token-value").is_expired() is False  # noqa: S106


class ApiKeyStoreTests(unittest.TestCase):
    """Tests for API key store resolution rules."""

    def test_override_takes_priority(self) -> None:
        store = ApiKeyStore(
            env={"OPENAI_API_KEY": "env-key"},
            overrides={"openai": "override-key"},
        )
        assert store.get("openai") == "override-key"

    def test_reads_from_env_mapping(self) -> None:
        store = ApiKeyStore(env={"ANTHROPIC_API_KEY": "abc"})
        assert store.get("anthropic") == "abc"

    def test_missing_key_raises(self) -> None:
        store = ApiKeyStore(env={})
        try:
            store.get("openai")
        except ValueError:
            pass
        else:
            msg = "Expected ValueError when API key is missing"
            raise AssertionError(msg)

    def test_env_var_name_and_set_validation(self) -> None:
        store = ApiKeyStore()
        assert store.env_var_name("openai-compatible") == "OPENAI_COMPATIBLE_API_KEY"
        try:
            store.set("openai", "")
        except ValueError:
            pass
        else:
            msg = "Expected ValueError when API key is empty"
            raise AssertionError(msg)


class OAuthTokenStoreTests(unittest.TestCase):
    """Tests for in-memory OAuth token store."""

    def test_set_get_and_serialize(self) -> None:
        token = OAuthToken(access_token="abc")  # noqa: S106
        store = OAuthTokenStore()
        store.set("openai", token)
        assert store.get("openai") == token

        serialized = store.to_dict()
        loaded = OAuthTokenStore.from_dict(serialized)
        assert loaded.get("openai") == token


if __name__ == "__main__":
    unittest.main()
