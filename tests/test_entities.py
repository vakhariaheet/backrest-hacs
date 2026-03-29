"""Tests for sensor.py, binary_sensor.py, and button.py entity behaviour."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.backrest.coordinator import (
    BackrestData,
    PlanData,
    RepoData,
)
from custom_components.backrest.const import (
    DEFAULT_STALE_THRESHOLD_HOURS,
    OP_STATUS_ERROR,
    OP_STATUS_SUCCESS,
    OP_STATUS_WARNING,
    OP_STATUS_INPROGRESS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_data(
    plan_status=OP_STATUS_SUCCESS,
    plan_running=False,
    last_backup_hours_ago=1,
    failure_count_30d=0,
) -> BackrestData:
    """Build a BackrestData object with configurable fields."""
    last_backup = datetime.now(timezone.utc) - timedelta(hours=last_backup_hours_ago)
    data = BackrestData(
        instance_name="homelab",
        config_version=1,
        repos={
            "s3-main": RepoData(
                id="s3-main",
                uri="s3:bucket",
            )
        },
        plans={
            "daily-home": PlanData(
                id="daily-home",
                repo_id="s3-main",
                schedule_cron="0 3 * * *",
                last_backup_time=last_backup,
                last_backup_status=plan_status,
                last_backup_duration_seconds=120.0,
                last_backup_bytes_added=1_200_000,
                last_backup_files_new=37,
                bytes_added_30d=2_000_000_000,
                backup_count_30d=28,
                failure_count_30d=failure_count_30d,
                is_running=plan_running,
                active_operation_id=999 if plan_running else None,
            )
        },
        active_operation_ids=[999] if plan_running else [],
        last_poll_success=True,
    )
    return data


def _make_coordinator(data: BackrestData, entry=None):
    """Build a minimal mock coordinator."""
    coord = MagicMock()
    coord.data = data
    coord.config_entry = entry or MagicMock()
    coord.config_entry.entry_id = "test_entry_001"
    coord.config_entry.options = {}
    return coord


# ===========================================================================
# SENSOR TESTS
# ===========================================================================


class TestInstanceSensors:
    def test_repo_count(self):
        from custom_components.backrest.sensor import (
            BackrestInstanceSensor,
            INSTANCE_SENSORS,
        )

        data = _make_data()
        coord = _make_coordinator(data)
        desc = next(s for s in INSTANCE_SENSORS if s.key == "repo_count")
        sensor = BackrestInstanceSensor(coord, desc)
        assert sensor.native_value == 1

    def test_plan_count(self):
        from custom_components.backrest.sensor import (
            BackrestInstanceSensor,
            INSTANCE_SENSORS,
        )

        data = _make_data()
        coord = _make_coordinator(data)
        desc = next(s for s in INSTANCE_SENSORS if s.key == "plan_count")
        sensor = BackrestInstanceSensor(coord, desc)
        assert sensor.native_value == 1

    def test_active_operations_zero_when_idle(self):
        from custom_components.backrest.sensor import (
            BackrestInstanceSensor,
            INSTANCE_SENSORS,
        )

        data = _make_data(plan_running=False)
        coord = _make_coordinator(data)
        desc = next(s for s in INSTANCE_SENSORS if s.key == "active_operations")
        sensor = BackrestInstanceSensor(coord, desc)
        assert sensor.native_value == 0

    def test_active_operations_one_when_running(self):
        from custom_components.backrest.sensor import (
            BackrestInstanceSensor,
            INSTANCE_SENSORS,
        )

        data = _make_data(plan_running=True)
        coord = _make_coordinator(data)
        desc = next(s for s in INSTANCE_SENSORS if s.key == "active_operations")
        sensor = BackrestInstanceSensor(coord, desc)
        assert sensor.native_value == 1



class TestPlanSensors:
    def test_last_backup_status_success(self):
        from custom_components.backrest.sensor import BackrestPlanSensor, PLAN_SENSORS

        data = _make_data(plan_status=OP_STATUS_SUCCESS)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_SENSORS if s.key == "last_backup_status")
        sensor = BackrestPlanSensor(coord, "daily-home", desc)
        assert sensor.native_value == OP_STATUS_SUCCESS

    def test_last_backup_status_error(self):
        from custom_components.backrest.sensor import BackrestPlanSensor, PLAN_SENSORS

        data = _make_data(plan_status=OP_STATUS_ERROR)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_SENSORS if s.key == "last_backup_status")
        sensor = BackrestPlanSensor(coord, "daily-home", desc)
        assert sensor.native_value == OP_STATUS_ERROR

    def test_backup_duration(self):
        from custom_components.backrest.sensor import BackrestPlanSensor, PLAN_SENSORS

        data = _make_data()
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_SENSORS if s.key == "backup_duration")
        sensor = BackrestPlanSensor(coord, "daily-home", desc)
        assert sensor.native_value == 120

    def test_hours_since_backup_approximately_one(self):
        from custom_components.backrest.sensor import BackrestPlanSensor, PLAN_SENSORS

        data = _make_data(last_backup_hours_ago=1)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_SENSORS if s.key == "hours_since_backup")
        sensor = BackrestPlanSensor(coord, "daily-home", desc)
        hours = sensor.native_value
        assert hours is not None
        assert 0.9 < hours < 1.1, f"Expected ~1h, got {hours}"

    def test_hours_since_backup_none_when_never_backed_up(self):
        from custom_components.backrest.sensor import BackrestPlanSensor, PLAN_SENSORS

        data = _make_data()
        data.plans["daily-home"].last_backup_time = None
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_SENSORS if s.key == "hours_since_backup")
        sensor = BackrestPlanSensor(coord, "daily-home", desc)
        assert sensor.native_value is None

    def test_failure_count_30d(self):
        from custom_components.backrest.sensor import BackrestPlanSensor, PLAN_SENSORS

        data = _make_data(failure_count_30d=3)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_SENSORS if s.key == "failure_count_30d")
        sensor = BackrestPlanSensor(coord, "daily-home", desc)
        assert sensor.native_value == 3

    def test_last_backup_time_extra_attrs(self):
        from custom_components.backrest.sensor import BackrestPlanSensor, PLAN_SENSORS

        data = _make_data(plan_status=OP_STATUS_SUCCESS)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_SENSORS if s.key == "last_backup_time")
        sensor = BackrestPlanSensor(coord, "daily-home", desc)
        attrs = sensor.extra_state_attributes
        assert attrs.get("status") == OP_STATUS_SUCCESS

    def test_sensor_unavailable_when_no_data(self):
        from custom_components.backrest.sensor import BackrestPlanSensor, PLAN_SENSORS

        coord = _make_coordinator(None)
        desc = next(s for s in PLAN_SENSORS if s.key == "last_backup_status")
        sensor = BackrestPlanSensor(coord, "daily-home", desc)
        assert sensor.native_value is None


# ===========================================================================
# BINARY SENSOR TESTS
# ===========================================================================


class TestInstanceBinarySensors:
    def test_connected_true_when_poll_succeeds(self):
        from custom_components.backrest.binary_sensor import (
            BackrestInstanceBinarySensor,
            INSTANCE_BINARY_SENSORS,
        )

        data = _make_data()
        data.last_poll_success = True
        coord = _make_coordinator(data)
        desc = next(s for s in INSTANCE_BINARY_SENSORS if s.key == "connected")
        sensor = BackrestInstanceBinarySensor(coord, desc)
        assert sensor.is_on is True

    def test_connected_false_when_poll_fails(self):
        from custom_components.backrest.binary_sensor import (
            BackrestInstanceBinarySensor,
            INSTANCE_BINARY_SENSORS,
        )

        data = _make_data()
        data.last_poll_success = False
        coord = _make_coordinator(data)
        desc = next(s for s in INSTANCE_BINARY_SENSORS if s.key == "connected")
        sensor = BackrestInstanceBinarySensor(coord, desc)
        assert sensor.is_on is False


class TestPlanBinarySensors:
    def test_is_running_true(self):
        from custom_components.backrest.binary_sensor import (
            BackrestPlanBinarySensor,
            PLAN_BINARY_SENSORS,
        )

        data = _make_data(plan_running=True)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_BINARY_SENSORS if s.key == "is_running")
        sensor = BackrestPlanBinarySensor(coord, "daily-home", desc)
        assert sensor.is_on is True

    def test_is_running_false_when_idle(self):
        from custom_components.backrest.binary_sensor import (
            BackrestPlanBinarySensor,
            PLAN_BINARY_SENSORS,
        )

        data = _make_data(plan_running=False)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_BINARY_SENSORS if s.key == "is_running")
        sensor = BackrestPlanBinarySensor(coord, "daily-home", desc)
        assert sensor.is_on is False

    def test_last_backup_failed_true_on_error(self):
        from custom_components.backrest.binary_sensor import (
            BackrestPlanBinarySensor,
            PLAN_BINARY_SENSORS,
        )

        data = _make_data(plan_status=OP_STATUS_ERROR)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_BINARY_SENSORS if s.key == "last_backup_failed")
        sensor = BackrestPlanBinarySensor(coord, "daily-home", desc)
        assert sensor.is_on is True

    def test_last_backup_failed_true_on_warning(self):
        from custom_components.backrest.binary_sensor import (
            BackrestPlanBinarySensor,
            PLAN_BINARY_SENSORS,
        )

        data = _make_data(plan_status=OP_STATUS_WARNING)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_BINARY_SENSORS if s.key == "last_backup_failed")
        sensor = BackrestPlanBinarySensor(coord, "daily-home", desc)
        assert sensor.is_on is True

    def test_last_backup_failed_false_on_success(self):
        from custom_components.backrest.binary_sensor import (
            BackrestPlanBinarySensor,
            PLAN_BINARY_SENSORS,
        )

        data = _make_data(plan_status=OP_STATUS_SUCCESS)
        coord = _make_coordinator(data)
        desc = next(s for s in PLAN_BINARY_SENSORS if s.key == "last_backup_failed")
        sensor = BackrestPlanBinarySensor(coord, "daily-home", desc)
        assert sensor.is_on is False


class TestBackupStaleSensor:
    def test_stale_when_backup_older_than_threshold(self):
        from custom_components.backrest.binary_sensor import BackrestBackupStaleSensor

        data = _make_data(last_backup_hours_ago=30)  # 30h ago, threshold=25h
        coord = _make_coordinator(data)
        coord.config_entry.options = {}
        sensor = BackrestBackupStaleSensor(coord, "daily-home")
        assert sensor.is_on is True

    def test_not_stale_when_backup_recent(self):
        from custom_components.backrest.binary_sensor import BackrestBackupStaleSensor

        data = _make_data(last_backup_hours_ago=1)  # 1h ago
        coord = _make_coordinator(data)
        coord.config_entry.options = {}
        sensor = BackrestBackupStaleSensor(coord, "daily-home")
        assert sensor.is_on is False

    def test_stale_when_never_backed_up(self):
        from custom_components.backrest.binary_sensor import BackrestBackupStaleSensor

        data = _make_data()
        data.plans["daily-home"].last_backup_time = None
        coord = _make_coordinator(data)
        coord.config_entry.options = {}
        sensor = BackrestBackupStaleSensor(coord, "daily-home")
        assert sensor.is_on is True

    def test_custom_threshold_respected(self):
        from custom_components.backrest.binary_sensor import BackrestBackupStaleSensor
        from custom_components.backrest.const import CONF_STALE_THRESHOLDS

        data = _make_data(last_backup_hours_ago=5)
        coord = _make_coordinator(data)
        # Set a low threshold of 3h — 5h since backup → stale
        coord.config_entry.options = {
            CONF_STALE_THRESHOLDS: {"daily-home": 3}
        }
        sensor = BackrestBackupStaleSensor(coord, "daily-home")
        assert sensor.is_on is True

    def test_threshold_in_extra_state_attributes(self):
        from custom_components.backrest.binary_sensor import BackrestBackupStaleSensor

        data = _make_data()
        coord = _make_coordinator(data)
        coord.config_entry.options = {}
        sensor = BackrestBackupStaleSensor(coord, "daily-home")
        attrs = sensor.extra_state_attributes
        assert "threshold_hours" in attrs
        assert attrs["threshold_hours"] == DEFAULT_STALE_THRESHOLD_HOURS


# ===========================================================================
# BUTTON TESTS
# ===========================================================================


class TestPlanButtons:
    async def test_trigger_backup_calls_api(self):
        from custom_components.backrest.button import (
            BackrestPlanButton,
            PLAN_BUTTONS,
        )

        data = _make_data()
        coord = _make_coordinator(data)
        coord.async_request_refresh = AsyncMock()

        api = AsyncMock()
        api.trigger_backup = AsyncMock(return_value={})

        desc = next(b for b in PLAN_BUTTONS if b.key == "trigger_backup")
        button = BackrestPlanButton(coord, "daily-home", desc, api)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        api.trigger_backup.assert_called_once_with("daily-home")
        coord.async_request_refresh.assert_called_once()

    async def test_forget_snapshots_calls_api(self):
        from custom_components.backrest.button import (
            BackrestPlanButton,
            PLAN_BUTTONS,
        )

        data = _make_data()
        coord = _make_coordinator(data)
        coord.async_request_refresh = AsyncMock()
        api = AsyncMock()

        desc = next(b for b in PLAN_BUTTONS if b.key == "forget_snapshots")
        button = BackrestPlanButton(coord, "daily-home", desc, api)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        api.forget_snapshots.assert_called_once()

    async def test_button_error_does_not_raise(self):
        """API errors should be logged, not propagated to HA."""
        from custom_components.backrest.button import (
            BackrestPlanButton,
            PLAN_BUTTONS,
        )

        data = _make_data()
        coord = _make_coordinator(data)
        coord.async_request_refresh = AsyncMock()
        api = AsyncMock()
        api.trigger_backup = AsyncMock(side_effect=Exception("network error"))

        desc = next(b for b in PLAN_BUTTONS if b.key == "trigger_backup")
        button = BackrestPlanButton(coord, "daily-home", desc, api)

        # Should not raise
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        # No refresh on error
        coord.async_request_refresh.assert_not_called()


class TestRepoButtons:
    async def test_run_prune_calls_api(self):
        from custom_components.backrest.button import BackrestRepoButton, REPO_BUTTONS

        data = _make_data()
        coord = _make_coordinator(data)
        coord.async_request_refresh = AsyncMock()
        api = AsyncMock()
        api.run_prune = AsyncMock(return_value={})

        desc = next(b for b in REPO_BUTTONS if b.key == "run_prune")
        button = BackrestRepoButton(coord, "s3-main", desc, api)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        api.run_prune.assert_called_once_with("s3-main")

    async def test_unlock_repo_calls_api(self):
        from custom_components.backrest.button import BackrestRepoButton, REPO_BUTTONS

        data = _make_data()
        coord = _make_coordinator(data)
        coord.async_request_refresh = AsyncMock()
        api = AsyncMock()

        desc = next(b for b in REPO_BUTTONS if b.key == "unlock_repo")
        button = BackrestRepoButton(coord, "s3-main", desc, api)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        api.unlock_repo.assert_called_once_with("s3-main")
