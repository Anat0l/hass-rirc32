"""Button platform for the RIRC integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .__init__ import RIRCConfigEntry
from .const import DATA_ACCOUNTS, DOMAIN
from .coordinator import RIRCCoordinator
from .entity import RIRCEntity

_LOGGER = logging.getLogger(__name__)

# Limit concurrent updates — single API client shared across entities
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RIRCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RIRC buttons from a config entry."""
    coordinator = entry.runtime_data
    button_created = False

    def _check_new_entities() -> None:
        """Create refresh button once the first account appears."""
        nonlocal button_created
        if button_created or not coordinator.data:
            return

        accounts = coordinator.data.get(DATA_ACCOUNTS, [])
        if accounts:
            first_account = accounts[0]
            async_add_entities(
                [
                    RIRCRefreshButton(
                        coordinator,
                        first_account["account_id"],
                        first_account.get("address", ""),
                    )
                ]
            )
            button_created = True

    _check_new_entities()

    entry.async_on_unload(
        coordinator.async_add_listener(_check_new_entities)
    )


class RIRCRefreshButton(RIRCEntity, ButtonEntity):
    """Button to force refresh data from RIRC."""

    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator, account_id, address)
        self._attr_unique_id = f"{DOMAIN}_refresh"
        self._attr_translation_key = "refresh"

    async def async_press(self) -> None:
        """Handle button press."""
        _LOGGER.debug("Manual refresh triggered")
        await self.coordinator.async_force_refresh()
