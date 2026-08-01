"""Turns saved analyses plus stored sessions into performance figures."""
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyPrice, Report
from app.scoring import Outcome, Scored, clamp_window, normalize_ticker, score

# Outcomes that say nothing about whether the source was right, so they are reported separately
# rather than counted as hits or misses.
UNJUDGED = {Outcome.ENTRY_NOT_REACHED, Outcome.UNPRICED, Outcome.AMBIGUOUS, Outcome.OPEN}


async def performance(session: AsyncSession, window_sessions: int) -> dict[str, object]:
    """
    Scores every analysis from the point price collection began.

    Recommendations live inside each report's summary rather than in the recommendations table,
    which the consolidated analysis does not write to. Anything predating the first stored session
    is skipped rather than reported as unpriced, since a call made before there was any price
    history says nothing about the source.
    """
    window = clamp_window(window_sessions)
    prices_from = await _prices_from(session)
    scored: list[dict[str, object]] = []
    by_channel: dict[str, list[Scored]] = defaultdict(list)

    for call in await _unique_calls(session, prices_from):
        sessions = await _sessions_from(session, call["ticker"], call["opened_on"])
        result = score(
            sessions,
            entry_low=call["entry_low"],
            entry_high=call["entry_high"],
            target_1=call["target"],
            target_2=call["target_2"],
            stop_loss=call["stop_loss"],
            window_sessions=window,
        )
        by_channel[str(call["channel"])].append(result)
        scored.append({
            **call,
            "opened_on": call["opened_on"].isoformat(),
            **{key: (value.isoformat() if isinstance(value, date) else value)
               for key, value in asdict(result).items()},
            "outcome": result.outcome.value,
        })

    # The earliest call actually scored, not the earliest stored price: reporting the price
    # history's start claimed coverage no saved call came anywhere near.
    oldest = min((item["opened_on"] for item in scored), default=None)
    return {
        "window_sessions": window,
        "scoring_since": oldest,
        # Calls naming a stock with no stored price at all, so a refresh is the missing step.
        "unpriced_stocks": len({
            item["ticker"] for item in scored if item["outcome"] == Outcome.UNPRICED.value
        }),
        "totals": _totals(scored),
        "channels": _channel_scores(by_channel),
        "recommendations": sorted(scored, key=lambda item: item["opened_on"], reverse=True),
    }


async def _unique_calls(session: AsyncSession, since: date | None) -> list[dict[str, object]]:
    """
    One entry per call, not per time a call was written down.

    Re-running the analysis on the same day saves another report listing the same recommendations,
    so the raw rows count a single call once per run. Left alone that inflates every total and
    quietly gives extra weight to whichever channel happened to be analysed most often. Calls are
    therefore keyed by stock, channel and date, keeping whichever copy states the most price
    levels, since runs differ mainly in how much of the message the model managed to read.
    """
    if since is None:
        return []
    best: dict[tuple[str, str, date], tuple[int, dict[str, object]]] = {}
    for report in await _reports_since(session, since):
        for row in _recommendation_rows(report):
            ticker = normalize_ticker(row.get("ticker"))
            opened_on = _opened_on(row)
            if not ticker or opened_on is None or opened_on < since:
                continue
            channel = str(row.get("source") or "Unknown").strip() or "Unknown"
            call = {
                "ticker": ticker,
                "company": row.get("company") or ticker,
                "company_ar": row.get("company_ar"),
                "channel": channel,
                "opened_on": opened_on,
                "entry_low": _price(row.get("buy_price_low")) or _price(row.get("buy_price")),
                "entry_high": _price(row.get("buy_price_high")) or _price(row.get("buy_price")),
                "target": _price(row.get("target_1")),
                "target_2": _price(row.get("target_2")),
                "stop_loss": _price(row.get("stop_loss")),
            }
            levels = sum(
                call[key] is not None
                for key in ("entry_low", "entry_high", "target", "target_2", "stop_loss")
            )
            key = (ticker, channel, opened_on)
            if key not in best or levels > best[key][0]:
                best[key] = (levels, call)
    return [call for _, call in best.values()]


async def _prices_from(session: AsyncSession) -> date | None:
    """
    The first session ever stored.

    Used only as the gate on what can be scored - a call made before there was any price history
    says nothing about the source. What the page reports as its starting point is the oldest call
    actually scored, which is a fact about the calls rather than about the download.
    """
    return await session.scalar(select(func.min(DailyPrice.session_date)))


