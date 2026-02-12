"""Helper utilities for the RIRC integration."""

from __future__ import annotations

import re
from typing import Any


def parse_float(value: str | None, default: float | None = 0.0) -> float | None:
    """Safely parse a float value from string."""
    if value is None:
        return default
    try:
        # Replace comma with dot (Russian locale)
        cleaned = str(value).strip().replace(",", ".").replace(" ", "")
        # Remove " руб." suffix if present
        cleaned = re.sub(r"\s*руб\.?\s*$", "", cleaned)
        if not cleaned:
            return default
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def find_last_nonzero_payment(
    payments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the most recent payment entry with amount > 0, or None."""
    for p in payments:
        try:
            if p.get("amount", 0) and float(p["amount"]) > 0:
                return p
        except (TypeError, ValueError):
            continue
    return None


def extract_meter_type_icon(meter_name: str) -> str:
    """Return an appropriate MDI icon based on meter name."""
    name_lower = meter_name.lower()
    if "вода" in name_lower:
        if "гор" in name_lower:
            return "mdi:water-boiler"
        return "mdi:water"
    if "газ" in name_lower:
        return "mdi:gas-cylinder"
    if "электр" in name_lower or "свет" in name_lower:
        return "mdi:flash"
    if "тепл" in name_lower or "отопл" in name_lower:
        return "mdi:radiator"
    return "mdi:gauge"


def get_period_name(period_code: str) -> str:
    """Convert period code (e.g., '2601') to human-readable name."""
    months = {
        "01": "Январь", "02": "Февраль", "03": "Март",
        "04": "Апрель", "05": "Май", "06": "Июнь",
        "07": "Июль", "08": "Август", "09": "Сентябрь",
        "10": "Октябрь", "11": "Ноябрь", "12": "Декабрь",
    }
    if len(period_code) == 4:
        year = f"20{period_code[:2]}"
        month = period_code[2:]
        month_name = months.get(month, month)
        return f"{month_name} {year}"
    return period_code
