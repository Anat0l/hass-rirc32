"""Service handlers for the RIRC integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er

from .const import ATTR_METER_ID, ATTR_METER_SERIAL, DOMAIN
from .coordinator import RIRCCoordinator
from .exceptions import RIRCError

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH = "refresh"
SERVICE_SEND_READINGS = "send_readings"

SERVICE_SEND_READINGS_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("value_entity_id"): cv.entity_id,
    }
)


def _get_coordinator(hass: HomeAssistant) -> RIRCCoordinator:
    """Get the first available RIRC coordinator.

    Raises HomeAssistantError if none is found.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if hasattr(entry, "runtime_data") and isinstance(
            entry.runtime_data, RIRCCoordinator
        ):
            return entry.runtime_data
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="no_integration",
    )


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up RIRC services."""

    async def handle_refresh(call: ServiceCall) -> None:
        """Handle the refresh service call."""
        coordinator = _get_coordinator(hass)
        _LOGGER.debug("Service call: refresh")
        try:
            await coordinator.async_force_refresh()
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to refresh RIRC data: {err}"
            ) from err

    async def handle_send_readings(call: ServiceCall) -> None:
        """Handle the send_readings service call."""
        coordinator = _get_coordinator(hass)

        device_id = call.data["device_id"]
        value_entity_id = call.data["value_entity_id"]
        if isinstance(value_entity_id, list):
            value_entity_id = value_entity_id[0] if value_entity_id else ""

        # Find meter reading entity from the selected device
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)

        device = dev_reg.async_get(device_id)
        if device is None:
            raise ServiceValidationError(
                f"Device not found: {device_id}",
                translation_domain=DOMAIN,
                translation_key="device_not_found",
            )

        # Find meter reading sensors belonging to this device
        meter_entities = [
            entry
            for entry in er.async_entries_for_device(ent_reg, device_id)
            if entry.domain == "sensor" and entry.translation_key == "meter_reading"
        ]

        if not meter_entities:
            raise ServiceValidationError(
                f"No meter reading sensors found for device {device_id} ({device.name})",
                translation_domain=DOMAIN,
                translation_key="no_meter_sensors",
            )

        # Get the value from the selected sensor
        value_state = hass.states.get(value_entity_id)
        if value_state is None:
            raise ServiceValidationError(
                f"Value entity not found: {value_entity_id}",
                translation_domain=DOMAIN,
                translation_key="entity_not_found",
            )

        try:
            value = float(value_state.state)
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(
                f"Entity {value_entity_id} has no valid numeric value (state={value_state.state!r})",
                translation_domain=DOMAIN,
                translation_key="invalid_value",
            ) from err

        # Submit for each meter reading sensor on this device
        for meter_entry in meter_entities:
            state = hass.states.get(meter_entry.entity_id)
            if state is None:
                continue

            attrs: dict[str, Any] = state.attributes
            account_id = attrs.get("account_id")
            meter_serial = attrs.get(ATTR_METER_SERIAL)
            meter_id = attrs.get(ATTR_METER_ID)

            if not account_id or not meter_serial or not meter_id:
                _LOGGER.warning(
                    "Skipping %s — missing meter attributes",
                    meter_entry.entity_id,
                )
                continue

            _LOGGER.debug(
                "Service call: send_readings device=%s value_from=%s "
                "(ls=%s, serial=%s, id=%s, val=%s)",
                device_id,
                value_entity_id,
                account_id,
                meter_serial,
                meter_id,
                value,
            )

            try:
                await coordinator.async_send_reading(
                    account_id, meter_serial, meter_id, value
                )
            except RIRCError as err:
                raise HomeAssistantError(
                    f"Failed to submit reading for meter {meter_serial}: {err}"
                ) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        handle_refresh,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_READINGS,
        handle_send_readings,
        schema=SERVICE_SEND_READINGS_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload RIRC services."""
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    hass.services.async_remove(DOMAIN, SERVICE_SEND_READINGS)
