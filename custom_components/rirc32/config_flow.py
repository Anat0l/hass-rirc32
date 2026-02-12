"""Config flow for the RIRC integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import RIRCApi
from .auth import RIRCAuth
from .const import CONF_LOGIN, CONF_PASSWORD, DOMAIN
from .exceptions import RIRCAuthError, RIRCConnectionError, RIRCTimeoutError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LOGIN): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class RIRCConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RIRC."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            login = user_input[CONF_LOGIN]
            password = user_input[CONF_PASSWORD]

            # Check if already configured with this login
            await self.async_set_unique_id(login)
            self._abort_if_unique_id_configured()

            # Try to authenticate
            try:
                session = async_create_clientsession(self.hass)
                auth = RIRCAuth(session)
                api = RIRCApi(auth, session)

                await api.async_login(login, password)

                return self.async_create_entry(
                    title=f"{login}",
                    data={
                        CONF_LOGIN: login,
                        CONF_PASSWORD: password,
                    },
                )

            except RIRCAuthError:
                errors["base"] = "invalid_auth"
            except RIRCConnectionError:
                errors["base"] = "cannot_connect"
            except RIRCTimeoutError:
                errors["base"] = "timeout"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    # ---- Reauthentication flow ----

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Handle re-authentication when credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation step."""
        errors: dict[str, str] = {}

        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            login = reauth_entry.data[CONF_LOGIN]
            password = user_input[CONF_PASSWORD]

            try:
                session = async_create_clientsession(self.hass)
                auth = RIRCAuth(session)
                api = RIRCApi(auth, session)
                await api.async_login(login, password)

                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={CONF_LOGIN: login, CONF_PASSWORD: password},
                )

            except RIRCAuthError:
                errors["base"] = "invalid_auth"
            except RIRCConnectionError:
                errors["base"] = "cannot_connect"
            except RIRCTimeoutError:
                errors["base"] = "timeout"
            except Exception:
                _LOGGER.exception("Unexpected exception during reauth")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
            description_placeholders={
                CONF_LOGIN: reauth_entry.data[CONF_LOGIN],
            },
        )

    # ---- Reconfiguration flow ----

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration (change login/password)."""
        errors: dict[str, str] = {}

        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            login = user_input[CONF_LOGIN]
            password = user_input[CONF_PASSWORD]

            try:
                session = async_create_clientsession(self.hass)
                auth = RIRCAuth(session)
                api = RIRCApi(auth, session)
                await api.async_login(login, password)

                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data={CONF_LOGIN: login, CONF_PASSWORD: password},
                )

            except RIRCAuthError:
                errors["base"] = "invalid_auth"
            except RIRCConnectionError:
                errors["base"] = "cannot_connect"
            except RIRCTimeoutError:
                errors["base"] = "timeout"
            except Exception:
                _LOGGER.exception("Unexpected exception during reconfigure")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOGIN,
                        default=reconfigure_entry.data.get(CONF_LOGIN, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
