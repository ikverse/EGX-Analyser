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
    since = await _scoring_since(session)
    scored: list[dict[str, object]] = []
    by_channel: dict[str, list[Scored]] = defaultdict(list)

    if since is not None:
        for report in await _reports_since(session, since):
            for row in _recommendation_rows(report):
                opened_on = _opened_on(row)
                ticker = normalize_ticker(row.get("ticker"))
                if not ticker or opened_on is None or opened_on < since:
                    continue
                sessions = await _sessions_from(session, ticker, opened_on)
                result = score(
                    sessions,
                    entry_low=_number(row.get("buy_price_low")) or _number(row.get("buy_price")),
                    entry_high=_number(row.get("buy_price_high")) or _number(row.get("buy_price")),
                    target_1=_number(row.get("target_1")),
                    target_2=_number(row.get("target_2")),
                    stop_loss=_number(row.get("stop_loss")),
                    window_sessions=window,
                )
                channel = str(row.get("source") or "Unknown").strip() or "Unknown"
                by_channel[channel].append(result)
                scored.append({
                    "ticker": ticker,
                    "company": row.get("company") or ticker,
                    "company_ar": row.get("company_ar"),
                    "channel": channel,
                    "opened_on": opened_on.isoformat(),
                    "entry_low": _number(row.get("buy_price_low")) or _number(row.get("buy_price")),
                    "entry_high": _number(row.get("buy_price_high")) or _number(row.get("buy_price")),
                    "target": _number(row.get("target_1")),
                    "target_2": _number(row.get("target_2")),
                    "stop_loss": _number(row.get("stop_loss")),
                    **{key: (value.isoformat() if isinstance(value, date) else value)
                       for key, value in asdict(result).items()},
                    "outcome": result.outcome.value,
                })

    return {
        "window_sessions": window,
        "scoring_since": since.isoformat() if since else None,
        "totals": _totals(scored),
        "channels": _channel_scores(by_channel),
        "recommendations": sorted(scored, key=lambda item: item["opened_on"], reverse=True),
    }


async def _scoring_since(session: AsyncSession) -> date | None:
    """
    The first session ever stored.

    Using the price history as the starting line means the feature scores exactly what it can
    actually judge, with no date to configure and nothing counted from before it existed.
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
