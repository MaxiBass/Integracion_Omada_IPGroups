"""Entidades `button`: disparan las acciones leyendo el estado de los campos
`text`/`select`/`number` de la propia integración (sin depender de helpers
externos)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OmadaApiError
from .const import DEFAULT_TEMP_MINUTES, DOMAIN
from .coordinator import OmadaIPGroupsCoordinator
from .entity import group_device_info, hub_device_info
from .select import parse_ip_from_option


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: OmadaIPGroupsCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_group_ids: set[str] = set()

    async_add_entities([OmadaCreateGroupButton(entry, coordinator)])

    @callback
    def _async_sync_entities() -> None:
        current_ids = set(coordinator.data or {})
        new_ids = current_ids - known_group_ids
        if new_ids:
            known_group_ids.update(new_ids)
            entities: list[ButtonEntity] = []
            for group_id in new_ids:
                entities.append(OmadaAddIpButton(coordinator, entry, group_id))
                entities.append(OmadaRemoveIpButton(coordinator, entry, group_id))
                entities.append(OmadaTempRemoveIpButton(coordinator, entry, group_id))
                entities.append(OmadaRestoreIpsButton(coordinator, entry, group_id))
                entities.append(OmadaDeleteGroupButton(coordinator, entry, group_id))
            async_add_entities(entities)

    _async_sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync_entities))


def _read_state(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    """Lee el estado actual de una de nuestras propias entidades por su unique_id."""
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    return state.state if state else None


def _selected_ip(hass: HomeAssistant, entry: ConfigEntry, group_id: str) -> str:
    """IP elegida en el desplegable «IP a quitar» del grupo; error si no hay."""
    option = _read_state(hass, "select", f"{entry.entry_id}_{group_id}_remove_ip_select")
    if not option or option in ("unknown", "unavailable"):
        raise HomeAssistantError("Elige primero una IP en «IP a quitar»")
    return parse_ip_from_option(option)


async def _clear_text(hass: HomeAssistant, unique_id: str) -> None:
    entity_id = er.async_get(hass).async_get_entity_id("text", DOMAIN, unique_id)
    if entity_id:
        await hass.services.async_call(
            "text", "set_value", {"entity_id": entity_id, "value": ""}, blocking=True
        )


class OmadaAddIpButton(CoordinatorEntity[OmadaIPGroupsCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:plus-network"
    _attr_name = "Añadir IP"

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_add_ip_button"

    @property
    def device_info(self):
        group = (self.coordinator.data or {}).get(self._group_id)
        name = group["name"] if group else self._group_id
        return group_device_info(self.hass, self._entry, self._group_id, name)

    async def async_press(self) -> None:
        ip_unique = f"{self._entry.entry_id}_{self._group_id}_new_ip"
        desc_unique = f"{self._entry.entry_id}_{self._group_id}_new_ip_desc"
        ip = _read_state(self.hass, "text", ip_unique)
        description = _read_state(self.hass, "text", desc_unique) or ""

        if not ip:
            raise HomeAssistantError(
                "Escribe primero una IP en el campo 'IP a añadir' de este grupo"
            )

        try:
            await self.coordinator.client.async_add_ip(
                self._group_id, ip, mask=32, description=description
            )
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error añadiendo la IP: {err}") from err

        await _clear_text(self.hass, ip_unique)
        await _clear_text(self.hass, desc_unique)
        await self.coordinator.async_refresh()


class OmadaRemoveIpButton(CoordinatorEntity[OmadaIPGroupsCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:minus-network"
    _attr_name = "Quitar IP seleccionada"

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_remove_ip_button"

    @property
    def device_info(self):
        group = (self.coordinator.data or {}).get(self._group_id)
        name = group["name"] if group else self._group_id
        return group_device_info(self.hass, self._entry, self._group_id, name)

    async def async_press(self) -> None:
        ip = _selected_ip(self.hass, self._entry, self._group_id)
        try:
            await self.coordinator.client.async_remove_ip(self._group_id, ip)
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error quitando la IP: {err}") from err
        await self.coordinator.async_refresh()


class OmadaTempRemoveIpButton(CoordinatorEntity[OmadaIPGroupsCoordinator], ButtonEntity):
    """Quita la IP del desplegable «IP a quitar» y la guarda para devolverla."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-minus-outline"
    _attr_name = "Quitar temporalmente"

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_temp_remove_button"

    @property
    def device_info(self):
        group = (self.coordinator.data or {}).get(self._group_id)
        name = group["name"] if group else self._group_id
        return group_device_info(self.hass, self._entry, self._group_id, name)

    async def async_press(self) -> None:
        ip = _selected_ip(self.hass, self._entry, self._group_id)
        minutes_unique = f"{self._entry.entry_id}_{self._group_id}_temp_minutes"
        try:
            minutes = int(float(_read_state(self.hass, "number", minutes_unique)))
        except (TypeError, ValueError):
            minutes = DEFAULT_TEMP_MINUTES

        await self.coordinator.temporales.async_remove(self._group_id, ip, minutes or None)
        await self.coordinator.async_refresh()


class OmadaRestoreIpsButton(CoordinatorEntity[OmadaIPGroupsCoordinator], ButtonEntity):
    """Devuelve al grupo todas las IPs quitadas temporalmente de él."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:restore"
    _attr_name = "Volver a añadir"

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_restore_button"

    @property
    def device_info(self):
        group = (self.coordinator.data or {}).get(self._group_id)
        name = group["name"] if group else self._group_id
        return group_device_info(self.hass, self._entry, self._group_id, name)

    async def async_press(self) -> None:
        await self.coordinator.temporales.async_restore(self._group_id)


class OmadaDeleteGroupButton(CoordinatorEntity[OmadaIPGroupsCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:folder-remove"
    _attr_name = "Borrar este grupo"

    def __init__(
        self, coordinator: OmadaIPGroupsCoordinator, entry: ConfigEntry, group_id: str
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{group_id}_delete_group_button"

    @property
    def device_info(self):
        group = (self.coordinator.data or {}).get(self._group_id)
        name = group["name"] if group else self._group_id
        return group_device_info(self.hass, self._entry, self._group_id, name)

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.async_delete_ip_group(self._group_id)
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error borrando el grupo: {err}") from err
        await self.coordinator.async_refresh()


class OmadaCreateGroupButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:folder-plus"
    _attr_name = "Crear grupo"

    def __init__(self, entry: ConfigEntry, coordinator: OmadaIPGroupsCoordinator) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_create_group_button"

    @property
    def device_info(self):
        return hub_device_info(self._entry)

    async def async_press(self) -> None:
        name_unique = f"{self._entry.entry_id}_new_group_name"
        name = _read_state(self.hass, "text", name_unique)
        if not name:
            raise HomeAssistantError("Escribe primero un nombre en 'Nombre del nuevo grupo'")

        try:
            await self._coordinator.client.async_create_ip_group(name=name, ip_list=[])
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error creando el grupo: {err}") from err

        await _clear_text(self.hass, name_unique)
        await self._coordinator.async_refresh()
