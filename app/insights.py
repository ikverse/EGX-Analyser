"""Turns saved recommendations plus stored sessions into performance figures."""
from collections import defaultdict
from dataclasses import asdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Channel, DailyPrice, Message, Recommendation
from app.scoring import Outcome, Scored, clamp_window, score

# Outcomes that say nothing about whether the source was right, so they are reported separately
# rather than being counted as hits or misses.
UNJUDGED = {Outcome.ENTRY_NOT_REACHED, Outcome.UNPRICED, Outcome.AMBIGUOUS, Outcome.OPEN}


async def performance(session: AsyncSession, window_sessions: int) -> dict[str, object]:
    window = clamp_window(window_sessions)
    rows = (
        await session.scalars(
            select(Recommendation).options(
                selectinload(Recommendation.message).selectinload(Message.channel),
            ),
        )
    ).all()

    scored: list[dict[str, object]] = []
    by_channel: dict[str, list[Scored]] = defaultdict(list)

    for row in rows:
        ticker = (row.ticker_raw or "").strip().upper()
        opened_on = _opened_on(row)
        if not ticker or opened_on is None:
            continue
        sessions = await _sessions_from(session, ticker, opened_on)
        result = score(
            sessions,
            entry_low=row.entry_low or row.entry,
            entry_high=row.entry_high or row.entry,
            target_1=row.target,
            target_2=row.target_2,
            stop_loss=row.stop_loss,
            window_sessions=window,
        )
        channel = _channel_name(row)
        by_channel[channel].append(result)
        scored.append({
            "ticker": ticker,
            "company": row.company_name,
            "channel": channel,
            "opened_on": opened_on.isoformat(),
            "entry_low": row.entry_low or row.entry,
            "entry_high": row.entry_high or row.entry,
            "target": row.target,
            "target_2": row.target_2,
            "stop_loss": row.stop_loss,
            **{key: (value.isoformat() if isinstance(value, date) else value)
               for key, value in asdict(result).items()},
            "outcome": result.outcome.value,
        })

    return {
        "window_sessions": window,
        "totals": _totals(scored),
        "channels": _channel_scores(by_channel),
        "recommendations": sorted(scored, key=lambda item: item["opened_on"], reverse=True),
    }


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


def _opened_on(row: Recommendation) -> date | None:
    published = getattr(row.message, "published_at", None)
    return published.date() if published is not None else None


def _channel_name(row: Recommendation) -> str:
    channel: Channel | None = getattr(getattr(row, "message", None), "channel", None)
    return (getattr(channel, "title", None) or getattr(channel, "handle", None) or "Unknown").strip()


def _totals(scored: list[dict[str, object]]) -> dict[str, object]:
    counts: dict[str, int] = defaultdict(int)
    for item in scored:
        counts[str(item["outcome"])] += 1
    judged = sum(
        count for outcome, count in counts.items() if Outcome(outcome) not in UNJUDGED
    )
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
        sessions_to_hit = [r.sessions_elapsed for r in hits]
        scores.append({
            "channel": channel,
            "calls": len(results),
            "judged": len(judged),
            "hits": len(hits),
            "stopped": sum(1 for r in judged if r.outcome is Outcome.STOPPED),
            "expired": sum(1 for r in judged if r.outcome is Outcome.EXPIRED),
            "entry_not_reached": sum(
                1 for r in results if r.outcome is Outcome.ENTRY_NOT_REACHED
            ),
            "unpriced": sum(1 for r in results if r.outcome is Outcome.UNPRICED),
            "hit_rate": round(len(hits) / len(judged) * 100, 1) if judged else None,
            "average_return": round(sum(returns) / len(returns), 2) if returns else None,
            "median_sessions_to_hit": _median(sessions_to_hit),
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
