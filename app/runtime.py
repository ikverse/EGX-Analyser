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
MAX_SELECTED_ANALYSIS_LOOKBACK_DAYS = 5


def empty_collection_summary() -> dict[str, int]:
    return {
        "messages_in_window": 0,
        "messages_analyzed": 0,
        "messages_reanalyzed": 0,
        "messages_already_saved": 0,
    }


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

    async def collect_once(self, channel_ids: list[int] | None = None, since: datetime | None = None) -> dict[str, int]:
        if self._collection_lock.locked():
            raise RuntimeError("A Telegram collection is already running")
        async with self._collection_lock:
            return await self._collect_once(channel_ids, since)

    async def _collect_once(self, channel_ids: list[int] | None = None, since: datetime | None = None) -> dict[str, int]:
        settings = get_settings()
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            return empty_collection_summary()
        async with SessionLocal() as session:
            statement = select(Channel)
            if channel_ids is not None:
                if not channel_ids:
                    return empty_collection_summary()
                statement = statement.where(Channel.id.in_(channel_ids))
            else:
                statement = statement.where(Channel.active.is_(True))
            active = [channel.handle for channel in (await session.scalars(statement)).all()]
            if not active:
                return empty_collection_summary()
            analyzer = AIAnalysisService(settings) if settings.ai_api_key else None
            count = await TelegramCollector(settings).collect_once(MessageService(session, analyzer), active, since)
            await session.commit()
            return count

    async def _run(self) -> None:
        while True:
            try:
                summary = await self.collect_once()
                if summary["messages_in_window"]:
                    log.info("telegram_collection_complete", **summary)
            except Exception as error:
                log.exception("telegram_collection_failed", error=str(error))
            await asyncio.sleep(60)


def selected_analysis_start(lookback_days: int = 3, now: datetime | None = None) -> datetime:
    if not 1 <= lookback_days <= MAX_SELECTED_ANALYSIS_LOOKBACK_DAYS:
        raise ValueError(f"The selected analysis range must be between 1 and {MAX_SELECTED_ANALYSIS_LOOKBACK_DAYS} days")
    return (now or datetime.now(timezone.utc)) - timedelta(days=lookback_days)
