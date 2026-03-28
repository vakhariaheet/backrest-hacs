"""Tests for auth.py — JWT token management."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.backrest.auth import (
    BackrestAuthError,
    BackrestAuthManager,
    BackrestCannotConnectError,
    _decode_jwt_expiry,
)
from tests.conftest import make_jwt

BASE_URL = "http://192.168.1.100:9898"
LOGIN_URL = f"{BASE_URL}/v1.Authentication/Login"


# ---------------------------------------------------------------------------
# _decode_jwt_expiry unit tests
# ---------------------------------------------------------------------------


class TestDecodeJwtExpiry:
    def test_decodes_real_expiry(self):
        """Should extract the exact exp timestamp from a JWT payload."""
        token = make_jwt(exp_offset_seconds=3600)
        expiry = _decode_jwt_expiry(token)

        assert expiry is not None
        assert expiry.tzinfo == timezone.utc

        # Should be approximately 1 hour from now (±5s tolerance)
        expected = datetime.now(timezone.utc) + timedelta(seconds=3600)
        diff = abs((expiry - expected).total_seconds())
        assert diff < 5, f"Expiry off by {diff}s"

    def test_returns_none_when_no_exp_claim(self):
        """Tokens without exp should return None — caller uses fallback."""
        token = make_jwt(include_exp=False)
        assert _decode_jwt_expiry(token) is None

    def test_returns_none_for_malformed_token(self):
        """Should not raise — just return None gracefully."""
        assert _decode_jwt_expiry("not.a.jwt") is None
        assert _decode_jwt_expiry("only_one_part") is None
        assert _decode_jwt_expiry("") is None
        assert _decode_jwt_expiry("a.!!!.c") is None  # bad base64

    def test_returns_none_for_two_part_token(self):
        """JWT with only 2 parts is invalid."""
        assert _decode_jwt_expiry("header.payload") is None

    def test_handles_past_expiry(self):
        """An already-expired token should still decode successfully."""
        token = make_jwt(exp_offset_seconds=-3600)  # expired 1h ago
        expiry = _decode_jwt_expiry(token)
        assert expiry is not None
        assert expiry < datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# BackrestAuthManager tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def session():
    """Real aiohttp.ClientSession — required for aioresponses to intercept calls."""
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as s:
        yield s


@pytest.fixture
async def auth_manager(session):
    return BackrestAuthManager(
        base_url=BASE_URL,
        username="admin",
        password="secret",
        session=session,
        verify_ssl=True,
    )


@pytest.fixture
async def no_auth_manager(session):
    """Auth manager with no credentials — no-auth mode."""
    return BackrestAuthManager(
        base_url=BASE_URL,
        username="",
        password="",
        session=session,
    )


class TestAuthManagerNoAuth:
    async def test_get_token_returns_none(self, no_auth_manager):
        """When no credentials given, get_token() should return None."""
        token = await no_auth_manager.get_token()
        assert token is None

    async def test_auth_enabled_is_false(self, no_auth_manager):
        assert no_auth_manager.auth_enabled is False

    async def test_no_network_call_made(self, no_auth_manager):
        """Should never hit the network when auth is disabled.
        Verified by using aioresponses with no registered URLs — any real
        request would raise ConnectionError."""
        with aioresponses() as mock:
            # No URLs registered — real HTTP call would raise
            result = await no_auth_manager.get_token()
        assert result is None
        assert len(mock.requests) == 0


class TestAuthManagerLogin:
    async def test_successful_login_returns_token(self, auth_manager):
        """Valid credentials should return a JWT."""
        token = make_jwt(exp_offset_seconds=86400)
        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": token}, status=200)
            result = await auth_manager.login()
        assert result == token

    async def test_token_is_cached_after_login(self, auth_manager):
        """Second get_token() should not fire a second HTTP request."""
        token = make_jwt(exp_offset_seconds=86400)
        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": token}, status=200)
            await auth_manager.login()

        # No more mocked responses — if a second request fires, it will raise
        result = await auth_manager.get_token()
        assert result == token

    async def test_401_raises_auth_error(self, auth_manager):
        with aioresponses() as mock:
            mock.post(LOGIN_URL, status=401)
            with pytest.raises(BackrestAuthError, match="Invalid username or password"):
                await auth_manager.login()

    async def test_404_disables_auth(self, auth_manager):
        """404 on login endpoint means Backrest auth is disabled."""
        with aioresponses() as mock:
            mock.post(LOGIN_URL, status=404)
            result = await auth_manager.login()
        assert result is None
        assert auth_manager.auth_enabled is False

    async def test_connection_error_raises_cannot_connect(self, auth_manager):
        with aioresponses() as mock:
            mock.post(LOGIN_URL, exception=aiohttp.ClientConnectorError(MagicMock(), MagicMock()))
            with pytest.raises(BackrestCannotConnectError):
                await auth_manager.login()

    async def test_timeout_raises_cannot_connect(self, auth_manager):
        with aioresponses() as mock:
            mock.post(LOGIN_URL, exception=asyncio.TimeoutError())
            with pytest.raises(BackrestCannotConnectError):
                await auth_manager.login()

    async def test_empty_token_in_response_raises_auth_error(self, auth_manager):
        """Server returning 200 with no token field should raise."""
        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"message": "ok"}, status=200)
            with pytest.raises(BackrestAuthError, match="no token"):
                await auth_manager.login()

    async def test_500_raises_auth_error(self, auth_manager):
        with aioresponses() as mock:
            mock.post(LOGIN_URL, status=500, body="Internal Server Error")
            with pytest.raises(BackrestAuthError):
                await auth_manager.login()


class TestTokenExpiry:
    async def test_uses_real_exp_from_jwt(self, auth_manager):
        """Expiry should be derived from the JWT's exp claim, not a hardcoded value."""
        token = make_jwt(exp_offset_seconds=7200)  # 2 hours
        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": token}, status=200)
            await auth_manager.login()

        expiry = auth_manager._token_expiry
        expected = datetime.now(timezone.utc) + timedelta(seconds=7200)
        diff = abs((expiry - expected).total_seconds())
        assert diff < 5

    async def test_fallback_expiry_when_no_exp_claim(self, auth_manager):
        """Falls back to TOKEN_FALLBACK_LIFETIME_SECONDS when no exp in JWT."""
        token = make_jwt(include_exp=False)
        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": token}, status=200)
            await auth_manager.login()

        from custom_components.backrest.auth import TOKEN_FALLBACK_LIFETIME_SECONDS

        expiry = auth_manager._token_expiry
        expected = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_FALLBACK_LIFETIME_SECONDS)
        diff = abs((expiry - expected).total_seconds())
        assert diff < 5

    async def test_expired_token_triggers_refresh(self, auth_manager):
        """When cached token is expired, get_token() should re-login."""
        expired_token = make_jwt(exp_offset_seconds=-100)
        fresh_token = make_jwt(exp_offset_seconds=86400)

        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": expired_token}, status=200)
            await auth_manager.login()

        # Manually expire the cached token
        auth_manager._token_expiry = datetime.now(timezone.utc) - timedelta(seconds=200)

        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": fresh_token}, status=200)
            result = await auth_manager.get_token()

        assert result == fresh_token

    async def test_token_refreshed_within_buffer(self, auth_manager):
        """Token expiring within TOKEN_REFRESH_BUFFER_SECONDS should be refreshed."""
        from custom_components.backrest.auth import TOKEN_REFRESH_BUFFER_SECONDS

        token = make_jwt(exp_offset_seconds=86400)
        fresh_token = make_jwt(exp_offset_seconds=86400)

        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": token}, status=200)
            await auth_manager.login()

        # Set expiry to within the refresh buffer
        auth_manager._token_expiry = datetime.now(timezone.utc) + timedelta(
            seconds=TOKEN_REFRESH_BUFFER_SECONDS - 10
        )

        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": fresh_token}, status=200)
            result = await auth_manager.get_token()

        assert result == fresh_token


