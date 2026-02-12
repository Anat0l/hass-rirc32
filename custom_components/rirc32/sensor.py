"""Sensor platform for the RIRC integration."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .__init__ import RIRCConfigEntry
from .const import (
    ATTR_ADDRESS,
    ATTR_KVIT_DEBT,
    ATTR_KVIT_NAME,
    ATTR_KVIT_PAID,
    ATTR_KVIT_PERIOD,
    ATTR_KVIT_TO_PAY,
    ATTR_LAST_READING,
    ATTR_METER_ID,
    ATTR_METER_NAME,
    ATTR_METER_SERIAL,
    ATTR_METER_TARIFF,
    DATA_ACCOUNTS,
    DATA_KVIT,
    DATA_METERS,
    DATA_PAYMENTS,
    DOMAIN,
)
from .coordinator import RIRCCoordinator
from .entity import RIRCEntity, RIRCMeterEntity
from .helpers import (
    extract_meter_type_icon,
    find_last_nonzero_payment,
    parse_float,
)

_LOGGER = logging.getLogger(__name__)

# Limit concurrent updates — single API client shared across entities
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RIRCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RIRC sensors from a config entry."""
    coordinator = entry.runtime_data

    known_accounts: set[str] = set()
    known_meters: set[str] = set()

    def _check_new_entities() -> None:
        """Check for new accounts/meters and create entities dynamically."""
        if not coordinator.data:
            return

        new_entities: list[SensorEntity] = []

        accounts = coordinator.data.get(DATA_ACCOUNTS, [])
        meters_data = coordinator.data.get(DATA_METERS, {})

        for account in accounts:
            account_id = account["account_id"]
            address = account.get("address", "")

            if account_id not in known_accounts:
                known_accounts.add(account_id)

                # Account-level sensors (always created)
                new_entities.append(
                    RIRCAccountSensor(coordinator, account_id, address)
                )
                new_entities.append(
                    RIRCBalanceSensor(coordinator, account_id, address)
                )
                new_entities.append(
                    RIRCReceiptNumberSensor(coordinator, account_id, address)
                )
                new_entities.append(
                    RIRCLastPaymentDateSensor(coordinator, account_id, address)
                )
                new_entities.append(
                    RIRCLastPaymentAmountSensor(coordinator, account_id, address)
                )
                new_entities.append(
                    RIRCLastUpdateSensor(coordinator, account_id, address)
                )

            # Per-meter sensors (track by account + serial)
            for meter in meters_data.get(account_id, []):
                meter_key = f"{account_id}_{meter.get('meter_serial', '')}"
                if meter_key not in known_meters:
                    known_meters.add(meter_key)
                    new_entities.append(
                        RIRCMeterReadingSensor(
                            coordinator, account_id, address, meter
                        )
                    )
                    new_entities.append(
                        RIRCTariffSensor(
                            coordinator, account_id, address, meter
                        )
                    )

        if new_entities:
            async_add_entities(new_entities)

    # Create entities for currently known data
    _check_new_entities()

    # Re-check on every coordinator update so new accounts/meters are picked up
    entry.async_on_unload(
        coordinator.async_add_listener(_check_new_entities)
    )


class RIRCAccountSensor(RIRCEntity, SensorEntity):
    """Sensor showing account information."""

    _attr_icon = "mdi:home-city"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
    ) -> None:
        """Initialize the account sensor."""
        super().__init__(coordinator, account_id, address)
        self._attr_unique_id = f"{DOMAIN}_{account_id}_account"
        self._attr_translation_key = "account"

    @property
    def native_value(self) -> str:
        """Return the account ID as value."""
        return self._account_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {
            ATTR_ADDRESS: self._address,
        }

        if self.coordinator.data:
            meters = self.coordinator.data.get(DATA_METERS, {})
            account_meters = meters.get(self._account_id, [])
            attrs["meter_count"] = len(account_meters)

            kvit = self.coordinator.data.get(DATA_KVIT, {})
            account_kvit = kvit.get(self._account_id, [])
            if account_kvit:
                latest = account_kvit[0]
                attrs[ATTR_KVIT_NAME] = latest.get("kvitName", "")
                attrs[ATTR_KVIT_PERIOD] = latest.get("period", "")
                attrs[ATTR_KVIT_TO_PAY] = latest.get("kvitOplSt", "")
                attrs[ATTR_KVIT_PAID] = latest.get("kvitOplFn", "")
                attrs[ATTR_KVIT_DEBT] = latest.get("kvitDolg", "")

        return attrs


