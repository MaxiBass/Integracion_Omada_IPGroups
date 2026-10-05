"""Config flow para Omada IP Groups."""
from __future__ import annotations

from collections.abc import Mapping
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

# Como el alta, pero sin valores por defecto (el formulario sale relleno con
# los actuales, y lo que no se mande se conserva) y con la contraseña
# opcional: vacía, se mantiene la que había.
STEP_RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_SITE_NAME): str,
        vol.Optional(CONF_VERIFY_SSL): bool,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
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

    async def _async_validate(self, data: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
        """Prueba los datos contra el controlador: (site real, errores)."""
        try:
            return await _validate_input(data), {}
        except OmadaAuthError:
            return None, {"base": "invalid_auth"}
        except OmadaConnectionError:
            return None, {"base": "cannot_connect"}
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Error inesperado validando la configuración")
            return None, {"base": "unknown"}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            site_name, errors = await self._async_validate(user_input)
            if not errors:
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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cambia los datos de conexión sin borrar la entrada (ni sus entidades)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **user_input}
            if not user_input.get(CONF_PASSWORD):
                data[CONF_PASSWORD] = entry.data[CONF_PASSWORD]
            site_name, errors = await self._async_validate(data)
            if not errors:
                data[CONF_SITE_NAME] = site_name
                unique_id = f"{data[CONF_HOST]}:{data[CONF_PORT]}:{site_name}"
                if any(
                    other.unique_id == unique_id
                    for other in self._async_current_entries(include_ignore=False)
                    if other.entry_id != entry.entry_id
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=f"Omada IP Groups ({data[CONF_HOST]})",
                    data=data,
                )

        suggested = {k: v for k, v in entry.data.items() if k != CONF_PASSWORD}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(STEP_RECONFIGURE_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """El controlador ha rechazado el usuario o la contraseña al arrancar."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            _site, errors = await self._async_validate({**entry.data, **user_input})
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                STEP_REAUTH_SCHEMA, {CONF_USERNAME: entry.data[CONF_USERNAME]}
            ),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )
