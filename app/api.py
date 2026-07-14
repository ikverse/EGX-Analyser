from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.ai.service import AIAnalysisService
from app.analysis_trace import export_analysis_trace
from app.config import get_settings
from app.config_store import update_config
from app.content_updates import ContentUpdateError, ContentUpdateService
from app.database import get_session
from app.diagnostics import diagnostics_path, logger, recent_entries
from app.models import Channel, Image, Media, Message, Recommendation, Report, Stock
from app.reports import ReportService
from app.schemas import (ChannelCreate, ChannelUpdate, CollectionRequest, DailyReportRequest, MessageCreate, SearchRequest, SettingsUpdate, TelegramChatSelect,
                         TelegramCodeRequest, TelegramCodeVerification)
from app.services import AnalyticsService, MessageService, SearchService
from app.repositories import get_or_create_channel
from app.telegram_auth import TelegramAuthenticator
from telethon import TelegramClient
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, AuthenticationError, BadRequestError, RateLimitError

router = APIRouter()
telegram_authenticator = TelegramAuthenticator()


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]: return {"status": "ok"}


@router.get("/diagnostics/recent", tags=["system"])
async def diagnostics(limit: int = 50) -> dict[str, object]:
    """Return locally stored, secret-free API diagnostics for troubleshooting."""
    return {"path": str(diagnostics_path()), "entries": recent_entries(min(max(limit, 1), 100))}


@router.get("/content-updates")
async def content_update_status() -> dict[str, object]:
    return ContentUpdateService(get_settings()).status()


@router.post("/content-updates/check")
async def check_content_updates() -> dict[str, object]:
    try:
        return await ContentUpdateService(get_settings()).check_and_apply()
    except ContentUpdateError as error:
        raise HTTPException(502, str(error)) from error


@router.get("/settings")
async def settings_status() -> dict[str, object]:
    settings = get_settings()
    session_path = f"{settings.telegram_session}.session"
    return {"openai_configured": bool(settings.openai_api_key),
            "ai_configured": bool(settings.ai_api_key),
            "ai_provider": settings.ai_provider,
            "telegram_configured": bool(settings.telegram_api_id and settings.telegram_api_hash),
            "telegram_authorized": Path(session_path).exists(),
            "openai_model": settings.openai_model, "telegram_session": settings.telegram_session,
            "analysis_instructions": settings.analysis_instructions}


@router.get("/models")
async def available_models() -> list[str]:
    settings = get_settings()
    provider = settings.ai_provider
    if not settings.ai_api_key:
        raise HTTPException(400, f"Save a {provider.title()} API key first")
    if provider != "openai":
        catalog_url = {
            "qwen": f"{settings.qwen_base_url.rstrip('/')}/models",
            "openrouter": "https://openrouter.ai/api/v1/models",
            "huggingface": "https://router.huggingface.co/v1/models",
        }[provider]
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(catalog_url, headers={"Authorization": f"Bearer {settings.ai_api_key}"})
                response.raise_for_status()
            catalog = response.json().get("data", [])
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if provider == "qwen" and status in (401, 403):
                raise HTTPException(
                    status,
                    "Qwen rejected this key. Create a pay-as-you-go Model Studio API key in the same region "
                    "as the selected endpoint. Beijing uses dashscope.aliyuncs.com, Singapore uses "
                    "dashscope-intl.aliyuncs.com, and US uses dashscope-us.aliyuncs.com. Token Plan, "
                    "Coding Plan, Qwen Chat, and expired temporary keys cannot be used here.",
                ) from error
            message = "rejected the saved API key" if status in (401, 403) else f"could not load models (status {status})"
            raise HTTPException(status if status < 500 else 502, f"{provider.title()} {message}. Try again shortly.") from error
        except httpx.HTTPError as error:
            raise HTTPException(503, f"Unable to connect to {provider.title()}. Check your internet connection and try again.") from error
        compatible = []
        for model in catalog:
            architecture = model.get("architecture") or {}
            modalities = architecture.get("input_modalities") or model.get("input_modalities") or []
            parameters = model.get("supported_parameters") or []
            if "image" in modalities and any(item in parameters for item in ("response_format", "structured_outputs")):
                compatible.append(model["id"])
        preferred = {"qwen": ["qwen3-vl-plus"], "openrouter": ["openrouter/free"]}.get(provider, [])
        return preferred + sorted(set(model for model in compatible if model not in preferred))
    try:
        models = await AsyncOpenAI(api_key=settings.openai_api_key).models.list()
    except AuthenticationError as error:
        raise HTTPException(401, "OpenAI rejected the saved API key. Replace it in Settings and save.") from error
    except RateLimitError as error:
        raise HTTPException(429, "OpenAI rate limit reached. Try loading models again shortly.") from error
    except APIConnectionError as error:
        raise HTTPException(503, "Unable to connect to OpenAI. Check your internet connection and try again.") from error
    except APIStatusError as error:
        raise HTTPException(502, f"OpenAI could not load models (status {error.status_code}). Try again shortly.") from error
    except Exception as error:
        raise HTTPException(502, "Unable to load available OpenAI models. Try again shortly.") from error
    allowed = [model.id for model in models.data if model.id.startswith("gpt-") and
               not any(term in model.id for term in ("audio", "realtime", "transcribe", "tts", "image", "chat"))]
    return sorted(set(allowed), reverse=True)