async def _reports_since(session: AsyncSession, since: date) -> list[Report]:
    rows = (await session.scalars(select(Report).order_by(Report.id))).all()
    return [report for report in rows if _report_date(report) and _report_date(report) >= since]


def _report_date(report: Report) -> date | None:
    value = getattr(report, "report_date", None)
    return value.date() if hasattr(value, "date") else None


def _recommendation_rows(report: Report) -> list[dict[str, object]]:
    # summary is a JSON column, so it arrives already decoded; older rows written as text are
    # still decoded here rather than being silently skipped.
    summary: object = report.summary
    if isinstance(summary, str):
        try:
            summary = json.loads(summary or "{}")
        except ValueError:
            return []
    if not isinstance(summary, dict):
        return []
    rows = summary.get("stock_source_table")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _opened_on(row: dict[str, object]) -> date | None:
    """The session the call was made for, which is where scoring starts."""
    for key in ("latest_date", "visible_source_date"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            try:
                return date.fromisoformat(value.strip()[:10])
            except ValueError:
                continue
    return None


async def _sessions_from(
    session: AsyncSession, ticker: str, opened_on: date,
) -> list[DailyPrice]:
    """Sessions from the day the call was made onward, oldest first."""
    return list(
        (
            await session.scalars(
                select(DailyPrice)
                .where(DailyPrice.ticker == ticker, DailyPrice.session_date >= opened_on)
                .order_by(DailyPrice.session_date),
            )
        ).all(),
    )


def _totals(scored: list[dict[str, object]]) -> dict[str, object]:
    counts: dict[str, int] = defaultdict(int)
    for item in scored:
        counts[str(item["outcome"])] += 1
    judged = sum(count for outcome, count in counts.items() if Outcome(outcome) not in UNJUDGED)
    hits = counts[Outcome.TARGET_1.value] + counts[Outcome.TARGET_2.value]
    return {
        "tracked": len(scored),
        "judged": judged,
        "hits": hits,
        # Only calls that could be judged count toward the rate, so a stock with no price data or
        # an entry that never traded neither helps nor hurts it.
        "hit_rate": round(hits / judged * 100, 1) if judged else None,
        "by_outcome": dict(counts),
    }


def _channel_scores(by_channel: dict[str, list[Scored]]) -> list[dict[str, object]]:
    scores: list[dict[str, object]] = []
    for channel, results in by_channel.items():
        judged = [r for r in results if r.outcome not in UNJUDGED]
        hits = [r for r in judged if r.outcome in (Outcome.TARGET_1, Outcome.TARGET_2)]
        returns = [r.return_pct for r in judged if r.return_pct is not None]
        scores.append({
            "channel": channel,
            "calls": len(results),
            "judged": len(judged),
            "hits": len(hits),
            "stopped": sum(1 for r in judged if r.outcome is Outcome.STOPPED),
            "expired": sum(1 for r in judged if r.outcome is Outcome.EXPIRED),
            "entry_not_reached": sum(1 for r in results if r.outcome is Outcome.ENTRY_NOT_REACHED),
            "unpriced": sum(1 for r in results if r.outcome is Outcome.UNPRICED),
            "hit_rate": round(len(hits) / len(judged) * 100, 1) if judged else None,
            "average_return": round(sum(returns) / len(returns), 2) if returns else None,
            "median_sessions_to_hit": _median([r.sessions_elapsed for r in hits]),
        })
    # Channels with nothing judged sort last: a perfect record over zero calls is not a record.
    return sorted(
        scores,
        key=lambda item: (item["judged"] > 0, item["hit_rate"] or 0, item["judged"]),
        reverse=True,
    )


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _price(value: object) -> float | None:
    """
    A price exactly as the source printed it.

    It used to be rounded to two decimals, which reached the scorer rather than only the screen.
    EGX trades plenty of stocks below one pound - ARAB at 0.243, COPR at 0.408 - where the third
    decimal is the difference between a target that was hit and one the run waited for in vain.
    """
    return _number(value)


async def recommended_tickers(session: AsyncSession) -> set[str]:
    """
    Every ticker named by any stored analysis.

    Only these are worth pricing: the rest cannot be scored, and each one costs a request to an
    undocumented endpoint.
    """
    tickers: set[str] = set()
    for report in (await session.scalars(select(Report))).all():
        for row in _recommendation_rows(report):
            ticker = normalize_ticker(row.get("ticker"))
            if ticker:
                tickers.add(ticker)
    return tickers
