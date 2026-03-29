"""DataUpdateCoordinator for the Backrest integration."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BackrestApiClient, BackrestServerError
from .auth import BackrestAuthError, BackrestCannotConnectError
from .const import (
    DOMAIN,
    EVENT_BACKUP_COMPLETED,
    EVENT_BACKUP_FAILED,
    EVENT_BACKUP_STARTED,
    EVENT_CONNECTION_LOST,
    EVENT_CONNECTION_RESTORED,
    OP_STATUSES_FAILED,
    OP_STATUSES_FINISHED,
    OP_STATUSES_RUNNING,
    OP_STATUS_INPROGRESS,
    OP_STATUS_PENDING,
    OP_STATUS_SUCCESS,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RepoData:
    """Represents a single Backrest repository's current state."""

    id: str
    uri: str
    guid: str = ""


@dataclass
class PlanData:
    """Represents a single Backrest plan's current state."""

    id: str
    repo_id: str
    schedule_cron: Optional[str] = None  # raw cron string if available
    last_backup_time: Optional[datetime] = None
    last_backup_status: Optional[str] = None
    last_backup_duration_seconds: Optional[float] = None
    last_backup_bytes_added: Optional[int] = None
    last_backup_files_new: Optional[int] = None
    bytes_added_30d: int = 0
    backup_count_30d: int = 0
    failure_count_30d: int = 0
    is_running: bool = False
    active_operation_id: Optional[int] = None


@dataclass
class BackrestData:
    """Full snapshot of data fetched from one Backrest instance."""

    instance_name: str = "Backrest"
    config_version: int = 0
    repos: dict[str, RepoData] = field(default_factory=dict)
    plans: dict[str, PlanData] = field(default_factory=dict)
    active_operation_ids: list[int] = field(default_factory=list)
    last_poll_success: bool = True


# ---------------------------------------------------------------------------
# Helper: parse operations into plan-level summary
# ---------------------------------------------------------------------------


def _ms_to_datetime(ms: int | str | None) -> Optional[datetime]:
    """Convert unix milliseconds (int or string) to an aware UTC datetime."""
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def _parse_operations(
    operations: list[dict],
    plans: dict[str, PlanData],
) -> None:
    """Extract last-backup info and running state from a list of operations."""
    # We process operations newest-first so the first hit per plan is the latest
    seen_plan_last: set[str] = set()

    for op in sorted(
        operations,
        key=lambda o: int(o.get("unixTimeStartMs") or 0),
        reverse=True,
    ):
        plan_id = op.get("planId", "")
        status = op.get("status", "")
        op_id = op.get("id")

        if not plan_id or plan_id not in plans:
            continue

        plan = plans[plan_id]

        # Mark running ops (any op type that is actively in-progress)
        if status in OP_STATUSES_RUNNING:
            plan.is_running = True
            if op_id:
                plan.active_operation_id = int(op_id)

        # Record the last completed *backup* operation (once per plan).
        # Skip non-backup ops (operationForget, operationIndexSnapshot, etc.)
        # and ops with no actual backup data (e.g., empty PENDING operationBackup).
        op_backup = op.get("operationBackup")
        if op_backup is None:
            continue  # not a backup op at all

        last_status_data = op_backup.get("lastStatus", {})
        if plan_id not in seen_plan_last and status in OP_STATUSES_FINISHED and last_status_data:
            seen_plan_last.add(plan_id)
            plan.last_backup_status = status
            plan.last_backup_time = _ms_to_datetime(op.get("unixTimeStartMs"))

            start_ms = op.get("unixTimeStartMs", 0)
            end_ms = op.get("unixTimeEndMs", 0)
            if start_ms and end_ms:
                plan.last_backup_duration_seconds = (int(end_ms) - int(start_ms)) / 1000

            summary = last_status_data.get("summary", {})
            if summary is not None:
                plan.last_backup_files_new = int(summary.get("filesNew") or 0)
                plan.last_backup_bytes_added = int(summary.get("dataAdded") or 0)


