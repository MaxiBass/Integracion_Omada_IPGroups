"""Sensores por grupo IP: el del grupo (nº de IPs, con la lista como
atributo) y el de las IPs quitadas temporalmente (ver temporal.py)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OmadaIPGroupsCoordinator
from .entity import group_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Crea las entidades iniciales y se suscribe a altas/bajas de grupos."""
    coordinator: OmadaIPGroupsCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_group_ids: set[str] = set()

    @callback
    def _async_sync_entities() -> None:
        current_ids = set(coordinator.data or {})
        new_ids = current_ids - known_group_ids
        if new_ids:
            known_group_ids.update(new_ids)
            entities: list[SensorEntity] = []
            for group_id in new_ids:
                entities.append(OmadaIPGroupSensor(coordinator, entry, group_id))
                entities.append(OmadaTempRemovedSensor(coordinator, entry, group_id))
            async_add_entities(entities)
        # Los grupos borrados desaparecen solos: available=False vía CoordinatorEntity
        # más la condición en `available` de abajo.

    _async_sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync_entities))


class OmadaIPGroupSensor(CoordinatorEntity[OmadaIPGroupsCoordinator], SensorEntity):
    """Representa un grupo IP: el estado es el nº de IPs, atributos = detalle."""

    _attr_has_entity_name = True
    # Sin nombre propio: es la entidad principal del dispositivo del grupo y
    # toma su nombre. Si repitiera el del grupo, HA mostraría "X X".
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:ip-network"

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}"

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

    @property
    def native_value(self) -> int | None:
        group = self._group
        if group is None:
            return None
        return len(group.get("ipList") or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        group = self._group
        if group is None:
            return {}
        return {
            "group_id": group.get("groupId"),
            "description": group.get("description"),
            "ips": [
                {
                    "ip": entry.get("ip"),
                    "mask": entry.get("mask"),
                    "description": entry.get("description"),
                }
                for entry in (group.get("ipList") or [])
            ],
        }


class OmadaTempRemovedSensor(CoordinatorEntity[OmadaIPGroupsCoordinator], SensorEntity):
    """Nº de IPs quitadas temporalmente del grupo, con cuándo vuelve cada una."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_name = "Quitadas temporalmente"

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_temp_removed"

    @property
    def device_info(self):
        group = (self.coordinator.data or {}).get(self._group_id)
        name = group["name"] if group else self._group_id
        return group_device_info(self.hass, self._entry, self._group_id, name)

    @property
    def _records(self) -> list[dict[str, Any]]:
        return self.coordinator.temporales.records(self._group_id)

    @property
    def native_value(self) -> int:
        return len(self._records)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        records = self._records
        # restore_at None = no vuelve sola, hasta pulsar «Volver a añadir».
        pending = sorted(r["restore_at"] for r in records if r["restore_at"])
        return {
            "ips": [
                {k: r[k] for k in ("ip", "mask", "description", "removed_at", "restore_at")}
                for r in records
            ],
            "next_restore": pending[0] if pending else None,
        }
