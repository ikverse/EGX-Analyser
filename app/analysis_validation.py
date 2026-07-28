from __future__ import annotations

from datetime import date
import re
from typing import Any

from app.channel_names import clean_channel_name


_DATE_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)
_MONTHS = {
    "jan": 1, "january": 1, "يناير": 1,
    "feb": 2, "february": 2, "فبراير": 2,
    "mar": 3, "march": 3, "مارس": 3,
    "apr": 4, "april": 4, "ابريل": 4, "أبريل": 4,
    "may": 5, "مايو": 5,
    "jun": 6, "june": 6, "يونيو": 6, "يونيه": 6,
    "jul": 7, "july": 7, "يوليو": 7, "يوليه": 7,
    "aug": 8, "august": 8, "اغسطس": 8, "أغسطس": 8,
    "sep": 9, "sept": 9, "september": 9, "سبتمبر": 9,
    "oct": 10, "october": 10, "اكتوبر": 10, "أكتوبر": 10,
    "nov": 11, "november": 11, "نوفمبر": 11,
    "dec": 12, "december": 12, "ديسمبر": 12,
}
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


def _parsed_source_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip().translate(_DATE_DIGITS)
    if not text:
        return None

    numeric_patterns = (
        (r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", (1, 2, 3)),
        (r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?!\d)", (3, 2, 1)),
    )
    for pattern, order in numeric_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        values = [int(match.group(index)) for index in order]
        try:
            return date(*values)
        except ValueError:
            return None

    words = re.findall(r"[A-Za-z\u0600-\u06ff]+|\d+", text.casefold())
    for index, word in enumerate(words):
        month = _MONTHS.get(word)
        if month is None:
            continue
        neighboring_numbers: list[int] = []
        for candidate in (words[index - 1:index], words[index + 1:index + 2]):
            if candidate and candidate[0].isdigit():
                neighboring_numbers.append(int(candidate[0]))
        day = next((number for number in neighboring_numbers if 1 <= number <= 31), None)
        year = next((int(item) for item in words if item.isdigit() and len(item) == 4), None)
        if day is None or year is None:
            return None
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def normalize_consolidated_output(
    payload: dict[str, Any],
    messages: list[dict[str, Any]],
    source_image_references: dict[int, dict[str, str]] | None = None,
    target_date: date | str | None = None,
) -> list[str]:
    """Keep rows with known Telegram IDs, eligible dates, and trusted local provenance."""
    sources = {
        str(item.get("telegram_message_id")): clean_channel_name(item.get("source"))
        for item in messages
        if item.get("telegram_message_id") is not None
    }
    parsed_target_date = _parsed_source_date(target_date)
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
        stock_code: object = None,
        enforce_target_date: bool = False,
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
            if parsed_target_date is not None and enforce_target_date:
                visible_date = str(row.get("visible_source_date") or "").strip()
                if _parsed_source_date(visible_date) != parsed_target_date:
                    stock_label = str(stock_code or "(unknown stock)").strip()
                    date_label = visible_date or "(missing)"
                    warnings.append(
                        f"Excluded {stock_label} message {message_id}: source date {date_label} "
                        f"does not match target date {parsed_target_date.isoformat()}."
                    )
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
        points = normalize_rows(
            stock.get("data_points"),
            "recommendation",
            stock_code=stock.get("stock_code"),
            enforce_target_date=True,
        )
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
    target_date: date | str | None = None,
) -> list[str]:
    """Backward-compatible entry point for minimal Telegram-ID and date validation."""
    return normalize_consolidated_output(payload, messages, target_date=target_date)
