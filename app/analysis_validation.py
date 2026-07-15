from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.analysis_filter import is_client_inquiry_context


def enforce_client_inquiry_separation(
    payload: dict[str, Any], messages: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Keep marked inquiry messages out of the active recommendation output.

    The model remains responsible for building the inquiry cards. This local
    safeguard only prevents a traceable client-inquiry message from leaking
    into the recommendation table when the provider returns an invalid split.
    """
    inquiry_message_ids = {
        str(item.get("telegram_message_id"))
        for item in messages
        if is_client_inquiry_context(
            "\n".join([str(item.get("text") or ""), *[str(value) for value in item.get("transcripts") or []]])
        )
    }
    if not inquiry_message_ids:
        return payload, []

    sanitized = deepcopy(payload)
    recommendations = sanitized.get("top_consolidated_recommendations")
    if not isinstance(recommendations, list):
        return sanitized, []

    retained_stocks: list[Any] = []
    removed_points = 0
    for stock in recommendations:
        if not isinstance(stock, dict):
            retained_stocks.append(stock)
            continue
        data_points = stock.get("data_points")
        if not isinstance(data_points, list):
            retained_stocks.append(stock)
            continue
        retained_points = [
            point for point in data_points
            if not isinstance(point, dict)
            or str(point.get("source_message_id") or "").strip() not in inquiry_message_ids
        ]
        removed_points += len(data_points) - len(retained_points)
        if not retained_points:
            continue
        if len(retained_points) != len(data_points):
            stock["data_points"] = retained_points
            stock["mention_count"] = len(retained_points)
        retained_stocks.append(stock)

    sanitized["top_consolidated_recommendations"] = retained_stocks
    if not removed_points:
        return sanitized, []
    return sanitized, [
        f"{removed_points} marked client inquiry recommendation data point(s) were automatically excluded."
    ]


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
    for stock in payload.get("top_consolidated_recommendations", []):
        if not isinstance(stock, dict):
            continue
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
