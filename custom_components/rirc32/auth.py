"""Authentication module for RIRC integration."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import aiohttp

from .const import (
    BASE_URL,
    COOKIE_SID,
    COOKIE_UL,
    COOKIE_UN,
    ENDPOINT_LOGIN,
    FIELD_LOGIN,
    FIELD_PASSWORD,
)
from .exceptions import RIRCAuthError, RIRCConnectionError, RIRCTimeoutError
from .ssl_chain import RircSession

_LOGGER = logging.getLogger(__name__)

# Session token validity (seconds) - re-login proactively before server expires us
TOKEN_EXPIRY = 1800  # 30 min (server may expire earlier)


class RIRCAuth:
    """Handle authentication for RIRC personal cabinet."""

    def __init__(self, session: RircSession) -> None:
        """Initialize the auth handler."""
        self._session = session
        self._authenticated = False
        self._auth_time: float = 0
        self._sid: str | None = None
        self._user_login: str | None = None
        self._user_name: str | None = None

    @property
    def authenticated(self) -> bool:
        """Return whether we are authenticated."""
        if not self._authenticated:
            return False
        if time.time() - self._auth_time > TOKEN_EXPIRY:
            _LOGGER.debug("Session expired (age > %ds)", TOKEN_EXPIRY)
            self._authenticated = False
            return False
        return True

    @property
    def sid(self) -> str | None:
        """Return the session ID."""
        return self._sid

    @property
    def user_name(self) -> str | None:
        """Return the user name."""
        return self._user_name

    async def async_login(self, login: str, password: str) -> dict[str, Any]:
        """Log in to RIRC and return session info."""
        url = f"{BASE_URL}{ENDPOINT_LOGIN}"

        _LOGGER.debug(
            ">>> LOGIN REQUEST: POST %s | fields: %s=***, %s=***",
            url,
            FIELD_LOGIN,
            FIELD_PASSWORD,
        )

        data = aiohttp.FormData()
        data.add_field(FIELD_LOGIN, login)
        data.add_field(FIELD_PASSWORD, password)

        try:
            async with self._session.post(
                url,
                data=data,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                status = resp.status
                headers = dict(resp.headers)
                body = await resp.text()

                _LOGGER.debug(
                    "<<< LOGIN RESPONSE: status=%s | headers=%s",
                    status,
                    headers,
                )
                _LOGGER.debug(
                    "<<< LOGIN BODY (%d chars): %s",
                    len(body),
                    body[:1000],
                )

                # Log cookies
                cookies = self._session.cookie_jar.filter_cookies(
                    aiohttp.typedefs.URL(BASE_URL)
                )
                _LOGGER.debug(
                    "<<< LOGIN COOKIES: %s",
                    {n: m.value for n, m in cookies.items()},
                )

                if status == 302:
                    location = headers.get("Location", "")
                    if "cabinet" in location.lower():
                        self._extract_cookies()
                        self._authenticated = True
                        self._auth_time = time.time()
                        _LOGGER.debug(
                            "Login successful: sid=%s, user=%s, name=%s",
                            self._sid,
                            self._user_login,
                            self._user_name,
                        )
                        return {
                            "sid": self._sid,
                            "user_login": self._user_login,
                            "user_name": self._user_name,
                        }
                    raise RIRCAuthError("Invalid login or password")

                if status == 200:
                    if "ошибка" in body.lower() or "неверн" in body.lower():
                        raise RIRCAuthError("Invalid login or password")
                    self._extract_cookies()
                    self._authenticated = True
                    self._auth_time = time.time()
                    return {
                        "sid": self._sid,
                        "user_login": self._user_login,
                        "user_name": self._user_name,
                    }

                raise RIRCAuthError(f"Unexpected login response status: {status}")

        except aiohttp.ClientConnectorError as err:
            _LOGGER.debug("Login connection error: %s", err)
            raise RIRCConnectionError(
                f"Cannot connect to {BASE_URL}: {err}"
            ) from err
        except aiohttp.ServerTimeoutError as err:
            _LOGGER.debug("Login timeout: %s", err)
            raise RIRCTimeoutError(
                f"Timeout connecting to {BASE_URL}: {err}"
            ) from err

    def invalidate_session(self) -> None:
        """Invalidate current session (e.g. after server-side expiry)."""
        self._authenticated = False
        self._auth_time = 0
        self._sid = None
        _LOGGER.debug("Session invalidated")

    async def async_ensure_authenticated(self, login: str, password: str) -> None:
        """Ensure we are authenticated, refreshing if needed."""
        if not self.authenticated:
            _LOGGER.debug("Not authenticated, performing login")
            await self.async_login(login, password)
        else:
            _LOGGER.debug("Already authenticated (sid=%s)", self._sid)

    def _extract_cookies(self) -> None:
        """Extract session data from cookies."""
        cookies = self._session.cookie_jar.filter_cookies(
            aiohttp.typedefs.URL(BASE_URL)
        )

        sid_cookie = cookies.get(COOKIE_SID)
        if sid_cookie:
            try:
                self._sid = base64.b64decode(sid_cookie.value).decode("utf-8")
            except Exception:  # noqa: BLE001
                self._sid = sid_cookie.value

        ul_cookie = cookies.get(COOKIE_UL)
        if ul_cookie:
            try:
                self._user_login = base64.b64decode(ul_cookie.value).decode("utf-8")
            except Exception:  # noqa: BLE001
                self._user_login = ul_cookie.value

        un_cookie = cookies.get(COOKIE_UN)
        if un_cookie:
            try:
                self._user_name = base64.b64decode(un_cookie.value).decode("utf-8")
            except Exception:  # noqa: BLE001
                self._user_name = un_cookie.value
