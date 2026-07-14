"""Local background work used by the standalone desktop application."""
import asyncio
from contextlib import suppress
from datetime import date, datetime, time, timedelta, timezone
import structlog
from sqlalchemy import select
from app.ai.service import AIAnalysisService
from app.collector.telegram import TelegramCollector
from app.config import get_settings
from app.database import SessionLocal
from app.models import Channel
from app.services import MessageService
from zoneinfo import ZoneInfo

log = structlog.get_logger()


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

    async def collect_once(self, channel_ids: list[int] | None = None, since: datetime | None = None,
                           analyze_messages: bool = True) -> dict[str, int]:
        if self._collection_lock.locked():
            raise RuntimeError("A Telegram collection is already running")
        async with self._collection_lock:
            return await self._collect_once(channel_ids, since, analyze_messages)

    async def _collect_once(self, channel_ids: list[int] | None = None, since: datetime | None = None,
                            analyze_messages: bool = True) -> dict[str, int]:
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
            count = await TelegramCollector(settings).collect_once(
                MessageService(session, analyzer), active, since, analyze_messages=analyze_messages
            )
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


def next_day_analysis_window(now: datetime | None = None) -> tuple[datetime, datetime, date]:
    """Use the exact two Cairo days before Analyze is pressed for tomorrow's suggestions."""
    cairo = ZoneInfo("Africa/Cairo")
    current = (now or datetime.now(timezone.utc)).astimezone(cairo)
    start = (current - timedelta(days=2)).astimezone(timezone.utc)
    end = current.astimezone(timezone.utc)
    return start, end, current.date() + timedelta(days=1)


def selected_date_analysis_window(target_date: date) -> tuple[datetime, datetime, date]:
    """Use the two Cairo calendar days before and including one selected target date.

    The exclusive end timestamp represents 00:00 of the following Cairo day, so
    all messages posted through 23:59:59 on the selected date are included.
    """
    cairo = ZoneInfo("Africa/Cairo")
    start = datetime.combine(target_date - timedelta(days=2), time.min, tzinfo=cairo).astimezone(timezone.utc)
    end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=cairo).astimezone(timezone.utc)
    return start, end, target_date
