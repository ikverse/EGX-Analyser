"""Scores saved recommendations against what the market actually did.

Outcomes are decided by comparing target and stop levels to the session high and low, which is
arithmetic rather than judgement, so no model is involved.
"""
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyPrice

# The window is expressed in trading sessions rather than calendar days: a stock does not move at
# the weekend, so counting those would shorten every window by two days in five.
MIN_WINDOW_SESSIONS = 1
MAX_WINDOW_SESSIONS = 30


class Outcome(StrEnum):
    TARGET_1 = "target_1"
    TARGET_2 = "target_2"
    STOPPED = "stopped"
    ENTRY_NOT_REACHED = "entry_not_reached"
    OPEN = "open"
    EXPIRED = "expired"
    AMBIGUOUS = "ambiguous"
    UNPRICED = "unpriced"


@dataclass(frozen=True)
class Scored:
    outcome: Outcome
    settled_on: date | None
    price_at_settlement: float | None
    sessions_elapsed: int
    peak_high: float | None
    return_pct: float | None


def clamp_window(sessions: int) -> int:
    return max(MIN_WINDOW_SESSIONS, min(MAX_WINDOW_SESSIONS, sessions))


async def fetch_daily_quotes(url: str) -> list[dict[str, object]]:
    """One request returns every symbol's session high and low."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("results") or payload.get("quotes")
    return [row for row in (rows or []) if isinstance(row, dict) and row.get("symbol")]


async def store_quotes(
    session: AsyncSession, quotes: list[dict[str, object]], session_date: date,
) -> int:
    """Upserts one session per ticker, so re-running a day corrects it rather than duplicating."""
    stored = 0
    for quote in quotes:
        ticker = str(quote.get("symbol") or "").strip().upper().removesuffix(".CA")
        if not ticker:
            continue
        existing = await session.scalar(
            select(DailyPrice).where(
                DailyPrice.ticker == ticker, DailyPrice.session_date == session_date,
            ),
        )
        row = existing or DailyPrice(ticker=ticker, session_date=session_date)
        row.high = _number(quote.get("high"))
        row.low = _number(quote.get("low"))
        row.close = _number(quote.get("price") or quote.get("close"))
        row.volume = _number(quote.get("volume"))
        row.source = str(quote.get("source") or "")[:60] or None
        if existing is None:
            session.add(row)
        stored += 1
    return stored


def score(
    sessions: list[DailyPrice],
    entry_low: float | None,
    entry_high: float | None,
    target_1: float | None,
    target_2: float | None,
    stop_loss: float | None,
    window_sessions: int,
) -> Scored:
    """
    Walks forward one session at a time and returns the first outcome that settles.

    A session whose high reaches the target and whose low reaches the stop is reported as
    ambiguous: daily figures cannot say which came first, and picking the favourable one would
    quietly inflate every hit rate built on this.
    """
    window = clamp_window(window_sessions)
    considered = sessions[:window]
    if not considered:
        return Scored(Outcome.UNPRICED, None, None, 0, None, None)

    entered = entry_low is None and entry_high is None
    peak = None
    for index, day in enumerate(considered, start=1):
        if day.high is not None:
            peak = day.high if peak is None else max(peak, day.high)
        if not entered and _touched_entry(day, entry_low, entry_high):
            entered = True
        if not entered:
            continue

        hit_target = _reached(day.high, target_2) or _reached(day.high, target_1)
        hit_stop = day.low is not None and stop_loss is not None and day.low <= stop_loss
        if hit_target and hit_stop:
            return Scored(Outcome.AMBIGUOUS, day.session_date, None, index, peak, None)
        if _reached(day.high, target_2):
            return Scored(Outcome.TARGET_2, day.session_date, target_2, index, peak,
                          _return_pct(entry_low, entry_high, target_2))
        if _reached(day.high, target_1):
            return Scored(Outcome.TARGET_1, day.session_date, target_1, index, peak,
                          _return_pct(entry_low, entry_high, target_1))
        if hit_stop:
            return Scored(Outcome.STOPPED, day.session_date, stop_loss, index, peak,
                          _return_pct(entry_low, entry_high, stop_loss))

    if not entered:
        return Scored(Outcome.ENTRY_NOT_REACHED, None, None, len(considered), peak, None)
    if len(considered) >= window:
        return Scored(Outcome.EXPIRED, None, None, len(considered), peak, None)
    return Scored(Outcome.OPEN, None, None, len(considered), peak, None)


def _touched_entry(day: DailyPrice, low: float | None, high: float | None) -> bool:
    bound_low = low if low is not None else high
    bound_high = high if high is not None else low
    if bound_low is None or bound_high is None or day.low is None or day.high is None:
        return False
    # The session traded through the entry band at some point.
    return day.low <= max(bound_low, bound_high) and day.high >= min(bound_low, bound_high)


def _reached(high: float | None, target: float | None) -> bool:
    return high is not None and target is not None and high >= target


def _return_pct(low: float | None, high: float | None, exit_price: float | None) -> float | None:
    entry = low if low is not None else high
    if entry is None or not entry or exit_price is None:
        return None
    return round((exit_price - entry) / entry * 100, 2)


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
