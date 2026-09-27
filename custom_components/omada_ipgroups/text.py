"""Entidades `text`: campos editables en memoria, sin necesidad de helpers.

Por grupo: "IP a añadir" y "Descripción de la IP a añadir".
Global (bajo el propio controlador): "Nombre del nuevo grupo".
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OmadaIPGroupsCoordinator
from .entity import group_device_info, hub_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: OmadaIPGroupsCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_group_ids: set[str] = set()

    # Entidad global: nombre para el próximo grupo a crear.
    async_add_entities([OmadaNewGroupNameText(entry)])

    @callback
    def _async_sync_entities() -> None:
        current_ids = set(coordinator.data or {})
        new_ids = current_ids - known_group_ids
        if new_ids:
            known_group_ids.update(new_ids)
            entities: list[TextEntity] = []
            for group_id in new_ids:
                entities.append(OmadaGroupNewIpText(coordinator, entry, group_id))
                entities.append(OmadaGroupNewIpDescriptionText(coordinator, entry, group_id))
            async_add_entities(entities)

    _async_sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync_entities))


class _OmadaGroupTextBase(CoordinatorEntity[OmadaIPGroupsCoordinator], TextEntity):
    """Campo de texto simple en memoria, ligado a un grupo IP concreto."""

    _attr_has_entity_name = True
    _attr_mode = TextMode.TEXT
    _attr_native_max = 100

    def __init__(
        self,
        coordinator: OmadaIPGroupsCoordinator,
        entry: ConfigEntry,
        group_id: str,
        suffix: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_{suffix}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_value = ""

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
        return group_device_info(self.hass, self._entry, self._group_id, name)

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


class OmadaGroupNewIpText(_OmadaGroupTextBase):
    def __init__(self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str) -> None:
        super().__init__(coordinator, entry, group_id, "new_ip", "IP a añadir", "mdi:ip-network")


class OmadaGroupNewIpDescriptionText(_OmadaGroupTextBase):
    def __init__(self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str) -> None:
        super().__init__(
            coordinator, entry, group_id, "new_ip_desc", "Descripción de la IP a añadir", "mdi:text"
        )


class OmadaNewGroupNameText(TextEntity):
    """Entidad global (no ligada a un grupo existente): nombre del grupo a crear."""

    _attr_has_entity_name = True
    _attr_mode = TextMode.TEXT
    _attr_native_max = 100
    _attr_icon = "mdi:folder-plus"
    _attr_name = "Nombre del nuevo grupo"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_new_group_name"
        self._attr_native_value = ""

    @property
    def device_info(self):
        return hub_device_info(self._entry)

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
