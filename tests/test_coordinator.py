"""Tests for coordinator.py — data parsing, event firing, error handling."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.backrest.api import BackrestServerError
from custom_components.backrest.auth import BackrestAuthError, BackrestCannotConnectError
from custom_components.backrest.const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_BACKUP_COMPLETED,
    EVENT_BACKUP_FAILED,
    EVENT_BACKUP_STARTED,
    EVENT_CONNECTION_LOST,
    EVENT_CONNECTION_RESTORED,
    OP_STATUS_ERROR,
    OP_STATUS_INPROGRESS,
    OP_STATUS_SUCCESS,
    OP_STATUS_WARNING,
)
from custom_components.backrest.coordinator import (
    BackrestCoordinator,
    BackrestData,
    PlanData,
    RepoData,
    _parse_operations,
    _parse_dashboard,
    _ms_to_datetime,
)


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_entry(hass):
    entry = MagicMock()
    entry.entry_id = "test_entry_001"
    entry.data = {"host": "192.168.1.100", "port": 9898}
    entry.options = {}
    return entry


@pytest.fixture
def coordinator(hass, mock_entry, mock_api):
    return BackrestCoordinator(
        hass=hass,
        api=mock_api,
        entry=mock_entry,
        scan_interval=DEFAULT_SCAN_INTERVAL,
    )


# ---------------------------------------------------------------------------
# _ms_to_datetime
# ---------------------------------------------------------------------------


class TestMsToDatetime:
    def test_converts_ms_to_utc_datetime(self):
        ms = 1_700_000_000_000  # 2023-11-14 22:13:20 UTC
        dt = _ms_to_datetime(ms)
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2023

    def test_returns_none_for_zero(self):
        assert _ms_to_datetime(0) is None

    def test_returns_none_for_none(self):
        assert _ms_to_datetime(None) is None


# ---------------------------------------------------------------------------
# _parse_operations
# ---------------------------------------------------------------------------


class TestParseOperations:
    def _make_plans(self):
        return {
            "daily-home": PlanData(id="daily-home", repo_id="s3-main"),
            "weekly-archive": PlanData(id="weekly-archive", repo_id="local-nas"),
        }

    def test_marks_plan_as_running(self):
        plans = self._make_plans()
        ops = [
            {
                "id": "1",
                "planId": "daily-home",
                "status": OP_STATUS_INPROGRESS,
                "unixTimeStartMs": 1_700_000_000_000,
            }
        ]
        _parse_operations(ops, plans)
        assert plans["daily-home"].is_running is True
        assert plans["weekly-archive"].is_running is False

    def test_records_last_successful_backup(self):
        plans = self._make_plans()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        ops = [
            {
                "id": "1",
                "planId": "daily-home",
                "status": OP_STATUS_SUCCESS,
                "unixTimeStartMs": now_ms - 3_600_000,
                "unixTimeEndMs": now_ms,
                "operationBackup": {
                    "lastStatus": {
                        "summary": {"filesNew": 10, "dataAdded": 500_000}
                    }
                },
            }
        ]
        _parse_operations(ops, plans)
        assert plans["daily-home"].last_backup_status == OP_STATUS_SUCCESS
        assert plans["daily-home"].last_backup_time is not None
        assert plans["daily-home"].last_backup_duration_seconds == pytest.approx(3600, abs=5)
        assert plans["daily-home"].last_backup_bytes_added == 500_000
        assert plans["daily-home"].last_backup_files_new == 10

    def test_only_records_most_recent_operation(self):
        """If two completed ops exist for a plan, only the newest counts."""
        plans = self._make_plans()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        ops = [
            {
                "id": "1",
                "planId": "daily-home",
                "status": OP_STATUS_SUCCESS,
                "unixTimeStartMs": now_ms - 7_200_000,  # 2h ago
                "unixTimeEndMs": now_ms - 7_100_000,
                "operationBackup": {"lastStatus": {"summary": {"dataAdded": "100"}}},
            },
            {
                "id": "2",
                "planId": "daily-home",
                "status": OP_STATUS_ERROR,
                "unixTimeStartMs": now_ms - 3_600_000,  # 1h ago (newer)
                "unixTimeEndMs": now_ms - 3_550_000,
                "operationBackup": {"lastStatus": {"summary": {}}},
            },
        ]
        _parse_operations(ops, plans)
        assert plans["daily-home"].last_backup_status == OP_STATUS_ERROR

    def test_ignores_unknown_plan_ids(self):
        """Operations for unknown plans should not crash."""
        plans = self._make_plans()
        ops = [
            {"id": "1", "planId": "ghost-plan", "status": OP_STATUS_SUCCESS}
        ]
        _parse_operations(ops, plans)  # Should not raise

    def test_sets_active_operation_id(self):
        plans = self._make_plans()
        ops = [
            {
                "id": "999",
                "planId": "daily-home",
                "status": OP_STATUS_INPROGRESS,
                "unixTimeStartMs": 1_700_000_000_000,
            }
        ]
        _parse_operations(ops, plans)
        assert plans["daily-home"].active_operation_id == 999


# ---------------------------------------------------------------------------
# _parse_dashboard
# ---------------------------------------------------------------------------


class TestParseDashboard:
    def _make_repos_and_plans(self):
        repos = {
            "s3-main": RepoData(id="s3-main", uri="s3:bucket"),
        }
        plans = {
            "daily-home": PlanData(id="daily-home", repo_id="s3-main"),
        }
        return repos, plans

    def test_parses_repo_stats(self):
        repos, plans = self._make_repos_and_plans()
        dashboard = {
            "repoSummaries": [
                {
                    "id": "s3-main",
                    "bytesAddedLast30days": "10000000000",
                    "backupsSuccessLast30days": "42",
                }
            ],
            "planSummaries": [],
        }
        _parse_dashboard(dashboard, repos, plans)
        # Repo has no settable fields from dashboard currently — just verify no crash

    def test_parses_plan_stats(self):
        repos, plans = self._make_repos_and_plans()
        dashboard = {
            "repoSummaries": [],
            "planSummaries": [
                {
                    "id": "daily-home",
                    "bytesAddedLast30days": "2000000000",
                    "backupsSuccessLast30days": "30",
                    "backupsFailedLast30days": "2",
                }
            ],
        }
        _parse_dashboard(dashboard, repos, plans)
        plan = plans["daily-home"]
        assert plan.bytes_added_30d == 2_000_000_000
        assert plan.backup_count_30d == 30
        assert plan.failure_count_30d == 2

    def test_ignores_unknown_ids(self):
        repos, plans = self._make_repos_and_plans()
        dashboard = {
            "repoSummaries": [{"repoId": "ghost-repo", "repoStats": {}}],
            "planSummaries": [{"planId": "ghost-plan", "bytesAdded": 0}],
        }
        _parse_dashboard(dashboard, repos, plans)  # Should not raise


# ---------------------------------------------------------------------------
# Coordinator full fetch
# ---------------------------------------------------------------------------


class TestCoordinatorFetch:
    async def test_successful_fetch_returns_data(
        self,
        coordinator,
        mock_config_response,
        mock_dashboard_response,
        mock_operations_response,
    ):
        data = await coordinator._async_update_data()
        assert isinstance(data, BackrestData)
        assert data.instance_name == "homelab"
        assert "s3-main" in data.repos
        assert "local-nas" in data.repos
        assert "daily-home" in data.plans
        assert "weekly-archive" in data.plans

    async def test_repos_populated(self, coordinator):
        data = await coordinator._async_update_data()
        assert data.repos["s3-main"].uri == "s3:mybucket/backups"
        assert data.repos["local-nas"].uri == "/mnt/nas/backups"

    async def test_plan_last_backup_status_populated(self, coordinator):
        data = await coordinator._async_update_data()
        assert data.plans["daily-home"].last_backup_status == OP_STATUS_SUCCESS

    async def test_last_poll_success_is_true(self, coordinator):
        data = await coordinator._async_update_data()
        assert data.last_poll_success is True

    async def test_auth_error_raises_config_entry_auth_failed(
        self, coordinator, mock_api
    ):
        mock_api.get_config.side_effect = BackrestAuthError("bad token")
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    async def test_connection_error_raises_update_failed(
        self, coordinator, mock_api
    ):
        mock_api.get_config.side_effect = BackrestCannotConnectError("timeout")
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    async def test_server_error_raises_update_failed(self, coordinator, mock_api):
        mock_api.get_config.side_effect = BackrestServerError("500")
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# HA event firing
# ---------------------------------------------------------------------------


class TestEventFiring:
    async def test_fires_backup_started_event(
        self, hass, coordinator, mock_api, mock_operations_response
    ):
        # First poll — no operations running
        mock_api.get_operations.return_value = {"operations": []}
        await coordinator._async_update_data()

        # Second poll — daily-home is now INPROGRESS
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        mock_api.get_operations.return_value = {
            "operations": [
                {
                    "id": "555",
                    "planId": "daily-home",
                    "repoId": "s3-main",
                    "status": OP_STATUS_INPROGRESS,
                    "unixTimeStartMs": now_ms,
                }
            ]
        }

        fired_events = []
        hass.bus.async_listen(EVENT_BACKUP_STARTED, lambda e: fired_events.append(e))

        await coordinator._async_update_data()
        await hass.async_block_till_done()

        assert len(fired_events) == 1
        assert fired_events[0].data["plan_id"] == "daily-home"

    async def test_fires_backup_completed_event(
        self, hass, coordinator, mock_api
    ):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # First poll — backup is running
        mock_api.get_operations.return_value = {
            "operations": [
                {
                    "id": "555",
                    "planId": "daily-home",
                    "repoId": "s3-main",
                    "status": OP_STATUS_INPROGRESS,
                    "unixTimeStartMs": now_ms - 60_000,
                }
            ]
        }
        await coordinator._async_update_data()

        # Second poll — backup just finished successfully
        mock_api.get_operations.return_value = {
            "operations": [
                {
                    "id": "555",
                    "planId": "daily-home",
                    "repoId": "s3-main",
                    "status": OP_STATUS_SUCCESS,
                    "unixTimeStartMs": now_ms - 60_000,
                    "unixTimeEndMs": now_ms,
                    "operationBackup": {"lastStatus": {"summary": {"dataAdded": "1200000"}}},
                }
            ]
        }

        fired_events = []
        hass.bus.async_listen(EVENT_BACKUP_COMPLETED, lambda e: fired_events.append(e))

        await coordinator._async_update_data()
        await hass.async_block_till_done()

        assert len(fired_events) == 1
        assert fired_events[0].data["plan_id"] == "daily-home"
        assert fired_events[0].data["status"] == OP_STATUS_SUCCESS

    async def test_fires_backup_failed_event_on_error(
        self, hass, coordinator, mock_api
    ):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # First poll — running
        mock_api.get_operations.return_value = {
            "operations": [
                {
                    "id": "666",
                    "planId": "daily-home",
                    "status": OP_STATUS_INPROGRESS,
                    "unixTimeStartMs": now_ms - 60_000,
                }
            ]
        }
        await coordinator._async_update_data()

        # Second poll — failed
        mock_api.get_operations.return_value = {
            "operations": [
                {
                    "id": "666",
                    "planId": "daily-home",
                    "status": OP_STATUS_ERROR,
                    "unixTimeStartMs": now_ms - 60_000,
                    "unixTimeEndMs": now_ms,
                    "operationBackup": {"lastStatus": {"summary": {}}},
                }
            ]
        }

        failed_events = []
        hass.bus.async_listen(EVENT_BACKUP_FAILED, lambda e: failed_events.append(e))

        await coordinator._async_update_data()
        await hass.async_block_till_done()
        assert len(failed_events) == 1

    async def test_fires_connection_lost_and_restored(
        self, hass, coordinator, mock_api
    ):
        # First successful poll
        await coordinator._async_update_data()

        # Connection drops
        mock_api.get_config.side_effect = BackrestCannotConnectError("down")

        lost_events = []
        restored_events = []
        hass.bus.async_listen(EVENT_CONNECTION_LOST, lambda e: lost_events.append(e))
        hass.bus.async_listen(
            EVENT_CONNECTION_RESTORED, lambda e: restored_events.append(e)
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        await hass.async_block_till_done()
        assert len(lost_events) == 1

        # Connection comes back
        mock_api.get_config.side_effect = None
        await coordinator._async_update_data()
        await hass.async_block_till_done()
        assert len(restored_events) == 1

    async def test_connection_lost_fires_only_once(
        self, hass, coordinator, mock_api
    ):
        """Should not spam events on repeated failures."""
        await coordinator._async_update_data()  # establish prev_connected=True
        mock_api.get_config.side_effect = BackrestCannotConnectError("down")

        lost_events = []
        hass.bus.async_listen(EVENT_CONNECTION_LOST, lambda e: lost_events.append(e))

        for _ in range(3):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
        await hass.async_block_till_done()

        assert len(lost_events) == 1  # Only fired on the first failure
