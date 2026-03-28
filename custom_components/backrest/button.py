"""Button entities for the Backrest integration."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import BackrestApiClient
from .const import (
    KEY_BTN_CHECK,
    KEY_BTN_FORGET,
    KEY_BTN_PRUNE,
    KEY_BTN_STATS,
    KEY_BTN_TRIGGER_BACKUP,
    KEY_BTN_UNLOCK,
)
from .coordinator import BackrestCoordinator
from .entity import BackrestPlanEntity, BackrestRepoEntity

_LOGGER = logging.getLogger(__name__)

# Delay (seconds) after a button press before requesting a coordinator refresh
_POST_PRESS_REFRESH_DELAY = 3


# ---------------------------------------------------------------------------
# Typed description
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class BackrestPlanButtonDescription(ButtonEntityDescription):
    """Button description for plan-level actions."""

    press_fn: Callable[[BackrestApiClient, str], Awaitable] = None  # type: ignore[assignment]


@dataclass(frozen=True, kw_only=True)
class BackrestRepoButtonDescription(ButtonEntityDescription):
    """Button description for repo-level actions."""

    press_fn: Callable[[BackrestApiClient, str], Awaitable] = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Button descriptions
# ---------------------------------------------------------------------------

PLAN_BUTTONS: tuple[BackrestPlanButtonDescription, ...] = (
    BackrestPlanButtonDescription(
        key=KEY_BTN_TRIGGER_BACKUP,
        translation_key=KEY_BTN_TRIGGER_BACKUP,
        icon="mdi:backup-restore",
        press_fn=lambda api, plan_id: api.trigger_backup(plan_id),
    ),
    BackrestPlanButtonDescription(
        key=KEY_BTN_FORGET,
        translation_key=KEY_BTN_FORGET,
        icon="mdi:delete-clock",
        press_fn=lambda api, plan_id: api.forget_snapshots(plan_id, ""),
    ),
)

REPO_BUTTONS: tuple[BackrestRepoButtonDescription, ...] = (
    BackrestRepoButtonDescription(
        key=KEY_BTN_PRUNE,
        translation_key=KEY_BTN_PRUNE,
        icon="mdi:broom",
        press_fn=lambda api, repo_id: api.run_prune(repo_id),
    ),
    BackrestRepoButtonDescription(
        key=KEY_BTN_CHECK,
        translation_key=KEY_BTN_CHECK,
        icon="mdi:shield-check",
        press_fn=lambda api, repo_id: api.run_check(repo_id),
    ),
    BackrestRepoButtonDescription(
        key=KEY_BTN_STATS,
        translation_key=KEY_BTN_STATS,
        icon="mdi:chart-bar",
        press_fn=lambda api, repo_id: api.run_stats(repo_id),
    ),
    BackrestRepoButtonDescription(
        key=KEY_BTN_UNLOCK,
        translation_key=KEY_BTN_UNLOCK,
        icon="mdi:lock-open",
        press_fn=lambda api, repo_id: api.unlock_repo(repo_id),
    ),
)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------


class BackrestPlanButton(BackrestPlanEntity, ButtonEntity):
    """A button that performs an action on a Backrest plan."""

    entity_description: BackrestPlanButtonDescription

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        plan_id: str,
        description: BackrestPlanButtonDescription,
        api: BackrestApiClient,
    ) -> None:
        super().__init__(coordinator, plan_id, description.key)
        self.entity_description = description
        self._api = api

    async def async_press(self) -> None:
        """Execute the button action."""
        _LOGGER.debug(
            "Pressing button %s for plan %s",
            self.entity_description.key,
            self._plan_id,
        )
        try:
            await self.entity_description.press_fn(self._api, self._plan_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Error pressing button %s for plan %s: %s",
                self.entity_description.key,
                self._plan_id,
                err,
            )
            return

        # Give Backrest a moment to register the new operation, then refresh
        await asyncio.sleep(_POST_PRESS_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()


class BackrestRepoButton(BackrestRepoEntity, ButtonEntity):
    """A button that performs an action on a Backrest repository."""

    entity_description: BackrestRepoButtonDescription

    def __init__(
        self,
        coordinator: BackrestCoordinator,
        repo_id: str,
        description: BackrestRepoButtonDescription,
        api: BackrestApiClient,
    ) -> None:
        super().__init__(coordinator, repo_id, description.key)
        self.entity_description = description
        self._api = api

    async def async_press(self) -> None:
        """Execute the button action."""
        _LOGGER.debug(
            "Pressing button %s for repo %s",
            self.entity_description.key,
            self._repo_id,
        )
        try:
            await self.entity_description.press_fn(self._api, self._repo_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Error pressing button %s for repo %s: %s",
                self.entity_description.key,
                self._repo_id,
                err,
            )
            return

        await asyncio.sleep(_POST_PRESS_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Backrest buttons from a config entry."""
    from . import BackrestRuntimeData

    runtime: BackrestRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator
    api = runtime.api

    entities: list[ButtonEntity] = []

    # Plan buttons
    for plan_id in coordinator.data.plans:
        for desc in PLAN_BUTTONS:
            entities.append(BackrestPlanButton(coordinator, plan_id, desc, api))

    # Repo buttons
    for repo_id in coordinator.data.repos:
        for desc in REPO_BUTTONS:
            entities.append(BackrestRepoButton(coordinator, repo_id, desc, api))

    async_add_entities(entities)
