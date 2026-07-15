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


def _last_egx_open_day(value: date) -> date:
    """Resolve Egypt's Friday/Saturday weekly closure to the preceding Thursday."""
    while value.weekday() in (4, 5):
        value -= timedelta(days=1)
    return value


def _next_egx_open_day(value: date) -> date:
    """Return the next Sunday-through-Thursday EGX trading day after ``value``."""
    value += timedelta(days=1)
    while value.weekday() in (4, 5):
        value += timedelta(days=1)
    return value


def _egx_target_session(current: datetime) -> date:
    """Resolve the applicable EGX session for a Cairo-local analysis time."""
    if current.weekday() in (4, 5):
        return current.date() + timedelta(days=(6 - current.weekday()) % 7)

    market_close = time(14, 30)
    if current.timetz().replace(tzinfo=None) <= market_close:
        return current.date()
    return _next_egx_open_day(current.date())


def next_day_analysis_window(now: datetime | None = None) -> tuple[datetime, datetime, date]:
    """Use the current or next applicable EGX session and its source window."""
    cairo = ZoneInfo("Africa/Cairo")
    current = (now or datetime.now(timezone.utc)).astimezone(cairo)
    target_date = _egx_target_session(current)
    if target_date.weekday() == 6 and current.weekday() in (3, 4, 5):
        thursday = current.date()
        while thursday.weekday() != 3:
            thursday -= timedelta(days=1)
        start = datetime.combine(thursday, time.min, tzinfo=cairo).astimezone(timezone.utc)
    else:
        start = (current - timedelta(days=1)).astimezone(timezone.utc)
    end = current.astimezone(timezone.utc)
    return start, end, target_date


def selected_date_analysis_window(target_date: date, now: datetime | None = None) -> tuple[datetime, datetime, date]:
    """Use the selected date's prior Cairo day through the Analyze press time."""
    cairo = ZoneInfo("Africa/Cairo")
    target_date = _last_egx_open_day(target_date)
    start = datetime.combine(target_date - timedelta(days=1), time.min, tzinfo=cairo).astimezone(timezone.utc)
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return start, end, target_date
