"""Sensor entities for the Backrest integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    KEY_BACKUP_COUNT_30D,
    KEY_BACKUP_DURATION,
    KEY_BYTES_ADDED,
    KEY_BYTES_ADDED_30D,
    KEY_FAILURE_COUNT_30D,
    KEY_FILES_NEW,
    KEY_HOURS_SINCE_BACKUP,
    KEY_LAST_BACKUP_STATUS,
    KEY_LAST_BACKUP_TIME,
    KEY_NEXT_BACKUP,
    KEY_PLAN_COUNT,
    KEY_REPO_COUNT,
    KEY_ACTIVE_OPERATIONS,
)
from .coordinator import BackrestCoordinator, BackrestData, PlanData, RepoData
from .entity import BackrestInstanceEntity, BackrestPlanEntity, BackrestRepoEntity

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed description with a value extractor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class BackrestSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with a value function."""

    value_fn: Callable[[BackrestData], Any] = lambda _: None


@dataclass(frozen=True, kw_only=True)
class BackrestRepoSensorDescription(SensorEntityDescription):
    """Sensor description for per-repo sensors."""

    value_fn: Callable[[RepoData], Any] = lambda _: None


@dataclass(frozen=True, kw_only=True)
class BackrestPlanSensorDescription(SensorEntityDescription):
    """Sensor description for per-plan sensors."""

    value_fn: Callable[[PlanData], Any] = lambda _: None
    extra_attrs_fn: Optional[Callable[[PlanData], dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Instance-level sensor descriptions
# ---------------------------------------------------------------------------

INSTANCE_SENSORS: tuple[BackrestSensorDescription, ...] = (
    BackrestSensorDescription(
        key=KEY_REPO_COUNT,
        translation_key=KEY_REPO_COUNT,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.repos),
    ),
    BackrestSensorDescription(
        key=KEY_PLAN_COUNT,
        translation_key=KEY_PLAN_COUNT,
        icon="mdi:calendar-check",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.plans),
    ),
    BackrestSensorDescription(
        key=KEY_ACTIVE_OPERATIONS,
        translation_key=KEY_ACTIVE_OPERATIONS,
        icon="mdi:backup-restore",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.active_operation_ids),
    ),
)

# ---------------------------------------------------------------------------
# Per-repo sensor descriptions
# ---------------------------------------------------------------------------

REPO_SENSORS: tuple[BackrestRepoSensorDescription, ...] = ()

# ---------------------------------------------------------------------------
# Per-plan sensor descriptions
# ---------------------------------------------------------------------------


def _hours_since(plan: PlanData) -> Optional[float]:
    if plan.last_backup_time is None:
        return None
    delta = datetime.now(timezone.utc) - plan.last_backup_time
    return round(delta.total_seconds() / 3600, 2)


def _next_backup(plan: PlanData) -> Optional[datetime]:
    """Compute the next cron fire time using croniter (if available)."""
    if not plan.schedule_cron:
        return None
    try:
        from croniter import croniter  # noqa: PLC0415

        base = plan.last_backup_time or datetime.now(timezone.utc)
        cron = croniter(plan.schedule_cron, base)
        next_dt = cron.get_next(datetime)
        return next_dt.replace(tzinfo=timezone.utc) if next_dt.tzinfo is None else next_dt
    except Exception:  # noqa: BLE001
        return None