def _parse_dashboard(
    dashboard: dict,
    repos: dict[str, RepoData],
    plans: dict[str, PlanData],
) -> None:
    """Extract stats from the SummaryDashboard response."""
    for summary in dashboard.get("planSummaries", []):
        plan_id = summary.get("id", "")
        if plan_id in plans:
            plan = plans[plan_id]
            plan.bytes_added_30d = int(summary.get("bytesAddedLast30days", 0) or 0)
            plan.backup_count_30d = int(summary.get("backupsSuccessLast30days", 0) or 0)
            plan.failure_count_30d = int(summary.get("backupsFailedLast30days", 0) or 0)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class BackrestCoordinator(DataUpdateCoordinator[BackrestData]):
    """Coordinator that polls the Backrest API and manages entity state."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: BackrestApiClient,
        entry: ConfigEntry,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._api = api
        self._entry = entry

        # State tracking for event diffing across poll cycles
        self._prev_plan_running: dict[str, bool] = {}
        self._prev_plan_status: dict[str, Optional[str]] = {}
        # None = no successful poll yet; True = connected; False = was connected, now lost
        self._prev_connected: Optional[bool] = None

    # ------------------------------------------------------------------
    # Core polling method
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> BackrestData:
        """Fetch all data from Backrest in parallel and return BackrestData."""
        try:
            # Step 1: fetch config and dashboard in parallel
            config_resp, dashboard_resp = await asyncio.gather(
                self._api.get_config(),
                self._api.get_summary_dashboard(),
                return_exceptions=False,
            )
        except BackrestAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Backrest authentication failed: {err}"
            ) from err
        except BackrestCannotConnectError as err:
            self._fire_connection_lost()
            raise UpdateFailed(f"Cannot connect to Backrest: {err}") from err
        except BackrestServerError as err:
            raise UpdateFailed(f"Backrest server error: {err}") from err

        # Build the data model from raw API responses
        data = BackrestData(
            instance_name=config_resp.get("instance", "Backrest"),
            config_version=int(config_resp.get("modno", 0)),
        )

        # Repos
        for repo_raw in config_resp.get("repos", []):
            repo_id = repo_raw.get("id", "")
            if repo_id:
                data.repos[repo_id] = RepoData(
                    id=repo_id,
                    uri=repo_raw.get("uri", ""),
                    guid=repo_raw.get("guid", ""),
                )

        # Plans
        for plan_raw in config_resp.get("plans", []):
            plan_id = plan_raw.get("id", "")
            repo_id = plan_raw.get("repo", "")
            if plan_id:
                # Try to extract cron from schedule
                cron = None
                schedule = plan_raw.get("schedule", {})
                if isinstance(schedule, dict):
                    cron = schedule.get("cron")

                data.plans[plan_id] = PlanData(
                    id=plan_id,
                    repo_id=repo_id,
                    schedule_cron=cron,
                )

        # Step 2: fetch operations per-repo in parallel (Backrest requires a
        # non-empty selector — sending an empty body causes a 500 "empty selector")
        all_operations: list[dict] = []
        if data.repos:
            try:
                op_results = await asyncio.gather(
                    *[
                        self._api.get_operations(repo_id=repo_id, only_last=100)
                        for repo_id in data.repos
                    ],
                    return_exceptions=False,
                )
                for result in op_results:
                    all_operations.extend(result.get("operations", []))
            except BackrestAuthError as err:
                raise ConfigEntryAuthFailed(
                    f"Backrest authentication failed: {err}"
                ) from err
            except BackrestCannotConnectError as err:
                self._fire_connection_lost()
                raise UpdateFailed(f"Cannot connect to Backrest: {err}") from err
            except BackrestServerError as err:
                raise UpdateFailed(f"Backrest server error: {err}") from err

        # Parse operations into plan data
        operations = all_operations
        _parse_operations(operations, data.plans)

        # Active operations
        data.active_operation_ids = [
            int(op["id"])
            for op in operations
            if op.get("status") in OP_STATUSES_RUNNING and op.get("id")
        ]

        # Parse dashboard stats
        _LOGGER.debug("Dashboard response: %s", dashboard_resp)
        if operations:
            _LOGGER.debug("Sample operation fields: %s", operations[0])
        _parse_dashboard(dashboard_resp, data.repos, data.plans)

        for plan_id, plan in data.plans.items():
            _LOGGER.debug("Parsed plan %s: %s", plan_id, plan)

        data.last_poll_success = True

        # Fire HA events based on state transitions
        self._fire_transition_events(data)

        # Track previous state for next cycle
        self._prev_connected = True
        for plan_id, plan in data.plans.items():
            self._prev_plan_running[plan_id] = plan.is_running
            self._prev_plan_status[plan_id] = plan.last_backup_status

        return data

    # ------------------------------------------------------------------
    # HA event firing
    # ------------------------------------------------------------------

    def _fire_connection_lost(self) -> None:
        """Fire a connection lost event (only once per outage)."""
        if self._prev_connected is True:
            self.hass.bus.async_fire(
                EVENT_CONNECTION_LOST,
                {
                    "entry_id": self._entry.entry_id,
                    "host": self._entry.data.get("host", ""),
                },
            )
            self._prev_connected = False

    def _fire_transition_events(self, data: BackrestData) -> None:
        """Diff current vs previous plan states and fire HA events."""
        # Connection restored (only if we previously lost it, not on first-ever poll)
        if self._prev_connected is False:
            self.hass.bus.async_fire(
                EVENT_CONNECTION_RESTORED,
                {
                    "entry_id": self._entry.entry_id,
                    "host": self._entry.data.get("host", ""),
                },
            )

        for plan_id, plan in data.plans.items():
            prev_running = self._prev_plan_running.get(plan_id, False)
            prev_status = self._prev_plan_status.get(plan_id)

            # Backup just started
            if plan.is_running and not prev_running:
                self.hass.bus.async_fire(
                    EVENT_BACKUP_STARTED,
                    {
                        "entry_id": self._entry.entry_id,
                        "plan_id": plan_id,
                        "operation_id": plan.active_operation_id,
                    },
                )

            # Backup just completed
            if not plan.is_running and prev_running:
                payload: dict[str, Any] = {
                    "entry_id": self._entry.entry_id,
                    "plan_id": plan_id,
                    "status": plan.last_backup_status,
                    "duration_seconds": plan.last_backup_duration_seconds,
                    "bytes_added": plan.last_backup_bytes_added,
                }
                self.hass.bus.async_fire(EVENT_BACKUP_COMPLETED, payload)

                if plan.last_backup_status in OP_STATUSES_FAILED:
                    self.hass.bus.async_fire(EVENT_BACKUP_FAILED, payload)
