"""Exceptions for the RIRC integration."""

from __future__ import annotations


class RIRCError(Exception):
    """Base exception for RIRC integration."""


class RIRCAuthError(RIRCError):
    """Authentication error."""


class RIRCConnectionError(RIRCError):
    """Connection error."""


class RIRCTimeoutError(RIRCError):
    """Timeout error."""


class RIRCApiError(RIRCError):
    """General API error."""