PLAN_SENSORS: tuple[BackrestPlanSensorDescription, ...] = (
    BackrestPlanSensorDescription(
        key=KEY_LAST_BACKUP_TIME,
        translation_key=KEY_LAST_BACKUP_TIME,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check",
        value_fn=lambda p: p.last_backup_time,
        extra_attrs_fn=lambda p: {"status": p.last_backup_status},
    ),
    BackrestPlanSensorDescription(
        key=KEY_LAST_BACKUP_STATUS,
        translation_key=KEY_LAST_BACKUP_STATUS,
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:check-circle",
        options=[
            "STATUS_UNKNOWN",
            "STATUS_PENDING",
            "STATUS_INPROGRESS",
            "STATUS_SUCCESS",
            "STATUS_WARNING",
            "STATUS_ERROR",
            "STATUS_USER_CANCELLED",
            "STATUS_SYSTEM_CANCELLED",
        ],
        value_fn=lambda p: p.last_backup_status,
    ),
    BackrestPlanSensorDescription(
        key=KEY_BACKUP_DURATION,
        translation_key=KEY_BACKUP_DURATION,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer",
        value_fn=lambda p: (
            round(p.last_backup_duration_seconds)
            if p.last_backup_duration_seconds is not None
            else None
        ),
    ),
    BackrestPlanSensorDescription(
        key=KEY_BYTES_ADDED,
        translation_key=KEY_BYTES_ADDED,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: p.last_backup_bytes_added,
    ),
    BackrestPlanSensorDescription(
        key=KEY_FILES_NEW,
        translation_key=KEY_FILES_NEW,
        icon="mdi:file-plus",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: p.last_backup_files_new,
    ),
    BackrestPlanSensorDescription(
        key=KEY_BYTES_ADDED_30D,
        translation_key=KEY_BYTES_ADDED_30D,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.bytes_added_30d,
    ),
    BackrestPlanSensorDescription(
        key=KEY_BACKUP_COUNT_30D,
        translation_key=KEY_BACKUP_COUNT_30D,
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.backup_count_30d,
    ),
    BackrestPlanSensorDescription(
        key=KEY_FAILURE_COUNT_30D,
        translation_key=KEY_FAILURE_COUNT_30D,
        icon="mdi:alert-circle",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: p.failure_count_30d,
    ),
    BackrestPlanSensorDescription(
        key=KEY_NEXT_BACKUP,
        translation_key=KEY_NEXT_BACKUP,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-clock",
        value_fn=_next_backup,
    ),
    BackrestPlanSensorDescription(
        key=KEY_HOURS_SINCE_BACKUP,
        translation_key=KEY_HOURS_SINCE_BACKUP,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-alert",
        value_fn=_hours_since,
    ),
)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------


class BackrestInstanceSensor(BackrestInstanceEntity, SensorEntity):
    """A sensor for an instance-level metric."""

    entity_description: BackrestSensorDescription

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        description: BackrestSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class BackrestRepoSensor(BackrestRepoEntity, SensorEntity):
    """A sensor for a per-repo metric."""

    entity_description: BackrestRepoSensorDescription

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        repo_id: str,
        description: BackrestRepoSensorDescription,
    ) -> None:
        super().__init__(coordinator, repo_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        repo = self.coordinator.data.repos.get(self._repo_id)
        if repo is None:
            return None
        return self.entity_description.value_fn(repo)


class BackrestPlanSensor(BackrestPlanEntity, SensorEntity):
    """A sensor for a per-plan metric."""

    entity_description: BackrestPlanSensorDescription

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        plan_id: str,
        description: BackrestPlanSensorDescription,
    ) -> None:
        super().__init__(coordinator, plan_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        plan = self.coordinator.data.plans.get(self._plan_id)
        if plan is None:
            return None
        return self.entity_description.value_fn(plan)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        plan = self.coordinator.data.plans.get(self._plan_id)
        if plan is None or self.entity_description.extra_attrs_fn is None:
            return {}
        return self.entity_description.extra_attrs_fn(plan)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Backrest sensors from a config entry."""
    from . import BackrestRuntimeData

    runtime: BackrestRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator

    entities: list[SensorEntity] = []

    # Instance sensors
    for desc in INSTANCE_SENSORS:
        entities.append(BackrestInstanceSensor(coordinator, desc))

    # Repo sensors — one set per repo
    for repo_id in coordinator.data.repos:
        for desc in REPO_SENSORS:
            entities.append(BackrestRepoSensor(coordinator, repo_id, desc))

    # Plan sensors — one set per plan
    for plan_id in coordinator.data.plans:
        for desc in PLAN_SENSORS:
            entities.append(BackrestPlanSensor(coordinator, plan_id, desc))

    async_add_entities(entities)
