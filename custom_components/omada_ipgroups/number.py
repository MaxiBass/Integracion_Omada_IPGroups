"""Entidad `number`: minutos que pasa una IP fuera de su grupo al quitarla
temporalmente. Lo lee el botón «Quitar temporalmente» de cada grupo."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_TEMP_MINUTES, DOMAIN, MAX_TEMP_MINUTES
from .coordinator import OmadaIPGroupsCoordinator
from .entity import group_device_info


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
                OmadaTempMinutesNumber(coordinator, entry, group_id) for group_id in new_ids
            )

    _async_sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync_entities))


class OmadaTempMinutesNumber(CoordinatorEntity[OmadaIPGroupsCoordinator], RestoreNumber):
    """0 = la IP no vuelve sola; hay que pulsar «Volver a añadir»."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"
    _attr_name = "Minutos fuera del grupo"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_TEMP_MINUTES
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_temp_minutes"
        self._attr_native_value = DEFAULT_TEMP_MINUTES

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            self._attr_native_value = last.native_value

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

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
