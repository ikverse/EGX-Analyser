from datetime import datetime, timezone

from app.time_utils import as_cairo, cairo_iso


def test_as_cairo_uses_egypt_timezone_and_dst_rules() -> None:
    winter = as_cairo(datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc))
    summer = as_cairo(datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc))

    assert winter.tzinfo is not None
    assert winter.tzinfo.key == "Africa/Cairo"
    assert winter.hour == 12
    assert summer.hour == 13


def test_cairo_iso_keeps_cairo_offset() -> None:
    timestamp = cairo_iso(datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc))

    assert timestamp.startswith("2026-07-15T13:00:00")
    assert timestamp.endswith("+03:00")