class RIRCMeterReadingSensor(RIRCMeterEntity, SensorEntity):
    """Sensor showing the last meter reading."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
        meter_data: dict[str, Any],
    ) -> None:
        """Initialize the meter reading sensor."""
        super().__init__(coordinator, account_id, address, meter_data)
        serial = meter_data.get("meter_serial", "")
        self._attr_unique_id = f"{DOMAIN}_{account_id}_{serial}_reading"
        self._attr_translation_key = "meter_reading"
        self._attr_icon = extract_meter_type_icon(
            meter_data.get("meter_name", "")
        )

        # Set unit of measurement based on meter type
        name_lower = meter_data.get("meter_name", "").lower()
        if "вода" in name_lower:
            self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
            self._attr_device_class = SensorDeviceClass.WATER
        elif "газ" in name_lower:
            self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
            self._attr_device_class = SensorDeviceClass.GAS
        elif "электр" in name_lower or "свет" in name_lower:
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_device_class = SensorDeviceClass.ENERGY
        else:
            self._attr_native_unit_of_measurement = None

    @property
    def native_value(self) -> float | None:
        """Return the current meter reading."""
        meter = self._get_current_meter_data()
        if meter:
            reading = meter.get("last_reading", "")
            if reading:
                return parse_float(reading)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        meter = self._get_current_meter_data()
        if not meter:
            meter = {}

        return {
            ATTR_METER_ID: meter.get("meter_id", self._meter_id),
            ATTR_METER_SERIAL: meter.get("meter_serial", self._meter_serial),
            ATTR_METER_NAME: meter.get("meter_name", self._meter_name),
            ATTR_METER_TARIFF: meter.get("meter_tariff", self._meter_tariff),
            ATTR_LAST_READING: meter.get("last_reading", ""),
            "account_id": self._account_id,
        }


class RIRCTariffSensor(RIRCMeterEntity, SensorEntity):
    """Sensor showing the meter tariff."""

    _attr_icon = "mdi:cash"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "RUB/m³"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
        meter_data: dict[str, Any],
    ) -> None:
        """Initialize the tariff sensor."""
        super().__init__(coordinator, account_id, address, meter_data)
        serial = meter_data.get("meter_serial", "")
        self._attr_unique_id = f"{DOMAIN}_{account_id}_{serial}_tariff"
        self._attr_translation_key = "tariff"

    @property
    def native_value(self) -> float | None:
        """Return the tariff value."""
        meter = self._get_current_meter_data()
        tariff_str = ""
        if meter:
            tariff_str = meter.get("meter_tariff", "")
        if not tariff_str:
            tariff_str = self._meter_tariff

        return parse_float(tariff_str)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        meter = self._get_current_meter_data()
        if not meter:
            meter = {}

        return {
            ATTR_METER_SERIAL: meter.get("meter_serial", self._meter_serial),
            ATTR_METER_NAME: meter.get("meter_name", self._meter_name),
            "account_id": self._account_id,
        }


class RIRCLastPaymentDateSensor(RIRCEntity, SensorEntity):
    """Sensor showing the date of the last payment."""

    _attr_icon = "mdi:calendar-check"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
    ) -> None:
        """Initialize the last payment date sensor."""
        super().__init__(coordinator, account_id, address)
        self._attr_unique_id = f"{DOMAIN}_{account_id}_last_payment_date"
        self._attr_translation_key = "last_payment_date"

    def _get_last_paid(self) -> dict[str, Any] | None:
        """Get the last payment with amount > 0."""
        if not self.coordinator.data:
            return None
        payments = self.coordinator.data.get(DATA_PAYMENTS, {})
        return find_last_nonzero_payment(payments.get(self._account_id, []))

    @property
    def native_value(self) -> datetime.date | None:
        """Return the last payment date (with amount > 0)."""
        entry = self._get_last_paid()
        if entry is None:
            return None

        dt_str = entry.get("paysDateTime", "")
        if not dt_str:
            return None

        try:
            date_part = dt_str.split("T")[0] if "T" in dt_str else dt_str
            return datetime.date.fromisoformat(date_part)
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        entry = self._get_last_paid()
        if entry is None:
            return {}
        return {
            "oppl_name": entry.get("opplName", ""),
            "account": entry.get("account", ""),
            "amount": entry.get("amount", 0),
        }


class RIRCLastPaymentAmountSensor(RIRCEntity, SensorEntity):
    """Sensor showing the amount of the last payment."""

    _attr_icon = "mdi:credit-card-check-outline"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "RUB"

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
    ) -> None:
        """Initialize the last payment amount sensor."""
        super().__init__(coordinator, account_id, address)
        self._attr_unique_id = f"{DOMAIN}_{account_id}_last_payment_amount"
        self._attr_translation_key = "last_payment_amount"

    def _get_last_paid(self) -> dict[str, Any] | None:
        """Get the last payment with amount > 0."""
        if not self.coordinator.data:
            return None
        payments = self.coordinator.data.get(DATA_PAYMENTS, {})
        return find_last_nonzero_payment(payments.get(self._account_id, []))

    @property
    def native_value(self) -> float | None:
        """Return the last payment amount (> 0)."""
        entry = self._get_last_paid()
        if entry is None:
            return None
        return float(entry["amount"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        entry = self._get_last_paid()
        if entry is None:
            return {}
        attrs: dict[str, Any] = {
            "pays_date_time": entry.get("paysDateTime", ""),
            "oppl_name": entry.get("opplName", ""),
            "account": entry.get("account", ""),
        }
        ofd_url = entry.get("ofdUrl")
        if ofd_url:
            attrs["ofd_url"] = ofd_url
        return attrs


class RIRCBalanceSensor(RIRCEntity, SensorEntity):
    """Sensor showing current balance (debt) for an account."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "RUB"
    _attr_icon = "mdi:currency-rub"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
    ) -> None:
        """Initialize the balance sensor."""
        super().__init__(coordinator, account_id, address)
        self._attr_unique_id = f"{DOMAIN}_{account_id}_balance"
        self._attr_translation_key = "balance"

    @property
    def native_value(self) -> float | None:
        """Return the current balance (amount to pay)."""
        if not self.coordinator.data:
            return None

        kvit = self.coordinator.data.get(DATA_KVIT, {})
        account_kvit = kvit.get(self._account_id, [])
        if not account_kvit:
            return None

        latest = account_kvit[0]
        return parse_float(latest.get("kvitOplSt"), default=None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        attrs: dict[str, Any] = {}
        if not self.coordinator.data:
            return attrs

        kvit = self.coordinator.data.get(DATA_KVIT, {})
        account_kvit = kvit.get(self._account_id, [])
        if account_kvit:
            latest = account_kvit[0]
            attrs[ATTR_KVIT_NAME] = latest.get("kvitName", "")
            attrs[ATTR_KVIT_PERIOD] = latest.get("period", "")
            attrs[ATTR_KVIT_TO_PAY] = latest.get("kvitOplSt", "")
            attrs[ATTR_KVIT_PAID] = latest.get("kvitOplFn", "")
            attrs[ATTR_KVIT_DEBT] = latest.get("kvitDolg", "")

        return attrs


class RIRCReceiptNumberSensor(RIRCEntity, SensorEntity):
    """Sensor showing the latest receipt (kvitantsiya) number."""

    _attr_icon = "mdi:file-document-outline"

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
    ) -> None:
        """Initialize the receipt number sensor."""
        super().__init__(coordinator, account_id, address)
        self._attr_unique_id = f"{DOMAIN}_{account_id}_receipt_number"
        self._attr_translation_key = "receipt_number"

    @property
    def native_value(self) -> str | None:
        """Return the receipt number."""
        if not self.coordinator.data:
            return None

        kvit = self.coordinator.data.get(DATA_KVIT, {})
        account_kvit = kvit.get(self._account_id, [])
        if not account_kvit:
            return None

        latest = account_kvit[0]
        kvit_name = latest.get("kvitName", "")

        if not kvit_name:
            return None

        # Extract just the receipt number, e.g.
        # "Квитанция за ЖКУ 01 00000000 2601" -> "01 00000000 2601"
        prefix = "Квитанция за ЖКУ "
        if kvit_name.startswith(prefix):
            return kvit_name[len(prefix):]

        return kvit_name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        if not self.coordinator.data:
            return {}

        kvit = self.coordinator.data.get(DATA_KVIT, {})
        account_kvit = kvit.get(self._account_id, [])
        if not account_kvit:
            return {}

        latest = account_kvit[0]
        return {
            ATTR_KVIT_NAME: latest.get("kvitName", ""),
            ATTR_KVIT_PERIOD: latest.get("period", ""),
            ATTR_KVIT_TO_PAY: latest.get("kvitOplSt", ""),
            ATTR_KVIT_PAID: latest.get("kvitOplFn", ""),
            ATTR_KVIT_DEBT: latest.get("kvitDolg", ""),
        }


class RIRCLastUpdateSensor(RIRCEntity, SensorEntity):
    """Sensor showing the date and time of the last successful data update."""

    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: RIRCCoordinator,
        account_id: str,
        address: str,
    ) -> None:
        """Initialize the last update sensor."""
        super().__init__(coordinator, account_id, address)
        self._attr_unique_id = f"{DOMAIN}_{account_id}_last_update"
        self._attr_translation_key = "last_update"

    @property
    def native_value(self) -> datetime.datetime | None:
        """Return the timestamp of the last successful data refresh."""
        return self.coordinator.last_successful_update
