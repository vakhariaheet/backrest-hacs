"""HA service registrations for the Backrest integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_STALE_THRESHOLDS,
    DOMAIN,
    SERVICE_CANCEL_OPERATION,
    SERVICE_FORGET_SNAPSHOTS,
    SERVICE_LIST_SNAPSHOTS,
    SERVICE_RUN_REPO_TASK,
    SERVICE_SET_STALE_THRESHOLD,
    SERVICE_TRIGGER_BACKUP,
    TASK_CHECK,
    TASK_PRUNE,
    TASK_STATS,
    TASK_UNLOCK,
)

_LOGGER = logging.getLogger(__name__)

# Track whether services have been registered (only register once across entries)
_SERVICES_REGISTERED = False


def _get_runtime(hass: HomeAssistant, entry_id: str):
    """Retrieve the runtime data for a config entry by ID."""
    from homeassistant.config_entries import ConfigEntryState

    entries = hass.config_entries.async_entries(DOMAIN)
    for entry in entries:
        if entry.entry_id == entry_id:
            if hasattr(entry, "runtime_data"):
                return entry.runtime_data
    raise vol.Invalid(f"No active Backrest entry found with id '{entry_id}'")


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register all Backrest HA services (idempotent)."""
    global _SERVICES_REGISTERED
    if _SERVICES_REGISTERED:
        return

    # ------------------------------------------------------------------
    # backrest.trigger_backup
    # ------------------------------------------------------------------
    async def handle_trigger_backup(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        plan_id = call.data["plan_id"]
        runtime = _get_runtime(hass, entry_id)
        _LOGGER.info("Service: triggering backup for plan '%s'", plan_id)
        await runtime.api.trigger_backup(plan_id)
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER_BACKUP,
        handle_trigger_backup,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("plan_id"): cv.string,
            }
        ),
    )

    # ------------------------------------------------------------------
    # backrest.cancel_operation
    # ------------------------------------------------------------------
    async def handle_cancel_operation(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        operation_id = int(call.data["operation_id"])
        runtime = _get_runtime(hass, entry_id)
        _LOGGER.info("Service: cancelling operation %d", operation_id)
        await runtime.api.cancel_operation(operation_id)
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_OPERATION,
        handle_cancel_operation,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("operation_id"): vol.Coerce(int),
            }
        ),
    )

    # ------------------------------------------------------------------
    # backrest.run_repo_task
    # ------------------------------------------------------------------
    async def handle_run_repo_task(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        repo_id = call.data["repo_id"]
        task = call.data["task"].upper()
        if not task.startswith("TASK_"):
            task = f"TASK_{task}"
        runtime = _get_runtime(hass, entry_id)
        _LOGGER.info("Service: running task '%s' on repo '%s'", task, repo_id)
        await runtime.api.do_repo_task(repo_id, task)
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_REPO_TASK,
        handle_run_repo_task,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("repo_id"): cv.string,
                vol.Required("task"): vol.In(
                    ["prune", "check", "stats", "unlock",
                     TASK_PRUNE, TASK_CHECK, TASK_STATS, TASK_UNLOCK]
                ),
            }
        ),
    )

    # ------------------------------------------------------------------
    # backrest.forget_snapshots
    # ------------------------------------------------------------------
    async def handle_forget_snapshots(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        plan_id = call.data["plan_id"]
        repo_id = call.data.get("repo_id", "")
        runtime = _get_runtime(hass, entry_id)
        _LOGGER.info("Service: forget snapshots for plan '%s'", plan_id)
        await runtime.api.forget_snapshots(plan_id, repo_id)
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORGET_SNAPSHOTS,
        handle_forget_snapshots,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("plan_id"): cv.string,
                vol.Optional("repo_id", default=""): cv.string,
            }
        ),
    )

    # ------------------------------------------------------------------
    # backrest.list_snapshots  (returns data)
    # ------------------------------------------------------------------
    async def handle_list_snapshots(call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data["config_entry_id"]
        repo_id = call.data["repo_id"]
        plan_id = call.data.get("plan_id")
        tag = call.data.get("tag")
        runtime = _get_runtime(hass, entry_id)
        _LOGGER.info("Service: listing snapshots for repo '%s'", repo_id)
        result = await runtime.api.list_snapshots(repo_id, plan_id, tag)
        snapshots = result.get("snapshots", [])
        limit = int(call.data.get("limit", 10))
        return {"snapshots": snapshots[:limit], "total": len(snapshots)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_SNAPSHOTS,
        handle_list_snapshots,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("repo_id"): cv.string,
                vol.Optional("plan_id"): cv.string,
                vol.Optional("tag"): cv.string,
                vol.Optional("limit", default=10): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=500)
                ),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    # ------------------------------------------------------------------
    # backrest.set_stale_threshold
    # ------------------------------------------------------------------
    async def handle_set_stale_threshold(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        plan_id = call.data["plan_id"]
        threshold_hours = int(call.data["threshold_hours"])

        entries = hass.config_entries.async_entries(DOMAIN)
        for entry in entries:
            if entry.entry_id == entry_id:
                current_thresholds: dict = dict(
                    entry.options.get(CONF_STALE_THRESHOLDS, {})
                )
                current_thresholds[plan_id] = threshold_hours
                new_options = {**entry.options, CONF_STALE_THRESHOLDS: current_thresholds}
                hass.config_entries.async_update_entry(entry, options=new_options)
                _LOGGER.info(
                    "Updated stale threshold for plan '%s' to %dh",
                    plan_id,
                    threshold_hours,
                )
                return
        raise vol.Invalid(f"No Backrest entry found with id '{entry_id}'")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_STALE_THRESHOLD,
        handle_set_stale_threshold,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("plan_id"): cv.string,
                vol.Required("threshold_hours"): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=720)
                ),
            }
        ),
    )

    _SERVICES_REGISTERED = True
    _LOGGER.debug("Backrest services registered")


async def async_unload_services(hass: HomeAssistant) -> None:
    """Remove Backrest services when all entries are unloaded."""
    global _SERVICES_REGISTERED

    # Only unregister if there are no more active Backrest entries
    remaining = hass.config_entries.async_entries(DOMAIN)
    if remaining:
        return

    for service in [
        SERVICE_TRIGGER_BACKUP,
        SERVICE_CANCEL_OPERATION,
        SERVICE_RUN_REPO_TASK,
        SERVICE_FORGET_SNAPSHOTS,
        SERVICE_LIST_SNAPSHOTS,
        SERVICE_SET_STALE_THRESHOLD,
    ]:
        hass.services.async_remove(DOMAIN, service)

    _SERVICES_REGISTERED = False
    _LOGGER.debug("Backrest services unregistered")
