"""DeviceInfo compartido: agrupa las entidades de cada grupo IP como un
dispositivo, y las entidades globales bajo el propio controlador."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


def hub_device_info(entry: ConfigEntry) -> DeviceInfo:
    host = entry.data.get(CONF_HOST)
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Omada IP Groups ({host})",
        manufacturer="TP-Link Omada",
        model="Controlador Omada (grupos IP)",
        configuration_url=f"https://{host}" if host else None,
    )


def group_device_info(entry: ConfigEntry, group_id: str, group_name: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{group_id}")},
        name=group_name,
        manufacturer="TP-Link Omada",
        model="Grupo IP",
        via_device=(DOMAIN, entry.entry_id),
    )
