"""JWT authentication manager for Backrest."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

# How many seconds before expiry we proactively refresh the token
TOKEN_REFRESH_BUFFER_SECONDS = 60
# Fallback JWT lifetime when the token has no exp claim (24 hours)
TOKEN_FALLBACK_LIFETIME_SECONDS = 86400


def _decode_jwt_expiry(token: str) -> Optional[datetime]:
    """Extract the expiry datetime from a JWT token without verifying the signature.

    JWT format: <header_b64>.<payload_b64>.<signature_b64>
    The payload is a base64url-encoded JSON object. We only need the `exp` field
    (Unix timestamp in seconds). No third-party library is required.

    Returns None if the token is malformed or has no exp claim.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # base64url → standard base64 (pad to multiple of 4)
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        exp = payload.get("exp")
        if exp is None:
            return None

        return datetime.fromtimestamp(int(exp), tz=timezone.utc)

    except Exception:  # noqa: BLE001 — malformed token, degrade gracefully
        _LOGGER.debug("Could not decode JWT expiry; will use fallback lifetime")
        return None


class BackrestAuthError(Exception):
    """Raised when authentication fails (wrong credentials)."""


class BackrestCannotConnectError(Exception):
    """Raised when the Backrest instance is unreachable."""


class BackrestAuthManager:
    """Manages JWT tokens for the Backrest API.

    Handles:
    - Initial login and token fetch
    - Proactive refresh before expiry
    - Transparent no-auth mode (when Backrest auth is disabled)
    """

    def __init__(
        self,
        base_url: str,
        username: Optional[str],
        password: Optional[str],
        session: aiohttp.ClientSession,
        timeout: int = 30,
        verify_ssl: bool = True,
    ) -> None:
        self._base_url = base_url
        self._username = username
        self._password = password
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        # False disables SSL certificate verification (for self-signed certs)
        self._ssl: bool | None = None if verify_ssl else False

        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._lock = asyncio.Lock()

        # If no credentials provided, operate in no-auth mode
        self._auth_enabled = bool(username and password)

    @property
    def auth_enabled(self) -> bool:
        """Return True if authentication is configured."""
        return self._auth_enabled

    async def get_token(self) -> Optional[str]:
        """Return a valid JWT token, refreshing if necessary.

        Returns None when Backrest auth is disabled.
        """
        if not self._auth_enabled:
            return None

        async with self._lock:
            if self._token_is_valid():
                return self._token
            return await self._refresh()

    async def invalidate_token(self) -> None:
        """Force the next get_token() call to fetch a fresh token."""
        async with self._lock:
            self._token = None
            self._token_expiry = None

    def _token_is_valid(self) -> bool:
        """Return True if we have a token that won't expire soon."""
        if not self._token or not self._token_expiry:
            return False
        buffer = timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS)
        return datetime.now(timezone.utc) < (self._token_expiry - buffer)

    async def _refresh(self) -> str:
        """Fetch a new JWT token from Backrest.

        Raises:
            BackrestAuthError: If credentials are invalid.
            BackrestCannotConnectError: If the instance is unreachable.
        """
        url = f"{self._base_url}/v1.Authentication/Login"
        payload = {"username": self._username, "password": self._password}

        _LOGGER.debug("Refreshing Backrest JWT token")

        try:
            async with self._session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self._timeout,
                ssl=self._ssl,
            ) as resp:
                if resp.status == 401:
                    raise BackrestAuthError("Invalid username or password")
                if resp.status == 404:
                    # Auth endpoint missing — treat as auth disabled
                    _LOGGER.warning(
                        "Backrest login endpoint returned 404; assuming auth disabled"
                    )
                    self._auth_enabled = False
                    self._token = None
                    return None
                if resp.status >= 400:
                    text = await resp.text()
                    raise BackrestAuthError(
                        f"Login failed with HTTP {resp.status}: {text}"
                    )

                data = await resp.json(content_type=None)
                token = data.get("token")
                if not token:
                    raise BackrestAuthError("Login response contained no token")

                self._token = token

                # Prefer the real exp claim embedded in the JWT
                decoded_expiry = _decode_jwt_expiry(token)
                if decoded_expiry:
                    self._token_expiry = decoded_expiry
                    _LOGGER.debug(
                        "Backrest JWT token refreshed; expires at %s (from token)",
                        decoded_expiry.isoformat(),
                    )
                else:
                    # Fall back to assuming 24h if there's no exp claim
                    self._token_expiry = datetime.now(timezone.utc) + timedelta(
                        seconds=TOKEN_FALLBACK_LIFETIME_SECONDS
                    )
                    _LOGGER.debug(
                        "Backrest JWT has no exp claim; assuming %ds lifetime",
                        TOKEN_FALLBACK_LIFETIME_SECONDS,
                    )

                return self._token

        except aiohttp.ClientConnectorError as err:
            raise BackrestCannotConnectError(
                f"Cannot connect to Backrest at {self._base_url}"
            ) from err
        except asyncio.TimeoutError as err:
            raise BackrestCannotConnectError(
                f"Timeout connecting to Backrest at {self._base_url}"
            ) from err

    async def login(self) -> Optional[str]:
        """Perform initial login. Alias for get_token() with clearer intent."""
        return await self.get_token()