@router.put("/settings")
async def update_settings(payload: SettingsUpdate) -> dict[str, object]:
    current = get_settings()
    telegram_credentials_changed = (
        (payload.telegram_api_id is not None and payload.telegram_api_id != current.telegram_api_id)
        or (payload.telegram_api_hash is not None and payload.telegram_api_hash != current.telegram_api_hash)
    )
    values = {key.upper(): str(value) for key, value in payload.model_dump(exclude_none=True).items()}
    try:
        update_config(values)
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
        logger.error("settings_update_failed", error_type=type(error).__name__)
        raise HTTPException(500, "Settings could not be encrypted and saved. Try again after restarting the app.") from error
    get_settings.cache_clear()
    if telegram_credentials_changed:
        await telegram_authenticator.reset_session(current.telegram_session)
    return await settings_status()


@router.post("/telegram/request-code")
async def request_telegram_code(payload: TelegramCodeRequest) -> dict[str, str]:
    await telegram_authenticator.request_code(payload.phone)
    return {"status": "code_sent"}


@router.post("/telegram/verify-code")
async def verify_telegram_code(payload: TelegramCodeVerification) -> dict[str, bool]:
    return {"authorized": await telegram_authenticator.verify(payload.code, payload.password)}


@router.get("/telegram/chats")
async def telegram_chats() -> list[dict[str, str]]:
    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise HTTPException(400, "Save Telegram API credentials first")
    async with TelegramClient(settings.telegram_session, settings.telegram_api_id, settings.telegram_api_hash) as client:
        if not await client.is_user_authorized():
            raise HTTPException(400, "Connect Telegram in Settings first")
        dialogs = await client.get_dialogs()
    return [{"id": str(dialog.entity.id), "title": dialog.title or str(dialog.entity.id),
             "username": getattr(dialog.entity, "username", None) or "", "kind":
             "channel" if dialog.is_channel else "group" if dialog.is_group else "direct"}
            for dialog in dialogs]


@router.post("/messages")
async def create_message(payload: MessageCreate, session: AsyncSession = Depends(get_session)) -> dict:
    message = await MessageService(session).ingest(payload); await session.commit()
    return {"id": message.id, "created": message.processed_at is None}


