"""DeviceInfo compartido: agrupa las entidades de cada grupo IP como un
dispositivo, y las entidades globales bajo el propio controlador."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DEFAULT_PORT, DOMAIN


def hub_device_info(entry: ConfigEntry) -> DeviceInfo:
    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    url = None
    if host:
        url = f"https://{host}" if port == DEFAULT_PORT else f"https://{host}:{port}"
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Omada IP Groups ({host})",
        manufacturer="TP-Link Omada",
        model="Controlador Omada (grupos IP)",
        configuration_url=url,
    )


def group_device_info(
    hass: HomeAssistant, entry: ConfigEntry, group_id: str, group_name: str
) -> DeviceInfo:
    # Desde HA 2026.9 el dispositivo padre se indica por su id en el registro
    # (via_device_id) y no por su identificador (via_device, que deja de
    # funcionar en 2027.8). El del controlador lo registra async_setup_entry
    # antes de crear ninguna entidad, así que aquí ya existe.
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{group_id}")},
        name=group_name,
        manufacturer="TP-Link Omada",
        model="Grupo IP",
        via_device_id=dr.async_get_device_id_by_identifier(
            hass, (DOMAIN, entry.entry_id), config_entry_id=entry.entry_id
        ),
    )
