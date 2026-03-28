"""Binary sensor entities for the Backrest integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_STALE_THRESHOLDS,
    DEFAULT_STALE_THRESHOLD_HOURS,
    KEY_BACKUP_STALE,
    KEY_CONNECTED,
    KEY_IS_RUNNING,
    KEY_LAST_BACKUP_FAILED,
    OP_STATUSES_FAILED,
)
from .coordinator import BackrestCoordinator, BackrestData, PlanData
from .entity import BackrestInstanceEntity, BackrestPlanEntity

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed description helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class BackrestInstanceBinarySensorDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[BackrestData], bool] = lambda _: False


@dataclass(frozen=True, kw_only=True)
class BackrestPlanBinarySensorDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[PlanData], bool] = lambda _: False


# ---------------------------------------------------------------------------
# Instance-level binary sensors
# ---------------------------------------------------------------------------

INSTANCE_BINARY_SENSORS: tuple[BackrestInstanceBinarySensorDescription, ...] = (
    BackrestInstanceBinarySensorDescription(
        key=KEY_CONNECTED,
        translation_key=KEY_CONNECTED,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: d.last_poll_success,
    ),
)

# ---------------------------------------------------------------------------
# Per-plan binary sensors
# ---------------------------------------------------------------------------

PLAN_BINARY_SENSORS: tuple[BackrestPlanBinarySensorDescription, ...] = (
    BackrestPlanBinarySensorDescription(
        key=KEY_IS_RUNNING,
        translation_key=KEY_IS_RUNNING,
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:backup-restore",
        is_on_fn=lambda p: p.is_running,
    ),
    BackrestPlanBinarySensorDescription(
        key=KEY_LAST_BACKUP_FAILED,
        translation_key=KEY_LAST_BACKUP_FAILED,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle",
        is_on_fn=lambda p: p.last_backup_status in OP_STATUSES_FAILED
        if p.last_backup_status
        else False,
    ),
    # KEY_BACKUP_STALE is handled by a custom class below (needs threshold from options)
)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------


class BackrestInstanceBinarySensor(BackrestInstanceEntity, BinarySensorEntity):
    """A binary sensor for an instance-level state."""

    entity_description: BackrestInstanceBinarySensorDescription

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        description: BackrestInstanceBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        return self.entity_description.is_on_fn(self.coordinator.data)


class BackrestPlanBinarySensor(BackrestPlanEntity, BinarySensorEntity):
    """A binary sensor for a per-plan state."""

    entity_description: BackrestPlanBinarySensorDescription

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        plan_id: str,
        description: BackrestPlanBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, plan_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        plan = self.coordinator.data.plans.get(self._plan_id)
        if plan is None:
            return False
        return self.entity_description.is_on_fn(plan)


class BackrestBackupStaleSensor(BackrestPlanEntity, BinarySensorEntity):
    """Binary sensor that is ON when the last backup is older than the threshold."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-alert-outline"
    _attr_translation_key = KEY_BACKUP_STALE

    def __init__(self, coordinator: BackrestCoordinator, plan_id: str) -> None:
        super().__init__(coordinator, plan_id, KEY_BACKUP_STALE)
        self._plan_id = plan_id

    def _get_threshold_hours(self) -> float:
        """Return the configured stale threshold for this plan."""
        options = self.coordinator.config_entry.options
        thresholds: dict = options.get(CONF_STALE_THRESHOLDS, {})
        return float(
            thresholds.get(
                self._plan_id,
                options.get("default_stale_threshold_hours", DEFAULT_STALE_THRESHOLD_HOURS),
            )
        )

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        plan = self.coordinator.data.plans.get(self._plan_id)
        if plan is None or plan.last_backup_time is None:
            # Never backed up → stale
            return True

        from datetime import datetime, timezone

        hours_since = (
            datetime.now(timezone.utc) - plan.last_backup_time
        ).total_seconds() / 3600
        return hours_since > self._get_threshold_hours()

    @property
    def extra_state_attributes(self) -> dict:
        return {"threshold_hours": self._get_threshold_hours()}


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Backrest binary sensors from a config entry."""
    from . import BackrestRuntimeData

    runtime: BackrestRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator

    entities: list[BinarySensorEntity] = []

    # Instance binary sensors
    for desc in INSTANCE_BINARY_SENSORS:
        entities.append(BackrestInstanceBinarySensor(coordinator, desc))

    # Plan binary sensors
    for plan_id in coordinator.data.plans:
        for desc in PLAN_BINARY_SENSORS:
            entities.append(BackrestPlanBinarySensor(coordinator, plan_id, desc))
        # The stale sensor is special — one per plan
        entities.append(BackrestBackupStaleSensor(coordinator, plan_id))

    async_add_entities(entities)
