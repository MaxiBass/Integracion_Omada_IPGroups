"""Entidad `select`: elige qué IP quitar de un grupo, listando las actuales."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OmadaIPGroupsCoordinator
from .entity import group_device_info


def format_ip_option(entry: dict[str, Any]) -> str:
    """Da formato 'ip (descripción)' a una entrada de ipList, para mostrar en el desplegable."""
    ip = entry.get("ip", "")
    description = entry.get("description")
    return f"{ip} ({description})" if description else ip


def parse_ip_from_option(option: str) -> str:
    """Extrae la IP pura de una opción con el formato de format_ip_option."""
    return option.split(" (", 1)[0]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: OmadaIPGroupsCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_group_ids: set[str] = set()

    @callback
    def _async_sync_entities() -> None:
        current_ids = set(coordinator.data or {})
        new_ids = current_ids - known_group_ids
        if new_ids:
            known_group_ids.update(new_ids)
            async_add_entities(
                OmadaGroupRemoveIpSelect(coordinator, entry, group_id) for group_id in new_ids
            )

    _async_sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync_entities))


class OmadaGroupRemoveIpSelect(CoordinatorEntity[OmadaIPGroupsCoordinator], SelectEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:ip-network-outline"
    _attr_name = "IP a quitar"

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_remove_ip_select"
        self._selected: str | None = None

    @property
    def _group(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get(self._group_id)

    @property
    def available(self) -> bool:
        return super().available and self._group is not None

    @property
    def device_info(self):
        group = self._group
        name = group["name"] if group else self._group_id
        return group_device_info(self._entry, self._group_id, name)

    @property
    def options(self) -> list[str]:
        group = self._group
        if not group:
            return []
        return [format_ip_option(entry) for entry in (group.get("ipList") or [])]

    @property
    def current_option(self) -> str | None:
        opts = self.options
        if self._selected in opts:
            return self._selected
        return opts[0] if opts else None

    async def async_select_option(self, option: str) -> None:
        self._selected = option
        self.async_write_ha_state()
