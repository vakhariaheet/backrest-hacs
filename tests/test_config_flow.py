"""Tests for config_flow.py — setup wizard, re-auth, reconfigure, options."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

# This fixture (provided by pytest-homeassistant-custom-component) tells HA
# to load integrations from our local custom_components/ folder.
pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

from custom_components.backrest.const import (
    CONF_SCAN_INTERVAL,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from tests.conftest import make_jwt

# Patch target for _validate_connection inside config_flow
VALIDATE_PATCH = "custom_components.backrest.config_flow._validate_connection"
# Prevent real HTTP calls when HA auto-runs async_setup_entry after CREATE_ENTRY
SETUP_PATCH = "custom_components.backrest.async_setup_entry"


# ---------------------------------------------------------------------------
# Helper: simulate a successful validation
# ---------------------------------------------------------------------------


def _valid_patch(instance_name="homelab"):
    """Returns a coroutine mock that simulates a successful connection."""
    return AsyncMock(return_value=(instance_name, {}))


def _invalid_patch(error_key="cannot_connect"):
    """Returns a coroutine mock that simulates a connection failure."""
    return AsyncMock(return_value=(None, {"base": error_key}))


# ---------------------------------------------------------------------------
# Initial setup flow
# ---------------------------------------------------------------------------


class TestUserStep:
    async def test_shows_form_on_first_visit(self, hass: HomeAssistant):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    async def test_successful_setup_creates_entry(self, hass: HomeAssistant):
        with patch(VALIDATE_PATCH, _valid_patch("homelab")), patch(SETUP_PATCH, return_value=True):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    "host": "192.168.1.100",
                    "port": DEFAULT_PORT,
                    CONF_USE_SSL: False,
                    CONF_VERIFY_SSL: True,
                    "username": "admin",
                    "password": "secret",
                },
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Backrest (homelab)"
        assert result["data"]["host"] == "192.168.1.100"
        assert result["data"]["password"] == "secret"
        assert result["data"][CONF_VERIFY_SSL] is True

    async def test_cannot_connect_shows_error(self, hass: HomeAssistant):
        with patch(VALIDATE_PATCH, _invalid_patch("cannot_connect")):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    "host": "badhost",
                    "port": DEFAULT_PORT,
                    CONF_USE_SSL: False,
                    CONF_VERIFY_SSL: True,
                    "username": "",
                    "password": "",
                },
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}

    async def test_invalid_auth_shows_error(self, hass: HomeAssistant):
        with patch(VALIDATE_PATCH, _invalid_patch("invalid_auth")):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    "host": "192.168.1.100",
                    "port": DEFAULT_PORT,
                    CONF_USE_SSL: False,
                    CONF_VERIFY_SSL: True,
                    "username": "wrong",
                    "password": "wrong",
                },
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}

    async def test_duplicate_entry_is_aborted(self, hass: HomeAssistant):
        """Configuring the same host:port twice should abort."""
        with patch(VALIDATE_PATCH, _valid_patch()), patch(SETUP_PATCH, return_value=True):
            result1 = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    "host": "192.168.1.100",
                    "port": DEFAULT_PORT,
                    CONF_USE_SSL: False,
                    CONF_VERIFY_SSL: True,
                    "username": "admin",
                    "password": "secret",
                },
            )
        assert result1["type"] == FlowResultType.CREATE_ENTRY

        # Try to add again
        with patch(VALIDATE_PATCH, _valid_patch()), patch(SETUP_PATCH, return_value=True):
            result2 = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    "host": "192.168.1.100",
                    "port": DEFAULT_PORT,
                    CONF_USE_SSL: False,
                    CONF_VERIFY_SSL: True,
                    "username": "admin",
                    "password": "secret",
                },
            )
        assert result2["type"] == FlowResultType.ABORT
        assert result2["reason"] == "already_configured"

    async def test_verify_ssl_false_stored(self, hass: HomeAssistant):
        """Unchecking verify_ssl should persist False in entry data."""
        with patch(VALIDATE_PATCH, _valid_patch()), patch(SETUP_PATCH, return_value=True):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    "host": "192.168.1.100",
                    "port": DEFAULT_PORT,
                    CONF_USE_SSL: True,
                    CONF_VERIFY_SSL: False,  # self-signed cert
                    "username": "admin",
                    "password": "secret",
                },
            )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_VERIFY_SSL] is False


# ---------------------------------------------------------------------------
# Re-auth flow
# ---------------------------------------------------------------------------


class TestReauthFlow:
    async def _setup_entry(self, hass: HomeAssistant):
        """Helper: create a config entry and return it."""
        with patch(VALIDATE_PATCH, _valid_patch()), patch(SETUP_PATCH, return_value=True):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    "host": "192.168.1.100",
                    "port": DEFAULT_PORT,
                    CONF_USE_SSL: False,
                    CONF_VERIFY_SSL: True,
                    "username": "admin",
                    "password": "oldpassword",
                },
            )
        return hass.config_entries.async_get_entry(result["result"].entry_id)

    async def test_reauth_success_updates_credentials(self, hass: HomeAssistant):
        entry = await self._setup_entry(hass)

        with patch(VALIDATE_PATCH, _valid_patch()), patch(SETUP_PATCH, return_value=True):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_REAUTH,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["step_id"] == "reauth_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={"username": "admin", "password": "newpassword"},
            )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        # Updated password should be saved
        assert entry.data["password"] == "newpassword"

    async def test_reauth_wrong_password_shows_error(self, hass: HomeAssistant):
        entry = await self._setup_entry(hass)

        with patch(VALIDATE_PATCH, _invalid_patch("invalid_auth")):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_REAUTH,
                    "entry_id": entry.entry_id,
                },
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={"username": "admin", "password": "wrongpassword"},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


class TestOptionsFlow:
    async def _setup_entry(self, hass: HomeAssistant):
        with patch(VALIDATE_PATCH, _valid_patch()), patch(SETUP_PATCH, return_value=True):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    "host": "192.168.1.100",
                    "port": DEFAULT_PORT,
                    CONF_USE_SSL: False,
                    CONF_VERIFY_SSL: True,
                    "username": "admin",
                    "password": "secret",
                },
            )
        return hass.config_entries.async_get_entry(result["result"].entry_id)

    async def test_options_flow_shows_form(self, hass: HomeAssistant):
        entry = await self._setup_entry(hass)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

    async def test_options_flow_saves_scan_interval(self, hass: HomeAssistant):
        entry = await self._setup_entry(hass)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_SCAN_INTERVAL: 120,
                "default_stale_threshold_hours": 48,
            },
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_SCAN_INTERVAL] == 120
        assert entry.options["default_stale_threshold_hours"] == 48
