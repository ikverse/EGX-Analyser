"""Normalize exact recommendation entry prices without averaging ranges."""

from __future__ import annotations

import re
from typing import Any


_ARABIC_NUMERALS = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u066b\u066c", "0123456789.,")
_NUMBER = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?")
_RANGE_CONNECTOR = re.compile(
    r"(?:[-\u2013\u2014~]|\bto\b|\buntil\b|\u0627\u0644\u0649|\u0625\u0644\u0649|\u062d\u062a\u0649|\u0645\u0646|/)",
    re.IGNORECASE,
)


def as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().translate(_ARABIC_NUMERALS).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_entry_point(
    value: Any,
    low: Any = None,
    high: Any = None,
) -> tuple[float | None, float | None, float | None]:
    """Return ``single, low, high`` while preserving a source range exactly."""
    explicit_low = as_number(low)
    explicit_high = as_number(high)
    if explicit_low is not None or explicit_high is not None:
        return None, explicit_low, explicit_high

    single = as_number(value)
    if single is not None:
        return single, None, None
    if value is None:
        return None, None, None

    text = str(value).strip().translate(_ARABIC_NUMERALS).replace(",", "")
    numbers = _NUMBER.findall(text)
    if len(numbers) >= 2 and _RANGE_CONNECTOR.search(text):
        return None, float(numbers[0]), float(numbers[1])
    if len(numbers) == 1:
        return float(numbers[0]), None, None
    return None, None, None


def format_entry_point(value: Any, low: Any = None, high: Any = None) -> str:
    """Format a single entry or exact range for reports and exports."""
    single, range_low, range_high = normalize_entry_point(value, low, high)
    if range_low is not None and range_high is not None:
        return f"{range_low:g}\u2013{range_high:g}"
    if range_low is not None:
        return f"{range_low:g}\u2013"
    if range_high is not None:
        return f"\u2013{range_high:g}"
    return f"{single:g}" if single is not None else "-"
