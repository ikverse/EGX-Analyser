from typing import Any


def recommendation_signal(data_points: list[dict[str, Any]]) -> str:
    """Derive the internal signal from accepted rows instead of model-owned status."""
    actionable: set[str] = set()
    for point in data_points:
        timing_basis = (
            str(point.get("effective_date_basis") or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        recommendation_type = str(point.get("recommendation_type") or "").strip().lower()
        if recommendation_type == "buy":
            actionable.add("BUY")
        elif recommendation_type == "sell":
            actionable.add("SELL")
        elif not recommendation_type and timing_basis not in {"watching", "under_watch", "watchlist", "watch"}:
            # Older saved rows predate recommendation_type and were displayed as Buy.
            actionable.add("BUY")
    return next(iter(actionable)) if len(actionable) == 1 else "HOLD"
