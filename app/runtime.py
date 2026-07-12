"""Local background work used by the standalone desktop application."""
import asyncio
from contextlib import suppress
import structlog
from sqlalchemy import select
from app.ai.service import AIAnalysisService
from app.collector.telegram import TelegramCollector
from app.config import get_settings
from app.database import SessionLocal
from app.models import Channel
from app.services import MessageService

log = structlog.get_logger()


class LocalRuntime:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="egx-local-collector")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def collect_once(self, channel_ids: list[int] | None = None) -> int:
        settings = get_settings()
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            return 0
        async with SessionLocal() as session:
            statement = select(Channel).where(Channel.active.is_(True))
            if channel_ids: statement = statement.where(Channel.id.in_(channel_ids))
            active = [channel.handle for channel in (await session.scalars(statement)).all()]
            if not active:
                return 0
            analyzer = AIAnalysisService(settings) if settings.openai_api_key else None
            count = await TelegramCollector(settings).collect_once(MessageService(session, analyzer), active)
            await session.commit()
            return count

    async def _run(self) -> None:
        while True:
            try:
                count = await self.collect_once()
                if count:
                    log.info("telegram_collection_complete", messages=count)
            except Exception as error:
                log.exception("telegram_collection_failed", error=str(error))
            await asyncio.sleep(60)
