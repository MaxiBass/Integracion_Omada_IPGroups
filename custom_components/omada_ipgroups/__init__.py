"""Integración Omada IP Groups: gestión de grupos IP del controlador Omada local."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .api import OmadaApiError, OmadaAuthError, OmadaConnectionError, OmadaLocalClient
from .coordinator import OmadaIPGroupsCoordinator
from .const import (
    ATTR_DESCRIPTION,
    ATTR_GROUP_ID,
    ATTR_IP,
    ATTR_IPS,
    ATTR_MASK,
    ATTR_NAME,
    CONF_SITE_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    SERVICE_ADD_IP,
    SERVICE_CREATE_GROUP,
    SERVICE_DELETE_GROUP,
    SERVICE_REMOVE_IP,
    SERVICE_UPDATE_GROUP,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "text", "select", "button"]

IP_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_IP): cv.string,
        vol.Optional(ATTR_MASK, default=32): vol.All(int, vol.Range(min=0, max=32)),
        vol.Optional(ATTR_DESCRIPTION, default=""): cv.string,
    }
)

SERVICE_CREATE_GROUP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_IPS): vol.All(cv.ensure_list, [IP_ENTRY_SCHEMA]),
        vol.Optional(ATTR_DESCRIPTION, default=""): cv.string,
    }
)

SERVICE_UPDATE_GROUP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROUP_ID): cv.string,
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_IPS): vol.All(cv.ensure_list, [IP_ENTRY_SCHEMA]),
        vol.Optional(ATTR_DESCRIPTION, default=""): cv.string,
    }
)

SERVICE_DELETE_GROUP_SCHEMA = vol.Schema({vol.Required(ATTR_GROUP_ID): cv.string})

SERVICE_ADD_IP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROUP_ID): cv.string,
        vol.Required(ATTR_IP): cv.string,
        vol.Optional(ATTR_MASK, default=32): vol.All(int, vol.Range(min=0, max=32)),
        vol.Optional(ATTR_DESCRIPTION, default=""): cv.string,
    }
)

SERVICE_REMOVE_IP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROUP_ID): cv.string,
        vol.Required(ATTR_IP): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura una entrada de Omada IP Groups."""
    data = entry.data

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
    except OmadaAuthError as err:
        raise HomeAssistantError(f"Autenticación fallida contra el controlador Omada: {err}") from err
    except OmadaConnectionError as err:
        await client.async_close()
        raise HomeAssistantError(f"No se pudo conectar al controlador Omada: {err}") from err

    coordinator = OmadaIPGroupsCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga una entrada de Omada IP Groups."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: OmadaIPGroupsCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.async_close()

    if not hass.data.get(DOMAIN):
        for service in (
            SERVICE_CREATE_GROUP,
            SERVICE_UPDATE_GROUP,
            SERVICE_DELETE_GROUP,
            SERVICE_ADD_IP,
            SERVICE_REMOVE_IP,
        ):
            hass.services.async_remove(DOMAIN, service)

    return unload_ok


def _get_first_coordinator(hass: HomeAssistant) -> OmadaIPGroupsCoordinator:
    """Devuelve el coordinator de la (única) entrada configurada.

    Si en el futuro se soporta más de un controlador, los servicios deberán
    aceptar un selector de config_entry; por ahora se asume uno solo.
    """
    coordinators = list(hass.data.get(DOMAIN, {}).values())
    if not coordinators:
        raise HomeAssistantError("No hay ninguna entrada de Omada IP Groups configurada")
    return coordinators[0]


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_GROUP):
        return  # ya registrados por una entrada anterior

    async def handle_create_group(call: ServiceCall) -> None:
        coordinator = _get_first_coordinator(hass)
        try:
            await coordinator.client.async_create_ip_group(
                name=call.data[ATTR_NAME],
                ip_list=call.data[ATTR_IPS],
                description=call.data.get(ATTR_DESCRIPTION, ""),
            )
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error creando grupo IP: {err}") from err
        await coordinator.async_request_refresh()

    async def handle_update_group(call: ServiceCall) -> None:
        coordinator = _get_first_coordinator(hass)
        try:
            await coordinator.client.async_update_ip_group(
                group_id=call.data[ATTR_GROUP_ID],
                name=call.data[ATTR_NAME],
                ip_list=call.data[ATTR_IPS],
                description=call.data.get(ATTR_DESCRIPTION, ""),
            )
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error actualizando grupo IP: {err}") from err
        await coordinator.async_request_refresh()

    async def handle_delete_group(call: ServiceCall) -> None:
        coordinator = _get_first_coordinator(hass)
        try:
            await coordinator.client.async_delete_ip_group(call.data[ATTR_GROUP_ID])
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error borrando grupo IP: {err}") from err
        await coordinator.async_request_refresh()

    async def handle_add_ip(call: ServiceCall) -> None:
        coordinator = _get_first_coordinator(hass)
        try:
            await coordinator.client.async_add_ip(
                group_id=call.data[ATTR_GROUP_ID],
                ip=call.data[ATTR_IP],
                mask=call.data.get(ATTR_MASK, 32),
                description=call.data.get(ATTR_DESCRIPTION, ""),
            )
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error añadiendo IP al grupo: {err}") from err
        await coordinator.async_request_refresh()

    async def handle_remove_ip(call: ServiceCall) -> None:
        coordinator = _get_first_coordinator(hass)
        try:
            await coordinator.client.async_remove_ip(
                group_id=call.data[ATTR_GROUP_ID],
                ip=call.data[ATTR_IP],
            )
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error quitando IP del grupo: {err}") from err
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_CREATE_GROUP, handle_create_group, schema=SERVICE_CREATE_GROUP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_GROUP, handle_update_group, schema=SERVICE_UPDATE_GROUP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_GROUP, handle_delete_group, schema=SERVICE_DELETE_GROUP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_IP, handle_add_ip, schema=SERVICE_ADD_IP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_IP, handle_remove_ip, schema=SERVICE_REMOVE_IP_SCHEMA
    )
