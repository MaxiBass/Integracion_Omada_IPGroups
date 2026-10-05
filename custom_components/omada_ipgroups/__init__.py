"""Integración Omada IP Groups: gestión de grupos IP del controlador Omada local."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.storage import Store

from .api import OmadaApiError, OmadaAuthError, OmadaLocalClient
from .coordinator import OmadaIPGroupsCoordinator
from .const import (
    ATTR_DESCRIPTION,
    ATTR_GROUP_ID,
    ATTR_IP,
    ATTR_IPS,
    ATTR_MASK,
    ATTR_MINUTES,
    ATTR_NAME,
    CONF_SITE_NAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    MAX_TEMP_MINUTES,
    SERVICE_ADD_IP,
    SERVICE_CREATE_GROUP,
    SERVICE_DELETE_GROUP,
    SERVICE_REMOVE_IP,
    SERVICE_REMOVE_IP_TEMPORARILY,
    SERVICE_RESTORE_IPS,
    SERVICE_UPDATE_GROUP,
)
from .entity import hub_device_info
from .temporal import STORAGE_VERSION, TemporaryRemovals, storage_key

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "text", "select", "number", "button"]

SERVICES = (
    SERVICE_CREATE_GROUP,
    SERVICE_UPDATE_GROUP,
    SERVICE_DELETE_GROUP,
    SERVICE_ADD_IP,
    SERVICE_REMOVE_IP,
    SERVICE_REMOVE_IP_TEMPORARILY,
    SERVICE_RESTORE_IPS,
)

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
        # Sin valor por defecto: si no se indica, se conserva la del grupo.
        vol.Optional(ATTR_DESCRIPTION): cv.string,
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

SERVICE_REMOVE_IP_TEMPORARILY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROUP_ID): cv.string,
        vol.Required(ATTR_IP): cv.string,
        # Sin minutos (o 0), la IP no vuelve sola: hay que llamar a restore_ips.
        vol.Optional(ATTR_MINUTES, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_TEMP_MINUTES)
        ),
    }
)

SERVICE_RESTORE_IPS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROUP_ID): cv.string,
        vol.Optional(ATTR_IP): cv.string,
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
        await client.async_close()
        # Sin reintentos (acumularían logins fallidos en el controlador); HA
        # avisa y pide el usuario y la contraseña nuevos (config_flow, reauth).
        raise ConfigEntryAuthFailed(f"Autenticación fallida contra el controlador Omada: {err}") from err
    except OmadaApiError as err:
        # Controlador apagado, reiniciándose o aún arrancando (p. ej. si tras
        # un corte de luz HA arranca antes que él): HA reintenta solo.
        await client.async_close()
        raise ConfigEntryNotReady(f"No se pudo conectar al controlador Omada: {err}") from err

    if client.site_name and client.site_name != data[CONF_SITE_NAME]:
        # El site configurado no existe y el cliente ha usado el primero. Se
        # fija el real: así no se avisa en cada arranque y, si algún día se
        # crea otro site, la integración no cambia de site sin avisar.
        _LOGGER.info("Se guarda el site '%s' en lugar de '%s'", client.site_name, data[CONF_SITE_NAME])
        hass.config_entries.async_update_entry(
            entry, data={**data, CONF_SITE_NAME: client.site_name}
        )

    coordinator = OmadaIPGroupsCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.async_close()
        raise

    # IPs quitadas temporalmente: se cargan de disco y, si alguna debía haber
    # vuelto mientras HA estaba apagado, vuelve ahora.
    coordinator.temporales = TemporaryRemovals(hass, entry, coordinator)
    await coordinator.temporales.async_load()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # El dispositivo del controlador va antes que las entidades: los de cada
    # grupo lo referencian por su id de registro (ver entity.py).
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **hub_device_info(entry)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga una entrada de Omada IP Groups."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: OmadaIPGroupsCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.temporales.async_unload()
        await coordinator.client.async_close()

    if not hass.data.get(DOMAIN):
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Al borrar la integración, avisa de las IPs que se quedan fuera de su grupo.

    Ya no habrá quien las devuelva (una entrada nueva no hereda el registro),
    así que hay que volver a añadirlas a mano.
    """
    store: Store[dict] = Store(hass, STORAGE_VERSION, storage_key(entry.entry_id))
    stored = await store.async_load() or {}
    pending = [
        f"- {record['ip']}" + (f" ({record['description']})" if record.get("description") else "")
        for records in stored.get("groups", {}).values()
        for record in records.values()
    ]
    if pending:
        persistent_notification.async_create(
            hass,
            "Se ha borrado la integración con estas IPs quitadas temporalmente de "
            "su grupo, y ya no volverán solas. Añádelas a mano si hace falta:\n"
            + "\n".join(pending),
            title="Omada IP Groups: IPs fuera de su grupo",
            notification_id=f"{DOMAIN}_{entry.entry_id}_temporales",
        )
    await store.async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Deja eliminar desde HA el dispositivo de un grupo que ya no existe.

    Al borrar un grupo, su dispositivo y sus entidades se quedan como no
    disponibles; sin esto no había forma de quitarlos.
    """
    coordinator: OmadaIPGroupsCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return False
    alive = {(DOMAIN, entry.entry_id)} | {
        (DOMAIN, f"{entry.entry_id}_{group_id}") for group_id in coordinator.data or {}
    }
    return not device.identifiers & alive


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
                description=call.data.get(ATTR_DESCRIPTION),
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
    async def handle_remove_ip_temporarily(call: ServiceCall) -> None:
        coordinator = _get_first_coordinator(hass)
        await coordinator.temporales.async_remove(
            call.data[ATTR_GROUP_ID], call.data[ATTR_IP], call.data[ATTR_MINUTES] or None
        )
        await coordinator.async_request_refresh()

    async def handle_restore_ips(call: ServiceCall) -> None:
        coordinator = _get_first_coordinator(hass)
        await coordinator.temporales.async_restore(
            call.data[ATTR_GROUP_ID], call.data.get(ATTR_IP)
        )

    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_IP, handle_remove_ip, schema=SERVICE_REMOVE_IP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_IP_TEMPORARILY,
        handle_remove_ip_temporarily,
        schema=SERVICE_REMOVE_IP_TEMPORARILY_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESTORE_IPS, handle_restore_ips, schema=SERVICE_RESTORE_IPS_SCHEMA
    )
