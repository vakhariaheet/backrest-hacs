"""Tests for api.py — Backrest API client."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.backrest.api import BackrestApiClient, BackrestServerError
from custom_components.backrest.auth import (
    BackrestAuthError,
    BackrestAuthManager,
    BackrestCannotConnectError,
)
from tests.conftest import make_jwt

BASE_URL = "http://192.168.1.100:9898"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_auth():
    """An auth manager that always returns a valid token without HTTP calls."""
    auth = AsyncMock(spec=BackrestAuthManager)
    auth.get_token = AsyncMock(return_value=make_jwt())
    auth.invalidate_token = AsyncMock()
    auth.auth_enabled = True
    return auth


@pytest.fixture
def mock_auth_no_token():
    """An auth manager in no-auth mode."""
    auth = AsyncMock(spec=BackrestAuthManager)
    auth.get_token = AsyncMock(return_value=None)
    auth.auth_enabled = False
    return auth


@pytest.fixture
async def session():
    """Real aiohttp.ClientSession — required for aioresponses interception."""
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as s:
        yield s


@pytest.fixture
async def api(mock_auth, session):
    return BackrestApiClient(
        base_url=BASE_URL,
        auth_manager=mock_auth,
        session=session,
        verify_ssl=True,
    )


@pytest.fixture
async def api_no_auth(mock_auth_no_token, session):
    return BackrestApiClient(
        base_url=BASE_URL,
        auth_manager=mock_auth_no_token,
        session=session,
    )


# ---------------------------------------------------------------------------
# Request helper behaviour
# ---------------------------------------------------------------------------


class TestRequestHelper:
    async def test_injects_bearer_token(self, api, mock_auth):
        """Every request should carry Authorization: Bearer <token>."""
        from yarl import URL

        token = make_jwt()
        mock_auth.get_token.return_value = token

        with aioresponses() as mock:
            mock.post(
                f"{BASE_URL}/v1.Backrest/GetConfig",
                payload={"instance": "test"},
                status=200,
            )
            await api.get_config()

        # aioresponses keys requests by (method, URL object)
        key = ("POST", URL(f"{BASE_URL}/v1.Backrest/GetConfig"))
        assert key in mock.requests
        call_kwargs = mock.requests[key][0].kwargs
        assert call_kwargs["headers"]["Authorization"] == f"Bearer {token}"

    async def test_no_auth_header_when_no_token(self, api_no_auth):
        """No Authorization header should be sent when in no-auth mode."""
        with aioresponses() as mock:
            mock.post(
                f"{BASE_URL}/v1.Backrest/GetConfig",
                payload={"instance": "noauth"},
                status=200,
            )
            result = await api_no_auth.get_config()

        assert result["instance"] == "noauth"

    async def test_retries_once_on_401(self, api, mock_auth):
        """On 401, the client should invalidate token and retry exactly once."""
        fresh_token = make_jwt()
        mock_auth.get_token.side_effect = [make_jwt(), fresh_token]

        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/GetConfig", status=401)
            mock.post(
                f"{BASE_URL}/v1.Backrest/GetConfig",
                payload={"instance": "retried"},
                status=200,
            )
            result = await api.get_config()

        mock_auth.invalidate_token.assert_called_once()
        assert result["instance"] == "retried"

    async def test_raises_auth_error_on_second_401(self, api, mock_auth):
        """If the retry also returns 401, raise BackrestAuthError."""
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/GetConfig", status=401)
            mock.post(f"{BASE_URL}/v1.Backrest/GetConfig", status=401)
            with pytest.raises(BackrestAuthError):
                await api.get_config()

    async def test_raises_server_error_on_500(self, api):
        with aioresponses() as mock:
            mock.post(
                f"{BASE_URL}/v1.Backrest/GetConfig", status=500, body="boom"
            )
            with pytest.raises(BackrestServerError, match="500"):
                await api.get_config()

    async def test_raises_cannot_connect_on_connection_error(self, api):
        with aioresponses() as mock:
            mock.post(
                f"{BASE_URL}/v1.Backrest/GetConfig",
                exception=aiohttp.ClientConnectorError(MagicMock(), MagicMock()),
            )
            with pytest.raises(BackrestCannotConnectError):
                await api.get_config()

    async def test_raises_cannot_connect_on_timeout(self, api):
        with aioresponses() as mock:
            mock.post(
                f"{BASE_URL}/v1.Backrest/GetConfig",
                exception=asyncio.TimeoutError(),
            )
            with pytest.raises(BackrestCannotConnectError):
                await api.get_config()

    async def test_returns_empty_dict_on_204(self, api):
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/Backup", status=204)
            result = await api.trigger_backup("daily-home")
        assert result == {}


# ---------------------------------------------------------------------------
# Per-endpoint smoke tests
# ---------------------------------------------------------------------------


class TestEndpoints:
    async def test_get_config(self, api):
        payload = {"instance": "homelab", "modno": 3, "repos": [], "plans": []}
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/GetConfig", payload=payload)
            result = await api.get_config()
        assert result["instance"] == "homelab"

    async def test_get_summary_dashboard(self, api):
        payload = {"repoSummaries": [], "planSummaries": []}
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/GetSummaryDashboard", payload=payload)
            result = await api.get_summary_dashboard()
        assert "repoSummaries" in result

    async def test_get_operations_no_filter(self, api):
        payload = {"operations": []}
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/GetOperations", payload=payload)
            result = await api.get_operations()
        assert result["operations"] == []

    async def test_get_operations_with_filters(self, api):
        payload = {"operations": [{"id": "1"}]}
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/GetOperations", payload=payload)
            result = await api.get_operations(repo_id="s3-main", plan_id="daily-home")
        assert len(result["operations"]) == 1

    async def test_trigger_backup(self, api):
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/Backup", payload={})
            result = await api.trigger_backup("daily-home")
        assert result == {}

    async def test_forget_snapshots(self, api):
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/Forget", payload={})
            await api.forget_snapshots("daily-home", "s3-main")

    async def test_cancel_operation(self, api):
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/Cancel", payload={})
            await api.cancel_operation(42)

    async def test_do_repo_task_prune(self, api):
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/DoRepoTask", payload={})
            await api.run_prune("s3-main")

    async def test_do_repo_task_check(self, api):
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/DoRepoTask", payload={})
            await api.run_check("s3-main")

    async def test_do_repo_task_stats(self, api):
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/DoRepoTask", payload={})
            await api.run_stats("s3-main")

    async def test_do_repo_task_unlock(self, api):
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/DoRepoTask", payload={})
            await api.unlock_repo("s3-main")

    async def test_list_snapshots_no_filter(self, api):
        payload = {"snapshots": [{"id": "abc"}]}
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/ListSnapshots", payload=payload)
            result = await api.list_snapshots("s3-main")
        assert len(result["snapshots"]) == 1

    async def test_list_snapshots_with_plan_and_tag(self, api):
        payload = {"snapshots": []}
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/ListSnapshots", payload=payload)
            result = await api.list_snapshots("s3-main", plan_id="daily-home", tag="v2")
        assert result["snapshots"] == []

    async def test_path_autocomplete(self, api):
        payload = {"values": ["/home", "/etc"]}
        with aioresponses() as mock:
            mock.post(f"{BASE_URL}/v1.Backrest/PathAutocomplete", payload=payload)
            result = await api.path_autocomplete("/")
        assert "/home" in result["values"]


# ---------------------------------------------------------------------------
# SSL verification
# ---------------------------------------------------------------------------


class TestSslVerification:
    async def test_ssl_none_when_verify_true(self, mock_auth, session):
        """verify_ssl=True → ssl=None (use default CA verification)."""
        client = BackrestApiClient(BASE_URL, mock_auth, session, verify_ssl=True)
        assert client._ssl is None

    async def test_ssl_false_when_verify_false(self, mock_auth, session):
        """verify_ssl=False → ssl=False (skip certificate verification)."""
        client = BackrestApiClient(BASE_URL, mock_auth, session, verify_ssl=False)
        assert client._ssl is False
