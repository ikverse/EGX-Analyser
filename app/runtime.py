"""Local background work used by the standalone desktop application."""
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy import select
from app.ai.service import AIAnalysisService
from app.collector.telegram import TelegramCollector
from app.config import get_settings
from app.database import SessionLocal
from app.models import Channel
from app.services import MessageService

log = structlog.get_logger()
SELECTED_ANALYSIS_LOOKBACK = timedelta(days=3)


class LocalRuntime:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._collection_lock = asyncio.Lock()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="egx-local-collector")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def collect_once(self, channel_ids: list[int] | None = None, since: datetime | None = None) -> int:
        if self._collection_lock.locked():
            raise RuntimeError("A Telegram collection is already running")
        async with self._collection_lock:
            return await self._collect_once(channel_ids, since)

    async def _collect_once(self, channel_ids: list[int] | None = None, since: datetime | None = None) -> int:
        settings = get_settings()
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            return 0
        async with SessionLocal() as session:
            statement = select(Channel)
            if channel_ids is not None:
                if not channel_ids:
                    return 0
                statement = statement.where(Channel.id.in_(channel_ids))
            else:
                statement = statement.where(Channel.active.is_(True))
            active = [channel.handle for channel in (await session.scalars(statement)).all()]
            if not active:
                return 0
            analyzer = AIAnalysisService(settings) if settings.ai_api_key else None
            count = await TelegramCollector(settings).collect_once(MessageService(session, analyzer), active, since)
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


def selected_analysis_start(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - SELECTED_ANALYSIS_LOOKBACK
