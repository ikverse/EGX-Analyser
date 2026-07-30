"""Scores saved recommendations against what the market actually did.

Outcomes are decided by comparing target and stop levels to the session high and low, which is
arithmetic rather than judgement, so no model is involved.
"""
import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyPrice

# The window is expressed in trading sessions rather than calendar days: a stock does not move at
# the weekend, so counting those would shorten every window by two days in five.
MIN_WINDOW_SESSIONS = 1
MAX_WINDOW_SESSIONS = 30

# History comes from the same provider the quote feed proxies, addressed directly because that
# feed reports only the current session. A month of calendar days is requested to be sure of
# covering the sessions wanted once weekends and holidays are removed.
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.CA"
_BACKFILL_CONCURRENCY = 4


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


def normalize_ticker(value: object) -> str:
    """
    One spelling per stock.

    Sources quote the same company as both AMOC and AMOC.CA, and treating those as two stocks
    splits a channel's record in half and prices only one of them.
    """
    return str(value or "").strip().upper().removesuffix(".CA")


def clamp_window(sessions: int) -> int:
    return max(MIN_WINDOW_SESSIONS, min(MAX_WINDOW_SESSIONS, sessions))


async def latest_quotes(url: str) -> dict[str, dict[str, object]]:
    """
    Current prices, keyed by ticker.

    Used to show where a stock is trading now. Deliberately not written into daily_prices: this
    feed reports no session date - its timestamp is when the request was served - so storing it
    against a calendar date invents a session on any day the market did not trade, and
    double-counts one it did.
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("results") or payload.get("quotes")
    quotes: dict[str, dict[str, object]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ticker = normalize_ticker(row.get("symbol"))
        if ticker:
            quotes[ticker] = row
    return quotes


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


async def backfill_sessions(
    session: AsyncSession,
    tickers: list[str],
    sessions: int = MAX_WINDOW_SESSIONS,
    url_template: str = YAHOO_CHART_URL,
) -> dict[str, int]:
    """
    Fills in recent sessions for the given tickers.

    Requests are made a few at a time rather than all at once: this is an undocumented public
    endpoint and hammering it would be both rude and likely to get throttled. A ticker that fails
    is skipped rather than aborting the run, since one delisted symbol should not cost the rest.
    """
    wanted = min(max(sessions, MIN_WINDOW_SESSIONS), MAX_WINDOW_SESSIONS)
    limit = asyncio.Semaphore(_BACKFILL_CONCURRENCY)
    stored: dict[str, int] = {}

    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; EGX-Analyzer)"},
    ) as client:
        async def one(ticker: str) -> tuple[str, list[dict[str, object]]]:
            async with limit:
                try:
                    response = await client.get(
                        url_template.format(symbol=ticker),
                        params={"interval": "1d", "range": "1mo"},
                    )
                    response.raise_for_status()
                    return ticker, _chart_sessions(response.json(), wanted)
                except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
                    return ticker, []

        for ticker, days in await asyncio.gather(*(one(t) for t in tickers)):
            for day in days:
                await _upsert(session, ticker, day)
            if days:
                stored[ticker] = len(days)
    return stored


def _chart_sessions(payload: object, wanted: int) -> list[dict[str, object]]:
    result = payload["chart"]["result"][0]  # type: ignore[index]
    quote = result["indicators"]["quote"][0]
    rows: list[dict[str, object]] = []
    for stamp, high, low, close, volume in zip(
        result["timestamp"], quote["high"], quote["low"], quote["close"], quote["volume"],
    ):
        # A session still open reports nulls; it is not history yet.
        if high is None or low is None:
            continue
        rows.append({
            "session_date": datetime.fromtimestamp(stamp, tz=UTC).date(),
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "source": "Yahoo Finance",
        })
    return rows[-wanted:]


async def _upsert(session: AsyncSession, ticker: str, day: dict[str, object]) -> None:
    session_date = day["session_date"]
    existing = await session.scalar(
        select(DailyPrice).where(
            DailyPrice.ticker == ticker, DailyPrice.session_date == session_date,
        ),
    )
    row = existing or DailyPrice(ticker=ticker, session_date=session_date)  # type: ignore[arg-type]
    row.high = _number(day.get("high"))
    row.low = _number(day.get("low"))
    row.close = _number(day.get("close"))
    row.volume = _number(day.get("volume"))
    row.source = str(day.get("source") or "")[:60] or None
    if existing is None:
        session.add(row)
