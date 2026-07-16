"""Shared Egypt-time helpers for generated artifacts and diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CAIRO_TIMEZONE = ZoneInfo("Africa/Cairo")


def cairo_now() -> datetime:
    """Return a timezone-aware current time in Egypt."""
    return datetime.now(CAIRO_TIMEZONE)


def as_cairo(value: datetime) -> datetime:
    """Render stored UTC values in Egypt time, preserving DST rules."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CAIRO_TIMEZONE)


def cairo_iso(value: datetime | None = None) -> str:
    """Return an ISO timestamp with the Africa/Cairo offset."""
    return as_cairo(value).isoformat() if value is not None else cairo_now().isoformat()