class TestTokenInvalidation:
    async def test_invalidate_clears_token(self, auth_manager):
        token = make_jwt()
        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": token}, status=200)
            await auth_manager.login()

        await auth_manager.invalidate_token()
        assert auth_manager._token is None
        assert auth_manager._token_expiry is None

    async def test_invalidated_token_forces_refresh(self, auth_manager):
        old_token = make_jwt()
        new_token = make_jwt(exp_offset_seconds=3600)

        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": old_token}, status=200)
            await auth_manager.login()

        await auth_manager.invalidate_token()

        with aioresponses() as mock:
            mock.post(LOGIN_URL, payload={"token": new_token}, status=200)
            result = await auth_manager.get_token()

        assert result == new_token


class TestConcurrentRefresh:
    async def test_concurrent_get_token_only_calls_login_once(self, auth_manager):
        """asyncio.Lock should prevent duplicate refresh requests."""
        from yarl import URL

        token = make_jwt()

        with aioresponses() as mock:
            # Register 10 possible responses — only 1 should actually fire
            for _ in range(10):
                mock.post(LOGIN_URL, payload={"token": token}, status=200)

            results = await asyncio.gather(
                *[auth_manager.get_token() for _ in range(10)]
            )

        # aioresponses keys requests by (method, yarl.URL)
        actual_calls = len(mock.requests.get(("POST", URL(LOGIN_URL)), []))
        assert actual_calls == 1, f"Expected 1 login call, got {actual_calls}"
        assert all(r == token for r in results)
