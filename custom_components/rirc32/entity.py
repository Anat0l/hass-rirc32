"""Base entity for the RIRC integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_METERS, DOMAIN
from .coordinator import RIRCCoordinator


class RIRCEntity(CoordinatorEntity[RIRCCoordinator]):
    """Base class for RIRC entities.

    Always available when coordinator has data (update is on-request only).
    """

    _attr_has_entity_name = True

    @property
    def available(self) -> bool:
        """Entity is available when we have data."""
        return self.coordinator.data is not None

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._account_id = account_id
        self._address = address

    def _build_device_name(self) -> str:
        """Build device name including meter info.

        """
        base = f"Лицевой счет {self._account_id}"

        if self.coordinator.data:
            meters = self.coordinator.data.get(DATA_METERS, {})
            account_meters = meters.get(self._account_id, [])
            if account_meters:
                meter_parts = []
                for m in account_meters:
                    serial = m.get("meter_serial", "")
                    name = m.get("meter_name", "")
                    if serial:
                        meter_parts.append(
                            f"{serial} {name}" if name else serial
                        )
                if meter_parts:
                    return f"{base} ({', '.join(meter_parts)})"

        return base

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._account_id)},
            name=self._build_device_name(),
            manufacturer="ООО «РИРЦ» Брянской области",
            model="Лицевой счёт",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://lk.rirc.ru",
        )


class RIRCMeterEntity(RIRCEntity):
    """Base class for meter-specific entities."""

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
        meter_data: dict[str, Any],
    ) -> None:
        """Initialize the meter entity."""
        super().__init__(coordinator, account_id, address)
        self._meter_id = meter_data.get("meter_id", "")
        self._meter_serial = meter_data.get("meter_serial", "")
        self._meter_name = meter_data.get("meter_name", "")
        self._meter_tariff = meter_data.get("meter_tariff", "")

    def _get_current_meter_data(self) -> dict[str, Any] | None:
        """Get current meter data from coordinator."""
        if not self.coordinator.data:
            return None
        meters = self.coordinator.data.get(DATA_METERS, {})
        account_meters = meters.get(self._account_id, [])
        for meter in account_meters:
            if meter.get("meter_serial") == self._meter_serial:
                return meter
        return None
