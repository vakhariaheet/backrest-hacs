"""Backrest Backup Manager integration for Home Assistant."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BackrestApiClient
from .auth import BackrestAuthError, BackrestAuthManager, BackrestCannotConnectError
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    RUNTIME_DATA_API,
    RUNTIME_DATA_AUTH,
    RUNTIME_DATA_COORDINATOR,
)
from .coordinator import BackrestCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)


@dataclass
class BackrestRuntimeData:
    """Runtime data stored in hass.data[DOMAIN][entry_id]."""

    coordinator: BackrestCoordinator
    api: BackrestApiClient
    auth: BackrestAuthManager


type BackrestConfigEntry = ConfigEntry[BackrestRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: BackrestConfigEntry) -> bool:
    """Set up Backrest from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    use_ssl = entry.data.get(CONF_USE_SSL, False)
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    username = entry.data.get(CONF_USERNAME, "")
    password = entry.data.get(CONF_PASSWORD, "")
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    scheme = "https" if use_ssl else "http"
    base_url = f"{scheme}://{host}:{port}"

    session = async_get_clientsession(hass)

    auth_manager = BackrestAuthManager(
        base_url=base_url,
        username=username,
        password=password,
        session=session,
        verify_ssl=verify_ssl,
    )

    # Validate credentials on setup
    try:
        await auth_manager.login()
    except BackrestAuthError as err:
        raise ConfigEntryAuthFailed(f"Invalid Backrest credentials: {err}") from err
    except BackrestCannotConnectError as err:
        raise ConfigEntryNotReady(f"Cannot connect to Backrest: {err}") from err

    api = BackrestApiClient(
        base_url=base_url,
        auth_manager=auth_manager,
        session=session,
        verify_ssl=verify_ssl,
    )

    coordinator = BackrestCoordinator(
        hass=hass,
        api=api,
        entry=entry,
        scan_interval=scan_interval,
    )

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = BackrestRuntimeData(
        coordinator=coordinator,
        api=api,
        auth=auth_manager,
    )

    # Forward to all platforms (sensor, binary_sensor, button)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register HA services (trigger_backup, cancel_operation, etc.)
    await async_setup_services(hass)

    # Reload if options change (e.g., scan interval, stale thresholds)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BackrestConfigEntry) -> bool:
    """Unload a Backrest config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Only remove services when the last Backrest entry is unloaded
        remaining = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining:
            await async_unload_services(hass)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: BackrestConfigEntry) -> None:
    """Handle removal of a config entry (cleanup if needed)."""
    _LOGGER.debug("Backrest config entry removed: %s", entry.entry_id)


async def _async_update_listener(
    hass: HomeAssistant, entry: BackrestConfigEntry
) -> None:
    """Reload the integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
