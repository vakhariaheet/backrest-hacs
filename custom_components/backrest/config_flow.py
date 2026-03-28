"""Config flow for the Backrest integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import BackrestApiClient
from .auth import BackrestAuthError, BackrestAuthManager, BackrestCannotConnectError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STALE_THRESHOLDS,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_THRESHOLD_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Re-export these so HA can resolve them from the integration's config entry
CONF_HOST = CONF_HOST  # "host"
CONF_PORT = CONF_PORT  # "port"
CONF_USERNAME = CONF_USERNAME  # "username"
CONF_PASSWORD = CONF_PASSWORD  # "password"


async def _validate_connection(
    hass: HomeAssistant,
    host: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    verify_ssl: bool = True,
) -> tuple[str | None, dict[str, str]]:
    """Try to connect to Backrest and return (instance_name, errors).

    Returns:
        (instance_name, {}) on success
        (None, {"base": "error_key"}) on failure
    """
    scheme = "https" if use_ssl else "http"
    base_url = f"{scheme}://{host}:{port}"
    session = async_get_clientsession(hass)

    auth = BackrestAuthManager(
        base_url=base_url,
        username=username,
        password=password,
        session=session,
        verify_ssl=verify_ssl,
    )

    try:
        await auth.login()
    except BackrestAuthError:
        return None, {"base": "invalid_auth"}
    except BackrestCannotConnectError:
        return None, {"base": "cannot_connect"}

    api = BackrestApiClient(
        base_url=base_url,
        auth_manager=auth,
        session=session,
        verify_ssl=verify_ssl,
    )

    try:
        config = await api.get_config()
    except BackrestCannotConnectError:
        return None, {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        return None, {"base": "unknown"}

    instance_name = config.get("instance", host)
    return instance_name, {}


class BackrestConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup config flow for Backrest."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    # ------------------------------------------------------------------
    # Step 1: User fills in host/port/credentials
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
            use_ssl = user_input.get(CONF_USE_SSL, False)
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "")

            instance_name, errors = await _validate_connection(
                self.hass, host, port, use_ssl, username, password, verify_ssl
            )

            if not errors:
                # Prevent duplicate entries for the same Backrest instance
                unique_id = f"{host}:{port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Backrest ({instance_name or host})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_USE_SSL: use_ssl,
                        CONF_VERIFY_SSL: verify_ssl,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=65535, step=1, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(CONF_USE_SSL, default=False): BooleanSelector(),
                    vol.Optional(CONF_VERIFY_SSL, default=True): BooleanSelector(),
                    vol.Optional(CONF_USERNAME, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_PASSWORD, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Re-auth flow (triggered automatically on 401)
    # ------------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when token is invalid."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication with new credentials."""
        errors: dict[str, str] = {}

        if user_input is not None and self._reauth_entry:
            host = self._reauth_entry.data[CONF_HOST]
            port = self._reauth_entry.data[CONF_PORT]
            use_ssl = self._reauth_entry.data.get(CONF_USE_SSL, False)
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "")

            _, errors = await _validate_connection(
                self.hass, host, port, use_ssl, username, password
            )

            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_USERNAME, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "host": self._reauth_entry.data.get(CONF_HOST, "")
                if self._reauth_entry
                else ""
            },
        )

    # ------------------------------------------------------------------
    # Reconfigure flow (change host/port without losing config entry)
    # ------------------------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow reconfiguring host/port/SSL."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
            use_ssl = user_input.get(CONF_USE_SSL, False)
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            username = reconfigure_entry.data.get(CONF_USERNAME, "")
            password = reconfigure_entry.data.get(CONF_PASSWORD, "")

            instance_name, errors = await _validate_connection(
                self.hass, host, port, use_ssl, username, password, verify_ssl
            )

            if not errors:
                new_unique_id = f"{host}:{port}"
                await self.async_set_unique_id(new_unique_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_PORT: port}
                )
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_USE_SSL: use_ssl,
                        CONF_VERIFY_SSL: verify_ssl,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=reconfigure_entry.data.get(CONF_HOST, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(
                        CONF_PORT,
                        default=reconfigure_entry.data.get(CONF_PORT, DEFAULT_PORT),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=65535, step=1, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(
                        CONF_USE_SSL,
                        default=reconfigure_entry.data.get(CONF_USE_SSL, False),
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_VERIFY_SSL,
                        default=reconfigure_entry.data.get(CONF_VERIFY_SSL, True),
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Options flow
    # ------------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return BackrestOptionsFlow(config_entry)


class BackrestOptionsFlow(OptionsFlow):
    """Handle options for an existing Backrest config entry."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Backrest options (scan interval, stale threshold)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_scan = self._config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_stale = self._config_entry.options.get(
            "default_stale_threshold_hours", DEFAULT_STALE_THRESHOLD_HOURS
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_scan
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=10,
                            max=3600,
                            step=10,
                            unit_of_measurement="seconds",
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        "default_stale_threshold_hours", default=current_stale
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=720,
                            step=1,
                            unit_of_measurement="hours",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
