"""IPs quitadas de un grupo temporalmente, para volver a añadirlas después.

Caso de uso: un grupo que bloquea Internet (por una regla ACL de Omada) y un
dispositivo que necesita salir un rato, p. ej. para actualizar su firmware.
Se le saca del grupo y luego se le vuelve a meter tal como estaba.

Cada IP quitada se guarda en disco con su máscara y su descripción, así que
un reinicio de HA no hace perder qué hay que devolver. Si se quitó con
límite de tiempo, vuelve sola al cumplirse; si el controlador no responde en
ese momento, se reintenta cada minuto hasta que entre.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import OmadaApiError, OmadaGroupNotFoundError
from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import OmadaIPGroupsCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
RETRY_DELAY = 60  # segundos entre reintentos si el controlador no responde


def storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}.temporales"


class TemporaryRemovals:
    """Registro de las IPs que están fuera de su grupo temporalmente."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator: OmadaIPGroupsCoordinator
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, storage_key(entry.entry_id))
        # group_id -> ip -> {ip, mask, description, removed_at, restore_at}
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._timers: dict[tuple[str, str], CALLBACK_TYPE] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self._data = stored.get("groups", {})
        for group_id, records in self._data.items():
            for ip in records:
                self._schedule(group_id, ip)

    @callback
    def async_unload(self) -> None:
        """Cancela los temporizadores; lo guardado en disco se queda."""
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    def records(self, group_id: str) -> list[dict[str, Any]]:
        return list(self._data.get(group_id, {}).values())

    # ------------------------------------------------------------------

    async def async_remove(self, group_id: str, ip: str, minutes: int | None) -> None:
        """Saca una IP del grupo y la apunta para devolverla después.

        Con `minutes` (> 0) vuelve sola pasado ese tiempo; sin él, solo al
        llamar a async_restore.
        """
        client = self._coordinator.client
        try:
            group = await client.async_get_ip_group(group_id)
        except OmadaApiError as err:
            raise HomeAssistantError(f"Error leyendo el grupo: {err}") from err
        entry = next((e for e in group.get("ipList") or [] if e.get("ip") == ip), None)
        if entry is None:
            raise HomeAssistantError(f"La IP {ip} no está en el grupo {group.get('name')}")

        now = dt_util.utcnow()
        record = {
            "ip": ip,
            "mask": entry.get("mask", 32),
            "description": entry.get("description") or "",
            "removed_at": now.isoformat(),
            "restore_at": (now + timedelta(minutes=minutes)).isoformat() if minutes else None,
        }
        # Se apunta antes de quitarla: si HA se cayera justo después de la
        # petición, la IP seguiría constando como pendiente de devolver.
        self._data.setdefault(group_id, {})[ip] = record
        await self._async_save()
        try:
            await client.async_remove_ip(group_id, ip)
        except OmadaApiError as err:
            await self._async_forget(group_id, ip)
            raise HomeAssistantError(f"Error quitando la IP: {err}") from err

        self._schedule(group_id, ip)
        self._coordinator.async_update_listeners()

    async def async_restore(self, group_id: str, ip: str | None = None) -> None:
        """Devuelve al grupo una IP quitada temporalmente, o todas las del grupo."""
        pending = self._data.get(group_id, {})
        if ip is not None and ip not in pending:
            raise HomeAssistantError(f"La IP {ip} no está quitada temporalmente de este grupo")
        if not pending:
            raise HomeAssistantError("No hay ninguna IP quitada temporalmente en este grupo")
        for one in [ip] if ip is not None else list(pending):
            try:
                await self._async_restore_one(group_id, one)
            except OmadaApiError as err:
                raise HomeAssistantError(f"Error volviendo a añadir {one}: {err}") from err

    # ------------------------------------------------------------------

    async def _async_restore_one(self, group_id: str, ip: str) -> None:
        record = self._data[group_id][ip]
        try:
            # async_add_ip no duplica: si alguien la volvió a añadir a mano,
            # no hace nada y aquí solo se borra el apunte.
            await self._coordinator.client.async_add_ip(
                group_id, ip, mask=record["mask"], description=record["description"]
            )
        except OmadaGroupNotFoundError:
            _LOGGER.warning(
                "El grupo %s ya no existe: no se puede devolver la IP %s, se olvida", group_id, ip
            )
        await self._async_forget(group_id, ip)
        self._coordinator.async_update_listeners()
        await self._coordinator.async_request_refresh()

    @callback
    def _schedule(self, group_id: str, ip: str) -> None:
        self._cancel(group_id, ip)
        restore_at = self._data[group_id][ip].get("restore_at")
        if not restore_at:
            return
        when = dt_util.parse_datetime(restore_at)
        # Si ya pasó (HA estaba apagado), se dispara enseguida.
        self._timers[(group_id, ip)] = async_track_point_in_utc_time(
            self._hass, partial(self._async_expired, group_id, ip), when
        )

    async def _async_expired(self, group_id: str, ip: str, _now: datetime) -> None:
        self._timers.pop((group_id, ip), None)
        if ip not in self._data.get(group_id, {}):
            return
        try:
            await self._async_restore_one(group_id, ip)
        except OmadaApiError as err:
            _LOGGER.warning(
                "No se pudo devolver la IP %s a su grupo (%s); se reintenta en %s s",
                ip,
                err,
                RETRY_DELAY,
            )
            self._timers[(group_id, ip)] = async_call_later(
                self._hass, RETRY_DELAY, partial(self._async_expired, group_id, ip)
            )
        else:
            _LOGGER.info("IP %s devuelta a su grupo al acabar el tiempo", ip)

    @callback
    def _cancel(self, group_id: str, ip: str) -> None:
        if cancel := self._timers.pop((group_id, ip), None):
            cancel()

    async def _async_forget(self, group_id: str, ip: str) -> None:
        self._cancel(group_id, ip)
        records = self._data.get(group_id, {})
        records.pop(ip, None)
        if not records:
            self._data.pop(group_id, None)
        await self._async_save()

    async def _async_save(self) -> None:
        await self._store.async_save({"groups": self._data})
