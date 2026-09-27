"""Config flow para Omada IP Groups."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

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


async def _validate_input(data: dict[str, Any]) -> str:
    """Prueba login + resolución de site contra el controlador real.

    Devuelve el nombre del site que se usará: si el indicado no existe, el
    cliente cae en el primero, y es ese el que hay que guardar.
    """
    client = OmadaLocalClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        site_name=data[CONF_SITE_NAME],
        verify_ssl=data[CONF_VERIFY_SSL],
    )
    try:
        await client.async_setup()
    finally:
        await client.async_close()
    return client.site_name or data[CONF_SITE_NAME]


class OmadaIPGroupsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow de Omada IP Groups."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                site_name = await _validate_input(user_input)
            except OmadaAuthError:
                errors["base"] = "invalid_auth"
            except OmadaConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Error inesperado validando la configuración")
                errors["base"] = "unknown"
            else:
                user_input = {**user_input, CONF_SITE_NAME: site_name}
                # Las entradas antiguas tienen el unique_id con el site que se
                # escribió (p. ej. "Default"), no con el real; se comparan
                # también por datos para no darlas de alta dos veces.
                self._async_abort_entries_match(
                    {
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_SITE_NAME: site_name,
                    }
                )
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
