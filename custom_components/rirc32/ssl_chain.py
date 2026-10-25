"""Достраивает цепочку TLS, если сервер не прислал промежуточный сертификат.

lk.rirc.ru отдаёт только сертификат сайта. Браузер сам скачивает издателя
по адресу из поля AIA. Python этого не делает, поэтому проверка обрывается,
пока издатель не добавлен в контекст. Скачанный сертификат не становится
корнем доверия: подпись по-прежнему должна дойти до корня из системы.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import socket
import ssl
from typing import Any
from urllib.parse import urlparse

import aiohttp
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization.pkcs7 import (
    load_der_pkcs7_certificates,
)
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

try:
    from homeassistant.util.ssl import SSL_ALPN_HTTP11, create_client_context
except ImportError:  # HA < 2025.2
    from homeassistant.util.ssl import create_client_context

    SSL_ALPN_HTTP11 = None

from .const import BASE_URL
from .exceptions import RIRCConnectionError

_LOGGER = logging.getLogger(__name__)

_MAX_DEPTH = 3
_MAX_BYTES = 64 * 1024
_TIMEOUT = aiohttp.ClientTimeout(total=10)
_cache: dict[str, ssl.SSLContext] = {}
_lock = asyncio.Lock()


def _issuer_urls(cert: x509.Certificate) -> list[str]:
    """Вернуть URL издателей из расширения AIA."""
    try:
        aia = cert.extensions.get_extension_for_oid(
            ExtensionOID.AUTHORITY_INFORMATION_ACCESS
        ).value
    except x509.ExtensionNotFound:
        return []

    urls: list[str] = []
    for item in aia:
        if item.access_method != AuthorityInformationAccessOID.CA_ISSUERS:
            continue
        url = item.access_location.value
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.append(url)
    return urls


def _load_certs(data: bytes) -> list[x509.Certificate]:
    """Прочитать один сертификат или набор из PEM, DER или PKCS#7."""
    if b"-----BEGIN CERTIFICATE-----" in data:
        certs: list[x509.Certificate] = []
        for chunk in data.split(b"-----END CERTIFICATE-----"):
            start = chunk.find(b"-----BEGIN CERTIFICATE-----")
            if start < 0:
                continue
            pem = chunk[start:] + b"-----END CERTIFICATE-----\n"
            certs.append(x509.load_pem_x509_certificate(pem))
        if certs:
            return certs

    try:
        return [x509.load_der_x509_certificate(data)]
    except ValueError:
        return list(load_der_pkcs7_certificates(data))


def _peer_leaf(host: str, port: int) -> bytes:
    """Прочитать сертификат, который прислал сервер.

    Это чтение не проверяет подпись: оно нужно только чтобы увидеть лист
    и адрес AIA. Рабочее соединение создаётся уже с проверкой.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=10) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise OSError(f"{host} не прислал сертификат")
    return der


def _verifying_context(
    host: str, port: int, extra: list[x509.Certificate]
) -> ssl.SSLContext | None:
    """Собрать проверяющий контекст и убедиться, что рукопожатие проходит."""
    if SSL_ALPN_HTTP11 is None:
        context = create_client_context()
    else:
        context = create_client_context(alpn_protocols=SSL_ALPN_HTTP11)
    if extra:
        pem = b"".join(
            cert.public_bytes(serialization.Encoding.PEM) for cert in extra
        )
        context.load_verify_locations(cadata=pem.decode("ascii"))
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host):
                return context
    except ssl.SSLCertVerificationError:
        return None


async def _download_certs(
    session: aiohttp.ClientSession, url: str
) -> list[x509.Certificate]:
    """Скачать сертификат издателя по адресу AIA."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return []
    try:
        async with session.get(
            url, timeout=_TIMEOUT, allow_redirects=True
        ) as response:
            if response.status != 200:
                return []
            data = await response.content.read(_MAX_BYTES + 1)
    except (aiohttp.ClientError, TimeoutError, OSError):
        _LOGGER.debug("Не удалось скачать AIA %s", url, exc_info=True)
        return []
    if len(data) > _MAX_BYTES:
        return []
    try:
        return _load_certs(data)
    except ValueError:
        _LOGGER.debug("Ответ AIA %s не является сертификатом", url)
        return []


