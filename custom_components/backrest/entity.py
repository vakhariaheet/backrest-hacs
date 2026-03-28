"""Base entity classes for the Backrest integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, plan_device_id, repo_device_id
from .coordinator import BackrestCoordinator


class BackrestEntity(CoordinatorEntity[BackrestCoordinator]):
    """Base class for all Backrest entities.

    Subclasses override _device_info and provide a unique_id.
    All Backrest entities have entity names enabled (no entity name prefix from device).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{unique_id_suffix}"
        )

    @property
    def available(self) -> bool:
        """Mark entities unavailable when the last poll failed."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.last_poll_success
        )


class BackrestInstanceEntity(BackrestEntity):
    """Entity scoped to the Backrest instance (top-level device)."""

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        key: str,
    ) -> None:
        super().__init__(coordinator, f"instance_{key}")

    @property
    def device_info(self) -> DeviceInfo:
        entry = self.coordinator.config_entry
        host = entry.data.get("host", "")
        port = entry.data.get("port", 9898)
        use_ssl = entry.data.get("use_ssl", False)
        scheme = "https" if use_ssl else "http"
        instance_name = (
            self.coordinator.data.instance_name
            if self.coordinator.data
            else "Backrest"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Backrest \u2014 {instance_name}",
            manufacturer="garethgeorge",
            model="Backrest Backup Manager",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"{scheme}://{host}:{port}",
        )


class BackrestRepoEntity(BackrestEntity):
    """Entity scoped to a single Backrest repository."""

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        repo_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, f"repo_{repo_id}_{key}")
        self._repo_id = repo_id

    @property
    def device_info(self) -> DeviceInfo:
        entry = self.coordinator.config_entry
        repo = (
            self.coordinator.data.repos.get(self._repo_id)
            if self.coordinator.data
            else None
        )
        uri = repo.uri if repo else self._repo_id
        return DeviceInfo(
            identifiers={(DOMAIN, repo_device_id(entry.entry_id, self._repo_id))},
            name=f"Backrest Repo: {self._repo_id}",
            manufacturer="garethgeorge",
            model=uri,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._repo_id in (self.coordinator.data.repos if self.coordinator.data else {})
        )


class BackrestPlanEntity(BackrestEntity):
    """Entity scoped to a single Backrest plan."""

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        plan_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, f"plan_{plan_id}_{key}")
        self._plan_id = plan_id

    @property
    def device_info(self) -> DeviceInfo:
        entry = self.coordinator.config_entry
        plan = (
            self.coordinator.data.plans.get(self._plan_id)
            if self.coordinator.data
            else None
        )
        model = f"Plan \u2192 {plan.repo_id}" if plan else "Backrest Plan"
        return DeviceInfo(
            identifiers={(DOMAIN, plan_device_id(entry.entry_id, self._plan_id))},
            name=f"Backrest Plan: {self._plan_id}",
            manufacturer="garethgeorge",
            model=model,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._plan_id in (self.coordinator.data.plans if self.coordinator.data else {})
        )
