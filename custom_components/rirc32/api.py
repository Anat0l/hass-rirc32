"""API client for RIRC integration."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from .auth import RIRCAuth
from .const import (
    BASE_URL,
    ENDPOINT_KVIT_LIST,
    ENDPOINT_LS_LIST,
    ENDPOINT_METERS,
    ENDPOINT_PAYMENT_HISTORY,
    ENDPOINT_SUBMIT_READING,
    FIELD_LS,
    FIELD_METHOD,
    FIELD_SCH,
    FIELD_SCH_SER,
    FIELD_SCH_VAL,
)
from .exceptions import (
    RIRCApiError,
    RIRCAuthError,
    RIRCConnectionError,
    RIRCTimeoutError,
)

_LOGGER = logging.getLogger(__name__)


class RIRCApi:
    """API client for RIRC personal cabinet."""

    def __init__(self, auth: RIRCAuth, session: aiohttp.ClientSession) -> None:
        """Initialize API client."""
        self._auth = auth
        self._session = session

    async def async_login(self, login: str, password: str) -> dict[str, Any]:
        """Login and return session info."""
        return await self._auth.async_login(login, password)

    async def async_ensure_auth(self, login: str, password: str) -> None:
        """Ensure authenticated."""
        await self._auth.async_ensure_authenticated(login, password)

    def invalidate_session(self) -> None:
        """Invalidate the current authentication session."""
        self._auth.invalidate_session()

    @property
    def auth_authenticated(self) -> bool:
        """Return whether we are currently authenticated."""
        return self._auth.authenticated

    @property
    def auth_sid(self) -> str | None:
        """Return the current session ID."""
        return self._auth.sid

    @property
    def auth_user_name(self) -> str | None:
        """Return the authenticated user name."""
        return self._auth.user_name

    async def _async_get(self, path: str, **kwargs: Any) -> str:
        """Perform authenticated GET request and return HTML text."""
        url = f"{BASE_URL}{path}"

        _LOGGER.debug(">>> GET %s", url)

        try:
            async with self._session.get(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
                **kwargs,
            ) as resp:
                status = resp.status
                final_url = str(resp.url)
                body = await resp.text()

                _LOGGER.debug(
                    "<<< GET %s | status=%s | final_url=%s | body=%d chars",
                    path,
                    status,
                    final_url,
                    len(body),
                )
                _LOGGER.debug(
                    "<<< GET %s | headers=%s",
                    path,
                    dict(resp.headers),
                )
                _LOGGER.debug(
                    "<<< GET %s | body_preview: %s",
                    path,
                    body[:2000],
                )

                if status == 200:
                    if "signin" in final_url:
                        _LOGGER.debug("Redirected to signin — session expired")
                        raise RIRCAuthError("Session expired")
                    return body

                if "signin" in final_url:
                    raise RIRCAuthError("Session expired")
                raise RIRCApiError(
                    f"Unexpected status {status} for GET {path}"
                )
        except aiohttp.ClientConnectorError as err:
            _LOGGER.debug("Connection error for GET %s: %s", path, err)
            raise RIRCConnectionError(str(err)) from err
        except aiohttp.ServerTimeoutError as err:
            _LOGGER.debug("Timeout for GET %s: %s", path, err)
            raise RIRCTimeoutError(str(err)) from err

    async def _async_get_json(
        self, path: str, params: dict[str, str] | None = None
    ) -> Any:
        """Perform authenticated GET request expecting JSON response."""
        url = f"{BASE_URL}{path}"

        _LOGGER.debug(">>> GET JSON %s | params=%s", url, params)

        try:
            async with self._session.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json",
                },
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                status = resp.status
                body = await resp.text()

                _LOGGER.debug(
                    "<<< GET JSON %s | status=%s | body=%d chars",
                    path,
                    status,
                    len(body),
                )
                _LOGGER.debug(
                    "<<< GET JSON %s | headers=%s",
                    path,
                    dict(resp.headers),
                )
                _LOGGER.debug(
                    "<<< GET JSON %s | raw_body: %s",
                    path,
                    body[:3000],
                )

                if status == 200:
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError as err:
                        _LOGGER.debug(
                            "JSON decode error for %s: %s", path, err
                        )
                        raise RIRCApiError(
                            f"Invalid JSON from {path}: {err}"
                        ) from err

                    _LOGGER.debug(
                        "<<< GET JSON %s | parsed: %s",
                        path,
                        json.dumps(data, ensure_ascii=False, default=str)[:3000],
                    )
                    return data

                raise RIRCApiError(
                    f"Unexpected status {status} for GET {path}"
                )
        except aiohttp.ClientConnectorError as err:
            _LOGGER.debug("Connection error for GET JSON %s: %s", path, err)
            raise RIRCConnectionError(str(err)) from err
        except aiohttp.ServerTimeoutError as err:
            _LOGGER.debug("Timeout for GET JSON %s: %s", path, err)
            raise RIRCTimeoutError(str(err)) from err

    # ---- Account (LS) operations ----

    async def async_get_accounts(self) -> list[dict[str, Any]]:
        """Get list of accounts (лицевые счета) by parsing HTML."""
        html = await self._async_get(ENDPOINT_LS_LIST)
        accounts = self._parse_accounts(html)
        _LOGGER.debug("Parsed accounts: %s", accounts)
        return accounts

    @staticmethod
    def _parse_accounts(html: str) -> list[dict[str, Any]]:
        """Parse accounts from the LS list page."""
        accounts = []

        item_pattern = re.compile(
            r'<h5[^>]*>(\d{5,})</h5>\s*'
            r'<small[^>]*>([^<]+)</small>',
            re.DOTALL,
        )

        seen = set()
        for match in item_pattern.finditer(html):
            account_id = match.group(1).strip()
            address = match.group(2).strip()
            if account_id not in seen:
                seen.add(account_id)
                ls_type = "1"
                type_match = re.search(
                    rf'href="/cabinet/{account_id}/\?type=(\d+)"',
                    html,
                )
                if type_match:
                    ls_type = type_match.group(1)

                accounts.append({
                    "account_id": account_id,
                    "address": address,
                    "ls_type": ls_type,
                })

        if not accounts:
            _LOGGER.warning("No accounts found in HTML response")

        return accounts

    # ---- Meter operations ----

    async def async_get_meters(self, account_id: str) -> list[dict[str, Any]]:
        """Get meters for a specific account by parsing HTML."""
        path = ENDPOINT_METERS.format(ls=account_id)
        html = await self._async_get(path)
        meters = self._parse_meters(html, account_id)
        _LOGGER.debug("Parsed meters for %s: %s", account_id, meters)
        return meters

    @staticmethod
    def _parse_meters(html: str, account_id: str) -> list[dict[str, Any]]:
        """Parse meters from the control-meter-list page."""
        meters = []

        btn_pattern = re.compile(
            r'data-btn="pass-sch-val"\s+'
            r'data-btn-ls="(\d+)"\s+'
            r'data-btn-sch-ser="(\d+)"\s+'
            r'data-btn-sch="(\d+)"',
        )

        card_pattern = re.compile(
            r'<h5[^>]*>(\d+)</h5>\s*'
            r'<span[^>]*>([^<]*?)\s*/\s*Тариф:\s*([^<]*)</span>',
            re.DOTALL,
        )

        reading_pattern = re.compile(
            r'Пред\.\s*показание\s*</span>\s*'
            r'<h5[^>]*>([^<]+)</h5>',
            re.DOTALL,
        )

        buttons = {}
        for btn_match in btn_pattern.finditer(html):
            ls = btn_match.group(1)
            serial = btn_match.group(2)
            meter_id = btn_match.group(3)
            buttons[serial] = {"ls": ls, "meter_id": meter_id}

        cards = list(card_pattern.finditer(html))
        readings = list(reading_pattern.finditer(html))

        for i, card_match in enumerate(cards):
            serial = card_match.group(1).strip()
            name_raw = card_match.group(2).strip()
            tariff = card_match.group(3).strip()

            last_reading = ""
            if i < len(readings):
                last_reading = readings[i].group(1).strip()

            btn_data = buttons.get(serial, {})
            meter_id = btn_data.get("meter_id", "")

            meters.append({
                "meter_id": meter_id,
                "meter_serial": serial,
                "meter_name": name_raw,
                "meter_tariff": tariff,
                "last_reading": last_reading,
                "account_id": account_id,
            })

        return meters

    # ---- Submit meter reading ----

    async def async_submit_reading(
        self,
        account_id: str,
        meter_serial: str,
        meter_id: str,
        value: float,
    ) -> bool:
        """Submit a meter reading."""
        url = f"{BASE_URL}{ENDPOINT_SUBMIT_READING}"

        fields = {
            FIELD_METHOD: "PUT",
            FIELD_LS: account_id,
            FIELD_SCH_SER: meter_serial,
            FIELD_SCH: meter_id,
            FIELD_SCH_VAL: str(value),
        }

        _LOGGER.debug(">>> SUBMIT READING: POST %s | fields=%s", url, fields)

        form_data = aiohttp.FormData()
        for k, v in fields.items():
            form_data.add_field(k, v)

        try:
            async with self._session.post(
                url,
                data=form_data,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                status = resp.status
                headers = dict(resp.headers)
                body = await resp.text()

                _LOGGER.debug(
                    "<<< SUBMIT READING: status=%s | headers=%s",
                    status,
                    headers,
                )
                _LOGGER.debug(
                    "<<< SUBMIT READING BODY (%d chars): %s",
                    len(body),
                    body[:2000],
                )

                if status in (200, 302):
                    if status == 302:
                        location = headers.get("Location", "")
                        _LOGGER.debug("Redirect to: %s", location)
                        if "signin" in location.lower():
                            raise RIRCAuthError("Session expired")
                    _LOGGER.info(
                        "Meter reading submitted: %s = %s",
                        meter_serial,
                        value,
                    )
                    return True

                raise RIRCApiError(
                    f"Failed to submit reading: status {status}, body: {body[:200]}"
                )

        except aiohttp.ClientConnectorError as err:
            _LOGGER.debug("Connection error submitting reading: %s", err)
            raise RIRCConnectionError(str(err)) from err
        except aiohttp.ServerTimeoutError as err:
            _LOGGER.debug("Timeout submitting reading: %s", err)
            raise RIRCTimeoutError(str(err)) from err

    # ---- Payment history ----

    async def async_get_payment_history(
        self, account_id: str
    ) -> list[dict[str, Any]]:
        """Get payment history for an account."""
        try:
            data = await self._async_get_json(
                ENDPOINT_PAYMENT_HISTORY,
                params={"lsId": account_id},
            )
            if data is None:
                return []
            if isinstance(data, list):
                return data
            return []
        except RIRCApiError:
            _LOGGER.debug("Payment history not available for %s", account_id)
            return []

    # ---- Receipt (kvit) list ----

    async def async_get_kvit_list(
        self,
        account_id: str,
        ls_type: str = "1",
        period: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get receipt list for an account."""
        params = {
            "lsId": account_id,
            "lsType": ls_type,
        }
        if period:
            params["period"] = period

        try:
            data = await self._async_get_json(
                ENDPOINT_KVIT_LIST,
                params=params,
            )
            if data is None:
                return []
            if isinstance(data, list):
                return data
            return []
        except RIRCApiError:
            _LOGGER.debug("Kvit list not available for %s", account_id)
            return []