@router.post("/messages/{message_id}/analyze")
async def analyze_message(message_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    message = await session.get(Message, message_id)
    if message is None: raise HTTPException(404, "Message not found")
    recommendations = await MessageService(session, AIAnalysisService(get_settings())).analyze(message); await session.commit()
    return {"recommendation_ids": [item.id for item in recommendations]}


@router.post("/collection/run")
async def run_collection() -> dict:
    from app.main import runtime
    try:
        summary = await runtime.collect_once()
        return {"messages_collected": summary["messages_analyzed"], **summary}
    except RuntimeError as error:
        if "already running" in str(error).lower():
            raise HTTPException(409, "A background collection is already running. Wait a moment and try again.") from error
        raise HTTPException(500, str(error)) from error
    except BadRequestError as error:
        raise HTTPException(400, f"The selected AI provider rejected the analysis request: {error}") from error


@router.post("/collection/analyze-selected")
async def analyze_selected_channels(payload: CollectionRequest, session: AsyncSession = Depends(get_session)) -> dict:
    from app.main import runtime
    from app.runtime import selected_analysis_start
    window_start = selected_analysis_start(payload.lookback_days)
    window_end = datetime.now(timezone.utc)
    try:
        collection = await runtime.collect_once(payload.channel_ids, since=window_start, analyze_messages=False)
        message_rows = (await session.execute(
            select(Message, Channel)
            .join(Channel, Message.channel_id == Channel.id)
            .where(
                Message.channel_id.in_(payload.channel_ids),
                Message.published_at >= window_start,
                Message.published_at < window_end,
            )
            .order_by(Message.published_at.asc())
        )).all()
        message_ids = [message.id for message, _ in message_rows]
        images_by_message: dict[int, list[str]] = {}
        transcripts_by_message: dict[int, list[str]] = {}
        if message_ids:
            image_rows = (await session.scalars(select(Image).where(Image.message_id.in_(message_ids)))).all()
            media_rows = (await session.scalars(select(Media).where(Media.message_id.in_(message_ids)))).all()
            for image in image_rows:
                if Path(image.path).is_file():
                    images_by_message.setdefault(image.message_id, []).append(image.path)
            for media in media_rows:
                if media.transcript:
                    transcripts_by_message.setdefault(media.message_id, []).append(media.transcript)
        batch_messages = [
            {
                "source": channel.title or channel.handle,
                "published_at": message.published_at.isoformat(),
                "telegram_message_id": message.telegram_message_id,
                "text": message.text,
                "image_paths": images_by_message.get(message.id, []),
                "transcripts": transcripts_by_message.get(message.id, []),
            }
            for message, channel in message_rows
        ]
        analysis_period = f"{window_start.date().isoformat()} to {window_end.date().isoformat()}"
        outcome = await AIAnalysisService(get_settings()).analyze_consolidated(batch_messages, analysis_period)
        consolidated_source = json.loads(outcome.raw_response)
        if not isinstance(consolidated_source, dict):
            raise RuntimeError("The AI provider returned a non-object response for the consolidated analysis")
        collection["messages_analyzed"] = len(batch_messages)
        trace = await export_analysis_trace(
            session, get_settings().storage_root, payload.channel_ids, window_start, window_end, outcome.raw_response
        )
        report = await ReportService(session, get_settings()).generate_selected_chat_report(
            payload.channel_ids, window_start, window_end, payload.lookback_days,
            consolidated_source=consolidated_source, consolidated_raw_response=outcome.raw_response,
        )
        await session.commit()
        channel_results = report.summary["channel_results"]
        return {"messages_collected": collection["messages_analyzed"], **collection,
                "window_start": window_start, "lookback_days": payload.lookback_days,
                "report": {"id": report.id, "markdown_path": report.markdown_path, "html_path": report.html_path,
                           "pdf_path": report.pdf_path,
                           "original_ai_response_text_path": report.summary["original_ai_response_text_path"],
                           "original_ai_response_pdf_path": report.summary["original_ai_response_pdf_path"]}, "channel_results": channel_results,
                "stock_code_summary": report.summary["stock_code_summary"],
                "stock_code_details": report.summary["stock_code_details"],
                "stock_source_table": report.summary["stock_source_table"],
                "trace": trace,
                "not_stock_related": [item["channel"] for item in channel_results if item["status"] == "not_stock_related"]}
    except RuntimeError as error:
        if "already running" in str(error).lower():
            raise HTTPException(409, "A background collection is already running. Wait a moment and try again.") from error
        raise HTTPException(500, str(error)) from error
    except BadRequestError as error:
        raise HTTPException(400, f"The selected AI provider rejected the analysis request: {error}") from error


@router.get("/messages")
async def list_messages(session: AsyncSession = Depends(get_session), limit: int = 50) -> list[dict]:
    messages = (await session.scalars(select(Message).order_by(Message.published_at.desc()).limit(min(limit, 100)))).all()
    return [{"id": item.id, "text": item.text, "published_at": item.published_at, "channel_id": item.channel_id} for item in messages]


@router.get("/channels")
async def list_channels(session: AsyncSession = Depends(get_session)) -> list[dict]:
    return [{"id": item.id, "handle": item.handle, "title": item.title, "active": item.active,
             "analyst_score": item.analyst_score} for item in (await session.scalars(select(Channel))).all()]


@router.post("/channels")
async def create_channel(payload: ChannelCreate, session: AsyncSession = Depends(get_session)) -> dict:
    channel = await get_or_create_channel(session, payload.handle)
    if payload.title:
        channel.title = payload.title
    channel.active = True
    await session.commit()
    return {"id": channel.id, "handle": channel.handle, "active": channel.active}


@router.post("/telegram/chats/select")
async def select_telegram_chat(payload: TelegramChatSelect, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        # Prefer the @username handle; fall back to the numeric entity ID.
        # For supergroups/channels the API returns IDs like "-1001234567890" — strip the
        # "-100" prefix so the stored handle is the plain channel ID used by Telethon.
        if payload.username:
            handle = payload.username
        else:
            raw = str(payload.id).lstrip("-")
            handle = raw[3:] if raw.startswith("100") else raw
        channel = await get_or_create_channel(session, handle)
        channel.title = payload.title
        channel.active = False
        await session.commit()
        return {"id": channel.id, "handle": channel.handle, "title": channel.title, "active": channel.active}
    except Exception as error:
        await session.rollback()
        logger().exception(
            "telegram_chat_selection_failed",
            extra={"error_type": type(error).__name__, "path": "/telegram/chats/select"},
        )
        raise HTTPException(500, "Unable to save this Telegram chat. Restart the local engine and try again.") from error


@router.patch("/channels/{channel_id}")
async def update_channel(channel_id: int, payload: ChannelUpdate, session: AsyncSession = Depends(get_session)) -> dict:
    channel = await session.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(404, "Channel not found")
    channel.active = payload.active
    await session.commit()
    return {"id": channel.id, "active": channel.active}


@router.get("/stocks")
async def list_stocks(session: AsyncSession = Depends(get_session)) -> list[dict]:
    return [{"id": item.id, "ticker": item.ticker, "name_en": item.name_en, "name_ar": item.name_ar} for item in (await session.scalars(select(Stock))).all()]


@router.get("/recommendations")
async def list_recommendations(session: AsyncSession = Depends(get_session)) -> list[dict]:
    values = (await session.scalars(select(Recommendation).order_by(Recommendation.id.desc()).limit(100))).all()
    return [{"id": item.id, "company": item.company_name, "ticker": item.ticker_raw, "signal": item.signal, "confidence": item.confidence, "target": item.target} for item in values]


@router.get("/analytics/consensus")
async def consensus(session: AsyncSession = Depends(get_session)) -> list[dict]: return await AnalyticsService(session).consensus()


@router.post("/reports/daily")
async def create_report(payload: DailyReportRequest = DailyReportRequest(), session: AsyncSession = Depends(get_session)) -> dict:
    report = await ReportService(session, get_settings()).generate_daily(payload.report_mode, payload.report_date); await session.commit()
    return {"id": report.id, "markdown_path": report.markdown_path, "html_path": report.html_path, "pdf_path": report.pdf_path}


@router.get("/reports")
async def reports(session: AsyncSession = Depends(get_session)) -> list[dict]:
    return [{"id": item.id, "date": item.report_date, "summary": item.summary, "markdown_path": item.markdown_path,
             "html_path": item.html_path, "pdf_path": item.pdf_path} for item in (await session.scalars(select(Report).order_by(Report.report_date.desc()))).all()]


@router.post("/search")
async def search(payload: SearchRequest, session: AsyncSession = Depends(get_session)) -> list[dict]:
    settings = get_settings()
    analyzer = AIAnalysisService(settings) if settings.ai_api_key else None
    return await SearchService(session, analyzer).search(payload.query, payload.limit)
