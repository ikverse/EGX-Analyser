from __future__ import annotations

from typing import Any

from app.channel_names import clean_channel_name


def normalize_consolidated_output(
    payload: dict[str, Any],
    messages: list[dict[str, Any]],
    source_image_references: dict[int, dict[str, str]] | None = None,
) -> list[str]:
    """Keep rows with known Telegram IDs and restore trusted local provenance."""
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
        stock["data_points"] = points
        stock["mention_count"] = len(points)
        recommendations.append(stock)
    payload["top_consolidated_recommendations"] = recommendations
    payload["client_inquiry_responses"] = normalize_rows(
        payload.get("client_inquiry_responses"), "client inquiry",
    )
    payload["achieved_targets"] = normalize_rows(
        payload.get("achieved_targets"), "achieved target", link_images=False,
    )
    return warnings


def validate_consolidated_output(payload: dict[str, Any], messages: list[dict[str, Any]]) -> list[str]:
    """Backward-compatible entry point for the minimal Telegram-ID validation."""
    return normalize_consolidated_output(payload, messages)
