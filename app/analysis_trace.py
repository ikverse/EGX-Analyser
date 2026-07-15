from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, Image, Message, Recommendation


def create_selected_input_trace(storage_root: Path, messages: list[dict[str, Any]],
                                start: datetime, end: datetime, analysis_period: str,
                                target_date: str, content_types: set[str],
                                excluded_items: list[dict[str, str]] | None = None) -> dict[str, object]:
    """Persist the exact date/type-filtered source payload before an AI request.

    The trace intentionally uses the already assembled batch rather than querying
    every stored message again, so deselected text, images, and audio are absent.
    It is created before the provider call and therefore remains available when a
    provider rejects or times out on an analysis request.
    """
    created_at = datetime.now(timezone.utc)
    directory = storage_root / "analysis-traces" / created_at.strftime("%Y-%m-%d") / created_at.strftime("%H%M%S_%f")
    image_directory = directory / "images"
    image_directory.mkdir(parents=True, exist_ok=True)
    copied_images = 0
    serialized_messages: list[dict[str, object]] = []
    text_lines = [
        "EGX Intelligence selected model input",
        f"Created: {created_at.isoformat()}",
        f"Window: {start.isoformat()} to {end.isoformat()}",
        f"Analysis period: {analysis_period}",
        f"Target date: {target_date}",
        f"Content types: {', '.join(sorted(content_types))}",
        f"Selected messages: {len(messages)}",
        "",
    ]
    for item in messages:
        message_id = str(item.get("telegram_message_id") or "unknown")
        copied_paths: list[str] = []
        for index, value in enumerate(item.get("image_paths") or [], start=1):
            source = Path(str(value))
            destination = image_directory / f"{message_id}_{index}_{source.name}"
            if source.is_file():
                shutil.copy2(source, destination)
                copied_images += 1
                copied_paths.append((Path("images") / destination.name).as_posix())
            else:
                copied_paths.append(f"unavailable:{source}")
        record = {
            "source": str(item.get("source") or "Unknown chat"),
            "published_at": str(item.get("published_at") or ""),
            "telegram_message_id": item.get("telegram_message_id"),
            "text": str(item.get("text") or ""),
            "audio_transcripts": [str(value) for value in item.get("transcripts") or [] if value],
            "image_files": copied_paths,
        }
        serialized_messages.append(record)
        text_lines += [
            f"--- MESSAGE | SOURCE: {record['source']} | DATE: {record['published_at']} | TELEGRAM_ID: {message_id} ---",
            str(record["text"]) or "[No selected text]",
        ]
        if record["audio_transcripts"]:
            text_lines.append("Selected audio transcript:\n" + "\n".join(record["audio_transcripts"]))
        for path in copied_paths:
            text_lines.append(f"Selected image: {path}")
        text_lines.append("")
    payload = {
        "created_at": created_at.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "analysis_period": analysis_period,
        "target_date": target_date,
        "content_types": sorted(content_types),
        "messages": serialized_messages,
    }
    json_path = directory / "model-input.json"
    text_path = directory / "model-input.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text("\n".join(text_lines), encoding="utf-8")
    excluded_path = directory / "excluded-items.json"
    excluded_path.write_text(json.dumps(excluded_items or [], ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "directory": str(directory), "text_path": str(text_path), "json_path": str(json_path),
        "images_path": str(image_directory), "excluded_path": str(excluded_path), "consolidated_response_path": None,
        "message_count": len(serialized_messages), "image_count": copied_images,
    }


def save_consolidated_response(trace: dict[str, object], response: str) -> dict[str, object]:
    """Add a provider response to its already-created selected-input trace."""
    directory = Path(str(trace["directory"]))
    response_path = directory / "consolidated-ai-response.json"
    response_path.write_text(response, encoding="utf-8")
    return {**trace, "consolidated_response_path": str(response_path)}


def save_model_validation(trace: dict[str, object], warnings: list[str], correction_attempted: bool) -> dict[str, object]:
    """Persist non-blocking model-output audit details next to the raw response."""
    directory = Path(str(trace["directory"]))
    validation_path = directory / "model-output-validation.json"
    validation_path.write_text(json.dumps({
        "warnings": warnings,
        "correction_attempted": correction_attempted,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**trace, "validation_path": str(validation_path)}


async def export_analysis_trace(session: AsyncSession, storage_root: Path, channel_ids: list[int],
                                start: datetime, end: datetime, consolidated_response: str | None = None) -> dict[str, object]:
    """Save the exact text and images considered in one selected-chat analysis run."""
    created_at = datetime.now(timezone.utc)
    directory = storage_root / "analysis-traces" / created_at.strftime("%Y-%m-%d") / created_at.strftime("%H%M%S")
    image_directory = directory / "images"
    image_directory.mkdir(parents=True, exist_ok=True)
    rows = (await session.execute(
        select(Message, Channel)
        .join(Channel, Message.channel_id == Channel.id)
        .where(Message.channel_id.in_(channel_ids), Message.published_at >= start, Message.published_at < end)
        .order_by(Message.published_at.asc())
    )).all()
    message_ids = [message.id for message, _ in rows]
    image_rows = (await session.scalars(select(Image).where(Image.message_id.in_(message_ids)))).all() if message_ids else []
    images_by_message: dict[int, list[Image]] = {}
    for image in image_rows:
        images_by_message.setdefault(image.message_id, []).append(image)
    recommendation_counts = dict((await session.execute(
        select(Recommendation.message_id, func.count())
        .where(Recommendation.message_id.in_(message_ids)).group_by(Recommendation.message_id)
    )).all()) if message_ids else {}

    lines = [
        "EGX Intelligence analysis trace", f"Created: {created_at.isoformat()}",
        f"Window: {start.isoformat()} to {end.isoformat()}", f"Messages: {len(rows)}", "",
    ]
    copied_images = 0
    for message, channel in rows:
        lines += [
            f"[{message.published_at.isoformat()}] {channel.title or channel.handle} | Telegram message {message.telegram_message_id}",
            f"Recommendations extracted: {recommendation_counts.get(message.id, 0)}",
            message.text or "[No text]",
        ]
        for image in images_by_message.get(message.id, []):
            source = Path(image.path)
            destination = image_directory / f"{message.telegram_message_id}_{source.name}"
            if source.is_file():
                shutil.copy2(source, destination)
                copied_images += 1
                lines.append(f"Image: images/{destination.name}")
            else:
                lines.append(f"Image unavailable: {source}")
        lines.append("")
    text_path = directory / "messages.txt"
    text_path.write_text("\n".join(lines), encoding="utf-8")
    response_path = None
    if consolidated_response:
        response_path = directory / "consolidated-ai-response.json"
        response_path.write_text(consolidated_response, encoding="utf-8")
    return {"directory": str(directory), "text_path": str(text_path), "images_path": str(image_directory),
            "consolidated_response_path": str(response_path) if response_path else None,
            "message_count": len(rows), "image_count": copied_images}
