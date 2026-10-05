"""Diagnóstico descargable (Ajustes → Dispositivos y servicios → la entrada →
⋮ → Descargar diagnóstico). Sin usuario ni contraseña del controlador."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import OmadaIPGroupsCoordinator

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: OmadaIPGroupsCoordinator = hass.data[DOMAIN][entry.entry_id]
    groups = coordinator.data or {}
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "controller": {
            "site_name": coordinator.client.site_name,
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
        },
        # Tal como los devuelve el controlador, para ver campos que la
        # integración no muestra.
        "groups": list(groups.values()),
        "temporarily_removed": coordinator.temporales.all_records(),
    }
