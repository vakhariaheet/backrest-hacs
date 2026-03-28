"""Shared pytest fixtures for the Backrest integration tests."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.backrest.const import (
    CONF_SCAN_INTERVAL,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_jwt(exp_offset_seconds: int = 86400, include_exp: bool = True) -> str:
    """Build a minimal fake JWT with a real base64url-encoded payload.

    Args:
        exp_offset_seconds: Seconds from now until token expiry.
        include_exp: Whether to include the exp claim (False = no expiry).
    """
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    payload_data: dict[str, Any] = {"sub": "testuser"}
    if include_exp:
        exp = int((datetime.now(timezone.utc) + timedelta(seconds=exp_offset_seconds)).timestamp())
        payload_data["exp"] = exp

    payload = base64.urlsafe_b64encode(
        json.dumps(payload_data).encode()
    ).rstrip(b"=").decode()

    # Signature doesn't need to be real — we never verify it
    signature = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


# ---------------------------------------------------------------------------
# Config entry fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config_entry_data() -> dict:
    """Minimal valid config entry data."""
    return {
        "host": "192.168.1.100",
        "port": DEFAULT_PORT,
        CONF_USE_SSL: False,
        CONF_VERIFY_SSL: True,
        "username": "admin",
        "password": "secret",
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    }


@pytest.fixture
def mock_config_entry(hass: HomeAssistant, mock_config_entry_data):
    """A mock config entry added to HA."""
    from homeassistant.config_entries import ConfigEntry

    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id_001"
    entry.domain = DOMAIN
    entry.title = "Backrest (test)"
    entry.data = mock_config_entry_data
    entry.options = {}
    entry.unique_id = "192.168.1.100:9898"
    entry.state = "loaded"
    return entry


# ---------------------------------------------------------------------------
# Backrest API response fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config_response() -> dict:
    """Realistic GetConfig response."""
    return {
        "instance": "homelab",
        "modno": 5,
        "repos": [
            {
                "id": "s3-main",
                "uri": "s3:mybucket/backups",
                "guid": "abc123",
            },
            {
                "id": "local-nas",
                "uri": "/mnt/nas/backups",
                "guid": "def456",
            },
        ],
        "plans": [
            {
                "id": "daily-home",
                "repo": "s3-main",
                "schedule": {"cron": "0 3 * * *"},
            },
            {
                "id": "weekly-archive",
                "repo": "local-nas",
                "schedule": {"cron": "0 2 * * 0"},
            },
        ],
    }


@pytest.fixture
def mock_dashboard_response() -> dict:
    """Realistic GetSummaryDashboard response."""
    return {
        "repoSummaries": [
            {
                "repoId": "s3-main",
                "repoStats": {
                    "snapshotCount": 42,
                    "totalSize": 10_000_000_000,  # 10 GB
                    "totalUncompressedSize": 25_000_000_000,  # 25 GB
                    "compressionRatio": 2.5,
                },
            },
            {
                "repoId": "local-nas",
                "repoStats": {
                    "snapshotCount": 8,
                    "totalSize": 5_000_000_000,
                    "totalUncompressedSize": 8_000_000_000,
                    "compressionRatio": 1.6,
                },
            },
        ],
        "planSummaries": [
            {
                "planId": "daily-home",
                "bytesAdded": 2_000_000_000,
                "backupCount": 28,
                "failedBackupCount": 1,
            },
            {
                "planId": "weekly-archive",
                "bytesAdded": 500_000_000,
                "backupCount": 4,
                "failedBackupCount": 0,
            },
        ],
    }


@pytest.fixture
def mock_operations_response() -> dict:
    """Realistic GetOperations response with one completed backup per plan."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    one_hour_ago_ms = now_ms - 3_600_000
    return {
        "operations": [
            {
                "id": "1001",
                "planId": "daily-home",
                "repoId": "s3-main",
                "status": "STATUS_SUCCESS",
                "unixTimeStartMs": one_hour_ago_ms,
                "unixTimeEndMs": now_ms - 3_540_000,  # 1 min duration
                "operationBackup": {
                    "lastStatus": {
                        "summary": {
                            "filesNew": 37,
                            "dataAdded": 1_200_000,
                        }
                    }
                },
            },
            {
                "id": "1002",
                "planId": "weekly-archive",
                "repoId": "local-nas",
                "status": "STATUS_SUCCESS",
                "unixTimeStartMs": one_hour_ago_ms - 3_600_000,
                "unixTimeEndMs": one_hour_ago_ms - 3_540_000,
                "operationBackup": {
                    "lastStatus": {
                        "summary": {
                            "filesNew": 5,
                            "dataAdded": 500_000,
                        }
                    }
                },
            },
        ]
    }


@pytest.fixture
def mock_empty_operations_response() -> dict:
    return {"operations": []}


# ---------------------------------------------------------------------------
# Mock API client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_api(
    mock_config_response,
    mock_dashboard_response,
    mock_operations_response,
):
    """A mock BackrestApiClient that returns realistic data."""
    api = AsyncMock()
    api.get_config = AsyncMock(return_value=mock_config_response)
    api.get_summary_dashboard = AsyncMock(return_value=mock_dashboard_response)
    api.get_operations = AsyncMock(return_value=mock_operations_response)
    api.trigger_backup = AsyncMock(return_value={})
    api.cancel_operation = AsyncMock(return_value={})
    api.do_repo_task = AsyncMock(return_value={})
    api.run_prune = AsyncMock(return_value={})
    api.run_check = AsyncMock(return_value={})
    api.run_stats = AsyncMock(return_value={})
    api.unlock_repo = AsyncMock(return_value={})
    api.forget_snapshots = AsyncMock(return_value={})
    api.list_snapshots = AsyncMock(
        return_value={
            "snapshots": [
                {
                    "id": "abcdef1234",
                    "unixTimeMs": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "hostname": "homelab",
                    "paths": ["/home"],
                    "tags": ["plan:daily-home"],
                }
            ]
        }
    )
    return api
