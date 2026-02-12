"""Diagnostics support for the RIRC integration.

Download from: Settings → Integrations → RIRC → ⋮ → Download diagnostics
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .__init__ import RIRCConfigEntry
from .const import CONF_LOGIN, CONF_PASSWORD, DATA_ACCOUNTS, DATA_KVIT, DATA_METERS, DATA_PAYMENTS

# Keys to redact from diagnostics output
TO_REDACT = {CONF_LOGIN, CONF_PASSWORD, "sid", "user_login", "user_name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: RIRCConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    # Config entry data (redacted)
    config_data = async_redact_data(dict(entry.data), TO_REDACT)

    # Auth state
    auth_info = {
        "authenticated": coordinator.api.auth_authenticated,
        "sid": "**REDACTED**" if coordinator.api.auth_sid else None,
        "user_name": "**REDACTED**" if coordinator.api.auth_user_name else None,
    }

    # Coordinator state
    coordinator_info = {
        "last_update_success": coordinator.last_update_success,
        "last_exception": str(coordinator.last_exception) if coordinator.last_exception else None,
        "update_interval_seconds": coordinator.update_interval.total_seconds() if coordinator.update_interval else None,
    }

    # Raw data from coordinator
    raw_data: dict[str, Any] = {}
    if coordinator.data:
        raw_data = {
            DATA_ACCOUNTS: coordinator.data.get(DATA_ACCOUNTS, []),
            DATA_METERS: coordinator.data.get(DATA_METERS, {}),
            DATA_PAYMENTS: coordinator.data.get(DATA_PAYMENTS, {}),
            DATA_KVIT: coordinator.data.get(DATA_KVIT, {}),
        }

    return {
        "config_entry": config_data,
        "auth": auth_info,
        "coordinator": coordinator_info,
        "data": raw_data,
    }
