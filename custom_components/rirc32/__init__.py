"""The RIRC integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .api import RIRCApi
from .auth import RIRCAuth
from .const import DOMAIN, PLATFORMS
from .coordinator import RIRCCoordinator
from .exceptions import RIRCConnectionError
from .services import async_setup_services, async_unload_services
from .ssl_chain import async_create_rirc_session

_LOGGER = logging.getLogger(__name__)

type RIRCConfigEntry = ConfigEntry[RIRCCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the RIRC integration (domain-level, once)."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RIRCConfigEntry) -> bool:
    """Set up RIRC from a config entry."""
    try:
        session = await async_create_rirc_session(hass)
    except RIRCConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    auth = RIRCAuth(session)
    api = RIRCApi(auth, session)

    coordinator = RIRCCoordinator(hass, api, entry)

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: RIRCConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Unload services if this is the last entry
    if unload_ok:
        remaining = hass.config_entries.async_entries(DOMAIN)
        if len(remaining) <= 1:
            await async_unload_services(hass)

    return unload_ok
