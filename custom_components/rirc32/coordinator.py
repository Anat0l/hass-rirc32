"""Data update coordinator for the RIRC integration."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .api import RIRCApi
from .const import (
    CONF_LOGIN,
    CONF_PASSWORD,
    DATA_ACCOUNTS,
    DATA_KVIT,
    DATA_METERS,
    DATA_PAYMENTS,
    DOMAIN,
    EVENT_REFRESH_COMPLETED,
    EVENT_REFRESH_FAILED,
    EVENT_SEND_READINGS_COMPLETED,
    EVENT_SEND_READINGS_FAILED,
)
from .exceptions import RIRCAuthError, RIRCError

_LOGGER = logging.getLogger(__name__)

# Data changes rarely (once a month); poll once per day to avoid overloading the service
UPDATE_INTERVAL = timedelta(hours=24)


class RIRCCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage data fetching from RIRC.

    Data is polled once per day.  On failure the previous data is kept
    so that sensors stay available.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        api: RIRCApi,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.api = api
        self._login = config_entry.data[CONF_LOGIN]
        self._password = config_entry.data[CONF_PASSWORD]
        self._last_update_success = True
        self.last_successful_update: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from RIRC.

        Returns dict with:
            accounts: list of account dicts
            meters: dict[account_id] -> list of meter dicts
            payments: dict[account_id] -> list of payment dicts
            kvit: dict[account_id] -> list of kvit dicts
        """
        last_error: Exception | None = None
        last_auth_error: RIRCAuthError | None = None

        for attempt in range(2):
            try:
                data = await self._fetch_data()
                # Log recovery exactly once
                if not self._last_update_success:
                    _LOGGER.info("Connection to RIRC restored")
                    self._last_update_success = True
                # Clear any auth repair issue on success
                ir.async_delete_issue(self.hass, DOMAIN, "auth_failed")
                self.last_successful_update = utcnow()
                return data
            except RIRCAuthError as err:
                last_auth_error = err
                last_error = err
                if attempt == 0:
                    _LOGGER.warning(
                        "Session expired (server-side?), re-authenticating: %s",
                        err,
                    )
                    self.api.invalidate_session()
                    continue
                break
            except Exception as err:
                last_error = err
                break

        # Log failure exactly once
        if self._last_update_success:
            _LOGGER.warning(
                "Unable to reach RIRC (%s); sensors will keep their last known values",
                last_error,
            )
            self._last_update_success = False

        # Create a repair issue for auth failures
        if last_auth_error:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "auth_failed",
                is_fixable=False,
                issue_domain=DOMAIN,
                severity=ir.IssueSeverity.ERROR,
                translation_key="auth_failed",
            )

        # On failure: keep existing data so sensors stay available
        if self.data is not None:
            return self.data

        # Initial load failed - must raise
        if last_auth_error:
            raise ConfigEntryAuthFailed(
                f"Authentication failed: {last_auth_error}"
            ) from last_auth_error
        raise UpdateFailed(f"Initial data fetch failed: {last_error}") from last_error

    async def _fetch_data(self) -> dict[str, Any]:
        """Fetch data from RIRC (single attempt)."""
        try:
            # Ensure we're authenticated
            await self.api.async_ensure_auth(self._login, self._password)

            # Get accounts
            accounts = await self.api.async_get_accounts()
            _LOGGER.debug("Found %d accounts", len(accounts))

            # Get meters and payment data for each account
            meters: dict[str, list[dict[str, Any]]] = {}
            payments: dict[str, list[dict[str, Any]]] = {}
            kvit_data: dict[str, list[dict[str, Any]]] = {}

            for account in accounts:
                account_id = account["account_id"]
                ls_type = account.get("ls_type", "1")

                # Meters
                try:
                    account_meters = await self.api.async_get_meters(account_id)
                    meters[account_id] = account_meters
                    _LOGGER.debug(
                        "Account %s: %d meters",
                        account_id,
                        len(account_meters),
                    )
                except RIRCError as err:
                    _LOGGER.warning(
                        "Failed to get meters for %s: %s",
                        account_id,
                        err,
                    )
                    meters[account_id] = []

                # Payment history
                try:
                    account_payments = await self.api.async_get_payment_history(
                        account_id
                    )
                    payments[account_id] = account_payments
                except RIRCError as err:
                    _LOGGER.debug(
                        "Failed to get payments for %s: %s",
                        account_id,
                        err,
                    )
                    payments[account_id] = []

                # Kvit list — period is required by the API (YYMM format)
                try:
                    today = date.today()
                    current_period = f"{today.year % 100:02d}{today.month:02d}"
                    account_kvit = await self.api.async_get_kvit_list(
                        account_id, ls_type, period=current_period
                    )
                    # If current month has no kvit, try previous month
                    if not account_kvit:
                        if today.month == 1:
                            prev_period = f"{(today.year - 1) % 100:02d}12"
                        else:
                            prev_period = f"{today.year % 100:02d}{today.month - 1:02d}"
                        account_kvit = await self.api.async_get_kvit_list(
                            account_id, ls_type, period=prev_period
                        )
                    kvit_data[account_id] = account_kvit
                except RIRCError as err:
                    _LOGGER.debug(
                        "Failed to get kvit for %s: %s",
                        account_id,
                        err,
                    )
                    kvit_data[account_id] = []

            result = {
                DATA_ACCOUNTS: accounts,
                DATA_METERS: meters,
                DATA_PAYMENTS: payments,
                DATA_KVIT: kvit_data,
            }

            # Remove devices for accounts that no longer exist in the API
            self._async_remove_stale_devices(accounts)

            self.hass.bus.async_fire(
                EVENT_REFRESH_COMPLETED,
                {"accounts": len(accounts)},
            )

            return result

        except RIRCAuthError:
            # Let it propagate to _async_update_data for retry with re-login
            raise
        except RIRCError as err:
            self.hass.bus.async_fire(
                EVENT_REFRESH_FAILED,
                {"error": str(err)},
            )
            raise UpdateFailed(f"Error fetching RIRC data: {err}") from err

    def _async_remove_stale_devices(
        self,
        accounts: list[dict[str, Any]],
    ) -> None:
        """Remove devices whose account IDs are no longer present in the API."""
        dev_reg = dr.async_get(self.hass)
        current_ids = {a["account_id"] for a in accounts}

        for device in dr.async_entries_for_config_entry(
            dev_reg, self.config_entry.entry_id
        ):
            # Each device has identifiers like {(DOMAIN, account_id)}
            for domain, identifier in device.identifiers:
                if domain == DOMAIN and identifier not in current_ids:
                    _LOGGER.info(
                        "Removing stale device %s (account %s no longer exists)",
                        device.name,
                        identifier,
                    )
                    dev_reg.async_remove_device(device.id)
                    break

    async def async_send_reading(
        self,
        account_id: str,
        meter_serial: str,
        meter_id: str,
        value: float,
    ) -> bool:
        """Send a meter reading."""
        try:
            await self.api.async_ensure_auth(self._login, self._password)
            result = await self.api.async_submit_reading(
                account_id, meter_serial, meter_id, value
            )

            self.hass.bus.async_fire(
                EVENT_SEND_READINGS_COMPLETED,
                {
                    "account_id": account_id,
                    "meter_serial": meter_serial,
                    "value": value,
                },
            )

            # Refresh data after submitting
            await self.async_request_refresh()

            return result

        except RIRCAuthError as err:
            _LOGGER.warning("Session expired during send_reading, retrying: %s", err)
            self.api.invalidate_session()
            try:
                await self.api.async_ensure_auth(self._login, self._password)
                result = await self.api.async_submit_reading(
                    account_id, meter_serial, meter_id, value
                )
                self.hass.bus.async_fire(
                    EVENT_SEND_READINGS_COMPLETED,
                    {"account_id": account_id, "meter_serial": meter_serial, "value": value},
                )
                await self.async_request_refresh()
                return result
            except RIRCError as retry_err:
                self.hass.bus.async_fire(
                    EVENT_SEND_READINGS_FAILED,
                    {
                        "account_id": account_id,
                        "meter_serial": meter_serial,
                        "error": str(retry_err),
                    },
                )
                raise retry_err
        except RIRCError as err:
            self.hass.bus.async_fire(
                EVENT_SEND_READINGS_FAILED,
                {
                    "account_id": account_id,
                    "meter_serial": meter_serial,
                    "error": str(err),
                },
            )
            raise

    async def async_force_refresh(self) -> None:
        """Force a data refresh."""
        await self.async_request_refresh()
