from datetime import datetime, timezone
from pathlib import Path
import shutil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, Image, Message, Recommendation


async def export_analysis_trace(session: AsyncSession, storage_root: Path, channel_ids: list[int],
                                start: datetime, end: datetime) -> dict[str, object]:
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
    return {"directory": str(directory), "text_path": str(text_path), "images_path": str(image_directory),
            "message_count": len(rows), "image_count": copied_images}
