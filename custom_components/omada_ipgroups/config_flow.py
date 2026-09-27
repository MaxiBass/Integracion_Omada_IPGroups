"""Config flow para Omada IP Groups."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .api import OmadaAuthError, OmadaConnectionError, OmadaLocalClient
from .const import (
    CONF_SITE_NAME,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SITE_NAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SITE_NAME, default=DEFAULT_SITE_NAME): str,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


async def _validate_input(data: dict[str, Any]) -> None:
    """Prueba login + resolución de site contra el controlador real."""
    connector = aiohttp.TCPConnector(ssl=data[CONF_VERIFY_SSL])
    # Mismo motivo que en api.py: el host es una IP, así que forzamos el
    # cookie jar en modo unsafe para que aiohttp no descarte la cookie de
    # sesión del controlador.
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(connector=connector, cookie_jar=cookie_jar) as session:
        client = OmadaLocalClient(
            host=data[CONF_HOST],
            port=data[CONF_PORT],
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            site_name=data[CONF_SITE_NAME],
            verify_ssl=data[CONF_VERIFY_SSL],
            session=session,
        )
        await client.async_setup()


class OmadaIPGroupsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow de Omada IP Groups."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_input(user_input)
            except OmadaAuthError:
                errors["base"] = "invalid_auth"
            except OmadaConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Error inesperado validando la configuración")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_SITE_NAME]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Omada IP Groups ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
