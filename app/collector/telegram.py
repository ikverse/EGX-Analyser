from datetime import timezone
from sqlalchemy import select
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeAudio, MessageMediaDocument, MessageMediaPhoto
from app.config import Settings
from app.models import Channel, Image, Media
from app.schemas import MessageCreate
from app.services import MessageService


class TelegramCollector:
    def __init__(self, settings: Settings) -> None: self.settings = settings

    async def collect_once(self, service: MessageService, channel_handles: list[str] | None = None) -> int:
        if not self.settings.telegram_api_id or not self.settings.telegram_api_hash:
            raise RuntimeError("Telegram credentials are required")
        count = 0
        async with TelegramClient(self.settings.telegram_session, self.settings.telegram_api_id, self.settings.telegram_api_hash) as client:
            for handle in channel_handles if channel_handles is not None else self.settings.channels:
                channel = await service.session.scalar(select(Channel).where(Channel.handle == handle.lower().lstrip("@")))
                entity_reference: str | int = int(handle) if handle.lstrip("-").isdigit() else handle
                entity = await client.get_entity(entity_reference)
                min_id = channel.last_collected_message_id if channel and channel.last_collected_message_id else 0
                async for remote in client.iter_messages(entity, limit=250, min_id=min_id, reverse=True):
                    if not remote.date: continue
                    message = await service.ingest(MessageCreate(channel_handle=handle, telegram_message_id=remote.id,
                        published_at=remote.date.astimezone(timezone.utc), text=remote.message or "", views=remote.views))
                    if isinstance(remote.media, MessageMediaPhoto):
                        folder = self.settings.storage_root / "images" / handle / remote.date.strftime("%Y/%m/%d")
                        folder.mkdir(parents=True, exist_ok=True)
                        filename = folder / f"{remote.id}_{remote.photo.id}.jpg"
                        if not filename.exists(): await client.download_media(remote, file=str(filename))
                        image = await service.session.scalar(select(Image).where(Image.path == str(filename)))
                        if image is None:
                            service.session.add(Image(message_id=message.id, path=str(filename), mime_type="image/jpeg"))
                            await service.session.flush()
                    elif isinstance(remote.media, MessageMediaDocument) and remote.document:
                        attributes = remote.document.attributes or []
                        if any(isinstance(attribute, DocumentAttributeAudio) for attribute in attributes):
                            folder = self.settings.storage_root / "audio" / handle / remote.date.strftime("%Y/%m/%d")
                            folder.mkdir(parents=True, exist_ok=True)
                            filename = folder / f"{remote.id}_{remote.document.id}.ogg"
                            if not filename.exists():
                                await client.download_media(remote, file=str(filename))
                            media = await service.session.scalar(select(Media).where(Media.path == str(filename)))
                            if media is None:
                                media = Media(message_id=message.id, path=str(filename), mime_type="audio/ogg", kind="audio")
                                service.session.add(media)
                                await service.session.flush()
                            if service.analyzer is not None and media.processed_at is None:
                                try:
                                    media.transcript = await service.analyzer.transcribe(media.path)
                                except RuntimeError:
                                    media.transcript = None
                                media.processed_at = remote.date.astimezone(timezone.utc)
                    if service.analyzer is not None and message.processed_at is None:
                        await service.analyze(message)
                    if channel:
                        channel.last_collected_message_id = remote.id
                        channel.last_collected_at = datetime.now(timezone.utc)
                    count += 1
        return count
