from __future__ import annotations

from typing import Any

from app.channel_names import clean_channel_name


_MERGED_TEXT_FIELDS = {
    "recommendation_evidence",
    "timing_evidence",
    "date_evidence",
    "notes_ar",
}
_WATCHING_BASES = {
    "watching",
    "watch",
    "watchlist",
    "watch_list",
    "under_watch",
    "stock_to_watch",
}


def _basis_key(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def _effective_date_bases(point: dict[str, Any]) -> list[str]:
    values = point.get("effective_date_bases")
    candidates = list(values) if isinstance(values, list) else []
    if point.get("effective_date_basis"):
        candidates.append(point["effective_date_basis"])
    bases: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        label = str(value or "").strip()
        key = _basis_key(label)
        if label and key not in seen:
            seen.add(key)
            bases.append(label)
    return bases


def _merge_same_source_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge repeated same-stock panels from one Telegram image into one result row."""
    merged: list[dict[str, Any]] = []
    by_source: dict[tuple[str, object], dict[str, Any]] = {}
    for index, point in enumerate(points):
        image_reference = point.get("source_image_ref")
        key = (
            str(point.get("source_message_id") or ""),
            image_reference if image_reference is not None else f"unlinked:{index}",
        )
        existing = by_source.get(key)
        if existing is None:
            existing = dict(point)
            existing["effective_date_bases"] = _effective_date_bases(existing)
            by_source[key] = existing
            merged.append(existing)
            continue

        existing["effective_date_bases"] = _effective_date_bases({
            "effective_date_bases": [
                *_effective_date_bases(existing),
                *_effective_date_bases(point),
            ],
        })

        for field, value in point.items():
            if value is None or value == "":
                continue
            current = existing.get(field)
            if current is None or current == "":
                existing[field] = value
                continue
            if field in _MERGED_TEXT_FIELDS and str(value).strip() != str(current).strip():
                existing[field] = f"{str(current).strip()} | {str(value).strip()}"
    for point in merged:
        bases = _effective_date_bases(point)
        point["effective_date_bases"] = bases
        if any(_basis_key(value) in _WATCHING_BASES for value in bases):
            point["effective_date_basis"] = "watching"
    return merged


def _category_code(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("stock_code") or value.get("ticker") or value.get("code")
    return str(value or "").strip().upper()


def _filter_categories(
    payload: dict[str, Any],
    accepted_codes: set[str],
    watching_codes: set[str],
) -> None:
    categories = payload.get("text_based_categories")
    if not isinstance(categories, dict):
        payload["text_based_categories"] = {}
        return
    for name, values in list(categories.items()):
        filtered: list[object] = []
        seen: set[str] = set()
        allowed = watching_codes if name == "watchlist_stocks" else accepted_codes
        for value in values if isinstance(values, list) else []:
            code = _category_code(value)
            if not code or code not in allowed or code in seen:
                continue
            seen.add(code)
            filtered.append(value)
        categories[name] = filtered


def normalize_consolidated_output(
    payload: dict[str, Any],
    messages: list[dict[str, Any]],
    source_image_references: dict[int, dict[str, str]] | None = None,
) -> list[str]:
    """
    Keep rows with known Telegram IDs and trusted local provenance.

    The date a recommendation belongs to is the model's to decide. This used to second-guess it by
    comparing the date printed on the source against the target date and discarding any row that
    differed, which threw away every card published during one session for the next one - the
    source window already limits which messages reach the model, so the extra gate only cost
    recommendations.
    """
    sources = {
        str(item.get("telegram_message_id")): clean_channel_name(item.get("source"))
        for item in messages
        if item.get("telegram_message_id") is not None
    }
    references = source_image_references or {}
    references_by_message: dict[str, list[int]] = {}
    for reference, metadata in references.items():
        message_id = str(metadata.get("source_message_id") or "").strip()
        if message_id:
            references_by_message.setdefault(message_id, []).append(reference)

    warnings: list[str] = []

    def normalize_rows(
        rows: object,
        row_type: str,
        link_images: bool = True,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            message_id = str(row.get("source_message_id") or "").strip()
            if not message_id or message_id not in sources:
                label = message_id or "(missing)"
                warnings.append(f"Excluded {row_type} with unknown Telegram message {label}.")
                continue
            row["source_message_id"] = message_id
            row["source"] = sources[message_id]

            if not link_images:
                normalized.append(row)
                continue
            valid_references = references_by_message.get(message_id, [])
            if len(valid_references) == 1:
                row["source_image_ref"] = valid_references[0]
            elif valid_references:
                try:
                    requested_reference = int(row.get("source_image_ref"))
                except (TypeError, ValueError):
                    requested_reference = -1
                row["source_image_ref"] = (
                    requested_reference if requested_reference in valid_references else None
                )
            else:
                row["source_image_ref"] = None
            normalized.append(row)
        return normalized

    recommendations: list[dict[str, Any]] = []
    for stock in payload.get("top_consolidated_recommendations", []):
        if not isinstance(stock, dict):
            continue
        points = normalize_rows(stock.get("data_points"), "recommendation")
        if not points:
            continue
        merged_points = _merge_same_source_points(points)
        stock["data_points"] = merged_points
        stock["mention_count"] = len(merged_points)
        recommendations.append(stock)
    for rank, stock in enumerate(recommendations, start=1):
        stock["rank"] = rank
    payload["top_consolidated_recommendations"] = recommendations
    accepted_codes = {
        str(stock.get("stock_code") or "").strip().upper()
        for stock in recommendations
        if stock.get("stock_code")
    }
    watching_codes = {
        str(stock.get("stock_code") or "").strip().upper()
        for stock in recommendations
        if any(
            _basis_key(basis) in _WATCHING_BASES
            for point in stock.get("data_points", [])
            if isinstance(point, dict)
            for basis in _effective_date_bases(point)
        )
    }
    _filter_categories(payload, accepted_codes, watching_codes)
    payload["client_inquiry_responses"] = normalize_rows(
        payload.get("client_inquiry_responses"), "client inquiry",
    )
    payload["achieved_targets"] = normalize_rows(
        payload.get("achieved_targets"), "achieved target", link_images=False,
    )
    return warnings


def validate_consolidated_output(
    payload: dict[str, Any],
    messages: list[dict[str, Any]],
) -> list[str]:
    """Backward-compatible entry point for minimal Telegram-ID validation."""
    return normalize_consolidated_output(payload, messages)