async def async_ssl_context_for_host(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    host: str,
    port: int = 443,
) -> ssl.SSLContext:
    """Вернуть проверяющий контекст, докачав недостающих издателей."""
    leaf_der = await hass.async_add_executor_job(_peer_leaf, host, port)
    fingerprint = hashlib.sha256(leaf_der).hexdigest()

    async with _lock:
        cached = _cache.get(fingerprint)
        if cached is not None:
            return cached

        leaf = x509.load_der_x509_certificate(leaf_der)
        extra: list[x509.Certificate] = []
        seen: set[bytes] = set()
        frontier = [leaf]

        for depth in range(_MAX_DEPTH + 1):
            context = await hass.async_add_executor_job(
                _verifying_context, host, port, list(extra)
            )
            if context is not None:
                if extra:
                    _LOGGER.debug(
                        "Для %s докачано промежуточных сертификатов: %s",
                        host,
                        len(extra),
                    )
                _cache[fingerprint] = context
                return context
            if depth == _MAX_DEPTH:
                break

            fetched_any = False
            next_frontier: list[x509.Certificate] = []
            for cert in frontier:
                for url in _issuer_urls(cert):
                    for item in await _download_certs(session, url):
                        digest = item.fingerprint(SHA256())
                        if digest in seen:
                            continue
                        seen.add(digest)
                        extra.append(item)
                        next_frontier.append(item)
                        fetched_any = True
            if not fetched_any:
                break
            frontier = next_frontier

    raise ssl.SSLCertVerificationError(f"Не удалось построить цепочку для {host}")


class _RircRequest:
    """Повторяет запрос один раз, если сертификат сайта сменился."""

    def __init__(
        self,
        owner: RircSession,
        method: str,
        url: str,
        kwargs: dict[str, Any],
    ) -> None:
        """Подготовить запрос."""
        self._owner = owner
        self._method = method
        self._url = url
        self._kwargs = kwargs
        self._cm: Any = None

    async def __aenter__(self) -> aiohttp.ClientResponse:
        """Выполнить запрос с актуальным контекстом SSL."""
        self._kwargs["ssl"] = self._owner.ssl_context
        try:
            self._cm = self._owner.raw.request(
                self._method, self._url, **self._kwargs
            )
            return await self._cm.__aenter__()
        except aiohttp.ClientConnectorCertificateError:
            self._cm = None
            self._owner.ssl_context = await async_ssl_context_for_host(
                self._owner.hass,
                self._owner.raw,
                self._owner.host,
                self._owner.port,
            )
            self._kwargs["ssl"] = self._owner.ssl_context
            self._cm = self._owner.raw.request(
                self._method, self._url, **self._kwargs
            )
            return await self._cm.__aenter__()

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        """Закрыть ответ."""
        if self._cm is None:
            return False
        return await self._cm.__aexit__(exc_type, exc, traceback)


class RircSession:
    """Сессия Home Assistant с отдельным проверяющим контекстом для РИРЦ."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        ssl_context: ssl.SSLContext,
    ) -> None:
        """Сохранить сессию и контекст."""
        self.hass = hass
        self.raw = session
        self.host = host
        self.port = port
        self.ssl_context = ssl_context

    @property
    def cookie_jar(self) -> aiohttp.CookieJar:
        """Вернуть хранилище cookie общей сессии."""
        return self.raw.cookie_jar

    def get(self, url: str, **kwargs: Any) -> _RircRequest:
        """Выполнить GET."""
        return _RircRequest(self, "GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> _RircRequest:
        """Выполнить POST."""
        return _RircRequest(self, "POST", url, kwargs)


async def async_create_rirc_session(hass: HomeAssistant) -> RircSession:
    """Создать сессию, которая доверяет текущей цепочке lk.rirc.ru."""
    parsed = urlparse(BASE_URL)
    host = parsed.hostname or "lk.rirc.ru"
    port = parsed.port or 443
    session = async_create_clientsession(hass)
    try:
        ssl_context = await async_ssl_context_for_host(hass, session, host, port)
    except (aiohttp.ClientError, OSError) as err:
        raise RIRCConnectionError(f"Cannot connect to {BASE_URL}: {err}") from err
    return RircSession(hass, session, host, port, ssl_context)
