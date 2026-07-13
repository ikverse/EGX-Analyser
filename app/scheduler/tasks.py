import asyncio
from celery import Celery
from sqlalchemy import select
from app.collector.telegram import TelegramCollector
from app.ai.service import AIAnalysisService
from app.config import get_settings
from app.database import SessionLocal
from app.models import Channel
from app.reports import ReportService
from app.services import MessageService

settings = get_settings()
celery_app = Celery("egx_intelligence", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.beat_schedule = {"telegram-every-minute": {"task": "app.scheduler.tasks.collect_telegram", "schedule": 60.0}, "daily-report": {"task": "app.scheduler.tasks.daily_report", "schedule": 86400.0}}


async def _collect() -> int:
    async with SessionLocal() as session:
        active_channels = [channel.handle for channel in (await session.scalars(
            select(Channel).where(Channel.active.is_(True))
        )).all()]
        analyzer = AIAnalysisService(settings) if settings.openai_api_key else None
        result = await TelegramCollector(settings).collect_once(
            MessageService(session, analyzer), active_channels or settings.channels
        )
        await session.commit()
        return result["messages_analyzed"]


@celery_app.task(name="app.scheduler.tasks.collect_telegram", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=5)
def collect_telegram() -> int: return asyncio.run(_collect())


async def _report() -> int:
    async with SessionLocal() as session:
        report = await ReportService(session, settings).generate_daily(); await session.commit(); return report.id


@celery_app.task(name="app.scheduler.tasks.daily_report", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=5)
def daily_report() -> int: return asyncio.run(_report())
