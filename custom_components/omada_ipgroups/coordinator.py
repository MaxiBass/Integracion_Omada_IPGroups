"""Coordinator para sondear los grupos IP del controlador Omada."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OmadaApiError, OmadaLocalClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

if TYPE_CHECKING:
    from .temporal import TemporaryRemovals

_LOGGER = logging.getLogger(__name__)


class OmadaIPGroupsCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Mantiene en caché los grupos IP, indexados por id de grupo."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: OmadaLocalClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        # Lo crea async_setup_entry tras el primer sondeo (ver temporal.py).
        self.temporales: TemporaryRemovals | None = None

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            groups = await self.client.async_get_ip_groups()
        except OmadaApiError as err:
            raise UpdateFailed(f"Error consultando grupos IP: {err}") from err
        return {group["groupId"]: group for group in groups}
