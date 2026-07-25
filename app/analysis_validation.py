from __future__ import annotations

from typing import Any

from app.analysis_filter import is_client_inquiry_context


_VALUE_FIELDS = (
    "buy_price", "buy_price_low", "buy_price_high", "target_1", "target_2", "stop_loss", "support", "resistance",
)


def _normalized_value(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value).strip().casefold()


def _point_fingerprint(point: dict[str, Any]) -> tuple[str, ...] | None:
    values = tuple(_normalized_value(point.get(field)) for field in _VALUE_FIELDS)
    if sum(bool(value) for value in values) < 3:
        return None
    return (str(point.get("recommendation_type") or "").strip().casefold(), *values)


def validate_consolidated_output(payload: dict[str, Any], messages: list[dict[str, Any]]) -> list[str]:
    """Return auditable warnings without rejecting any model output."""
    source_by_message_id = {
        str(item.get("telegram_message_id")): str(item.get("source") or "")
        for item in messages if item.get("telegram_message_id") is not None
    }
    inquiry_message_ids = {
        str(item.get("telegram_message_id"))
        for item in messages
        if is_client_inquiry_context(
            "\n".join([str(item.get("text") or ""), *[str(value) for value in item.get("transcripts") or []]])
        )
    }
    warnings: list[str] = []
    main_message_ids: set[str] = set()
    fingerprints_by_stock: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    stocks_by_fingerprint: dict[tuple[str, ...], set[str]] = {}
    for stock in payload.get("top_consolidated_recommendations", []):
        if not isinstance(stock, dict):
            continue
        ticker = str(stock.get("stock_code") or "UNKNOWN").strip().upper()
        for point in stock.get("data_points", []):
            if not isinstance(point, dict):
                continue
            message_id = str(point.get("source_message_id") or "").strip()
            source = str(point.get("source") or "").strip()
            if not message_id:
                warnings.append("A recommendation data point is missing source_message_id.")
                continue
            main_message_ids.add(message_id)
            expected_source = source_by_message_id.get(message_id)
            if expected_source is None:
                warnings.append(f"Recommendation references unknown Telegram message {message_id}.")
            elif source != expected_source:
                warnings.append(f"Recommendation message {message_id} has an invalid source label.")
            evidence = str(point.get("recommendation_evidence") or "").strip()
            if not evidence:
                warnings.append(f"Recommendation {ticker} message {message_id} is missing exact recommendation_evidence.")
            fingerprint = _point_fingerprint(point)
            if fingerprint is not None:
                fingerprints_by_stock.setdefault((ticker, fingerprint), []).append(message_id)
                stocks_by_fingerprint.setdefault(fingerprint, set()).add(ticker)
    for (ticker, _), message_ids in fingerprints_by_stock.items():
        unique_ids = list(dict.fromkeys(message_ids))
        if len(unique_ids) > 1:
            warnings.append(
                f"Recommendation {ticker} repeats identical trade values across messages {', '.join(unique_ids)}."
            )
    for fingerprint, tickers in stocks_by_fingerprint.items():
        if len(tickers) > 1:
            warnings.append(
                f"Identical trade values were assigned to different stocks: {', '.join(sorted(tickers))}."
            )
    inquiry_message_ids_returned: set[str] = set()
    for item in payload.get("client_inquiry_responses", []):
        if not isinstance(item, dict):
            continue
        message_id = str(item.get("source_message_id") or "").strip()
        source = str(item.get("source") or "").strip()
        if not message_id:
            warnings.append("A client inquiry response is missing source_message_id.")
            continue
        inquiry_message_ids_returned.add(message_id)
        expected_source = source_by_message_id.get(message_id)
        if expected_source is None:
            warnings.append(f"Client inquiry references unknown Telegram message {message_id}.")
        elif source != expected_source:
            warnings.append(f"Client inquiry message {message_id} has an invalid source label.")
    misplaced = sorted(main_message_ids & inquiry_message_ids)
    if misplaced:
        warnings.append(f"{len(misplaced)} marked client inquiry message(s) were placed in recommendations.")
    missing_inquiries = inquiry_message_ids - inquiry_message_ids_returned
    if missing_inquiries:
        warnings.append(f"{len(missing_inquiries)} marked client inquiry message(s) are absent from client inquiries.")
    return list(dict.fromkeys(warnings))
