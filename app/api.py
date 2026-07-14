from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import subprocess
from time import perf_counter
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
from app.stock_catalog import EGXStockCatalog
from app.schemas import (ChannelCreate, ChannelUpdate, CollectionRequest, DailyReportRequest, MessageCreate, SearchRequest, SettingsUpdate, TelegramChatSelect,
                         TelegramCodeRequest, TelegramCodeVerification)
from app.services import AnalyticsService, MessageService, SearchService
from app.repositories import get_or_create_channel
from app.telegram_auth import TelegramAuthenticator
from telethon import TelegramClient
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, AuthenticationError, BadRequestError, RateLimitError
from zoneinfo import ZoneInfo

router = APIRouter()

_QWEN_VISION_PREFERENCE = (
    "qwen3-vl-plus",
    "qwen3-vl-235b-a22b-instruct",
    "qwen3-vl-flash",
)


def _qwen_vision_models(catalog: list[object]) -> list[str]:
    """Return every accessible Qwen text-and-image model in a stable quality order."""
    available: dict[str, bool] = {}
    for item in catalog:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        model_id = item["id"].strip()
        architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        modalities = architecture.get("input_modalities") or item.get("input_modalities") or []
        supports_images = isinstance(modalities, list) and "image" in modalities
        known_vision_family = model_id.startswith(("qwen3-vl", "qwen-vl-", "qwen2.5-vl", "qvq"))
        if supports_images or known_vision_family:
            available[model_id] = True

    def priority(model_id: str) -> tuple[int, str]:
        for index, preferred in enumerate(_QWEN_VISION_PREFERENCE):
            if model_id == preferred or model_id.startswith(f"{preferred}-"):
                return index, model_id
        return len(_QWEN_VISION_PREFERENCE), model_id

    return sorted(available, key=priority)


def _ollama_api_url(settings) -> str:
    return settings.ollama_base_url.rstrip("/").removesuffix("/v1")


def _ollama_vision_models(catalog: list[object]) -> list[str]:
    """Return installed Ollama models that can accept images."""
    models: list[str] = []
    for item in catalog:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"].strip()
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        families = details.get("families") if isinstance(details.get("families"), list) else []
        supports_images = any("vision" in str(family).lower() or "vl" in str(family).lower() for family in families)
        known_vision_name = any(token in name.lower() for token in ("-vl", "llava", "minicpm-v", "gemma3", "moondream"))
        if supports_images or known_vision_name:
            models.append(name)
    preferred = ["qwen3-vl:4b", "qwen3-vl:8b"]
    return sorted(set(models), key=lambda model: (preferred.index(model) if model in preferred else len(preferred), model))
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


def egx_catalog(session: AsyncSession) -> EGXStockCatalog:
    settings = get_settings()
    return EGXStockCatalog(session, settings.egx_catalog_url, settings.storage_root, settings.egx_catalog_refresh_days)


@router.get("/egx-catalog")
async def egx_catalog_status(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    return await egx_catalog(session).status()


@router.post("/egx-catalog/refresh")
async def refresh_egx_catalog(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    result = await egx_catalog(session).ensure(force=True)
    await session.commit()
    if not result["refreshed"]:
        raise HTTPException(503, "Could not download the EGX catalog. Your saved local mapping is still available.")
    return result


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
            "openai_model": settings.openai_model, "ollama_model": settings.ollama_model,
            "ollama_base_url": settings.ollama_base_url, "telegram_session": settings.telegram_session,
            "analysis_instructions": settings.analysis_instructions}


@router.get("/models")
async def available_models() -> list[str]:
    settings = get_settings()
    provider = settings.ai_provider
    if provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{_ollama_api_url(settings)}/api/tags")
                response.raise_for_status()
            return _ollama_vision_models(response.json().get("models", []))
        except httpx.HTTPStatusError as error:
            raise HTTPException(502, f"Ollama could not list local models (status {error.response.status_code}).") from error
        except httpx.HTTPError as error:
            raise HTTPException(
                503,
                "Ollama is not reachable. Install and start Ollama, then confirm its local service is running.",
            ) from error
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
        if provider == "qwen":
            return _qwen_vision_models(catalog)
        compatible = []
        for model in catalog:
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                continue
            architecture = model.get("architecture") or {}
            modalities = architecture.get("input_modalities") or model.get("input_modalities") or []
            parameters = model.get("supported_parameters") or []
            if "image" in modalities and any(item in parameters for item in ("response_format", "structured_outputs")):
                compatible.append(model["id"])
        preferred = {"openrouter": ["openrouter/free"]}.get(provider, [])
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
    from app.runtime import next_day_analysis_window, selected_date_analysis_window
    cairo = ZoneInfo("Africa/Cairo")
    if payload.analysis_mode == "specific_date":
        if payload.target_date is None:
            raise HTTPException(422, "Choose a target date for historical analysis.")
        if payload.target_date > datetime.now(timezone.utc).astimezone(cairo).date():
            raise HTTPException(422, "Historical analysis can only use today or an earlier Cairo date.")
        window_start, window_end, target_date = selected_date_analysis_window(payload.target_date)
        report_label = f"selected-date suggestions ({target_date.isoformat()})"
    else:
        window_start, window_end, target_date = next_day_analysis_window()
        report_label = f"next-day suggestions ({target_date.isoformat()})"
    source_start_date = window_start.astimezone(cairo).date().isoformat()
    source_end_date = (target_date if payload.analysis_mode == "specific_date" else window_end.astimezone(cairo).date()).isoformat()
    analysis_period = f"Source messages: {source_start_date} through {source_end_date}; target date: {target_date.isoformat()}"
    content_types = set(payload.content_types)
    analysis_started = perf_counter()
    try:
        collection = await runtime.collect_once(payload.channel_ids, since=window_start, analyze_messages=False)
        collection_ms = round((perf_counter() - analysis_started) * 1000)
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
        if message_ids and "images" in content_types:
            image_rows = (await session.scalars(select(Image).where(Image.message_id.in_(message_ids)))).all()
            for image in image_rows:
                if Path(image.path).is_file():
                    images_by_message.setdefault(image.message_id, []).append(image.path)
        if message_ids and "audio" in content_types:
            media_rows = (await session.scalars(select(Media).where(Media.message_id.in_(message_ids)))).all()
            for media in media_rows:
                if media.transcript:
                    transcripts_by_message.setdefault(media.message_id, []).append(media.transcript)
        batch_messages = []
        for message, channel in message_rows:
            selected_text = message.text if "text" in content_types else ""
            selected_images = images_by_message.get(message.id, [])
            selected_transcripts = transcripts_by_message.get(message.id, [])
            if not selected_text.strip() and not selected_images and not selected_transcripts:
                continue
            batch_messages.append({
                "source": channel.title or channel.handle,
                "published_at": message.published_at.astimezone(cairo).isoformat(),
                "telegram_message_id": message.telegram_message_id,
                "text": selected_text,
                "image_paths": selected_images,
                "transcripts": selected_transcripts,
            })
        outcome = await AIAnalysisService(get_settings()).analyze_consolidated(
            batch_messages, analysis_period, target_date.isoformat()
        )
        model_completed = perf_counter()
        consolidated_source = json.loads(outcome.raw_response)
        if not isinstance(consolidated_source, dict):
            raise RuntimeError("The AI provider returned a non-object response for the consolidated analysis")
        catalog = egx_catalog(session)
        catalog_refresh = await catalog.ensure()
        await catalog.enrich_consolidated_output(consolidated_source)
        collection["messages_analyzed"] = len(batch_messages)
        trace = await export_analysis_trace(
            session, get_settings().storage_root, payload.channel_ids, window_start, window_end, outcome.raw_response
        )
        report = await ReportService(session, get_settings()).generate_selected_chat_report(
            payload.channel_ids, window_start, window_end, 2,
            consolidated_source=consolidated_source, consolidated_raw_response=outcome.raw_response,
            report_label=report_label,
        )
        report_generation_ms = round((perf_counter() - model_completed) * 1000)
        report.summary = {**report.summary, **{
            "analysis_result": True,
            "target_date": target_date.isoformat(),
            "analysis_window_mode": payload.analysis_mode,
            "source_window_start": window_start.isoformat(),
            "source_window_end": window_end.isoformat(),
            "content_types": sorted(content_types),
            "messages_analyzed": len(batch_messages),
            "analysis_trace_directory": trace["directory"],
        }}
        await session.commit()
        logger().info(
            "analysis_performance",
            extra={
                "collection_ms": collection_ms,
                "report_generation_ms": report_generation_ms,
                "total_analysis_ms": round((perf_counter() - analysis_started) * 1000),
                "catalog_changes": catalog_refresh["changed"],
                "catalog_refreshed": catalog_refresh["refreshed"],
                **outcome.input_metrics,
            },
        )
        channel_results = report.summary["channel_results"]
        return {"messages_collected": collection["messages_analyzed"], **collection,
                "window_start": window_start, "window_end": window_end, "target_date": target_date.isoformat(),
                "analysis_mode": payload.analysis_mode,
                "content_types": sorted(content_types),
                "report": {"id": report.id, "markdown_path": report.markdown_path, "html_path": report.html_path,
                           "original_ai_response_text_path": report.summary["original_ai_response_text_path"]}, "channel_results": channel_results,
                "stock_code_summary": report.summary["stock_code_summary"],
                "stock_code_details": report.summary["stock_code_details"],
                "stock_source_table": report.summary["stock_source_table"],
                "client_inquiry_responses": report.summary["client_inquiry_responses"],
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
    return {"id": report.id, "markdown_path": report.markdown_path, "html_path": report.html_path}


@router.get("/reports")
async def reports(session: AsyncSession = Depends(get_session)) -> list[dict]:
    return [{"id": item.id, "date": item.report_date, "summary": item.summary, "markdown_path": item.markdown_path,
             "html_path": item.html_path} for item in (await session.scalars(select(Report).order_by(Report.report_date.desc()))).all()]


@router.get("/analysis-results")
async def analysis_results(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Return saved batch-analysis outputs for the expandable Results history."""
    stored_reports = (await session.scalars(select(Report).order_by(Report.report_date.desc()))).all()
    return [
        {
            "id": item.id,
            "generated_at": item.report_date,
            "target_date": item.summary.get("target_date"),
            "messages_analyzed": item.summary.get("messages_analyzed", 0),
            "content_types": item.summary.get("content_types", ["text", "images", "audio"]),
            "stock_source_table": item.summary.get("stock_source_table", []),
            "client_inquiry_responses": item.summary.get("client_inquiry_responses", []),
        }
        for item in stored_reports
        if item.summary.get("analysis_result") or item.summary.get("analysis_mode") == "consolidated_batch"
    ]


def _delete_managed_artifact(storage_root: Path, value: object, directory: bool = False) -> None:
    if not isinstance(value, str) or not value:
        return
    try:
        root = storage_root.resolve()
        candidate = Path(value).resolve()
        if candidate != root and root not in candidate.parents:
            return
        if directory:
            if candidate.is_dir():
                shutil.rmtree(candidate)
        elif candidate.is_file():
            candidate.unlink()
    except OSError:
        return


@router.delete("/analysis-results/{report_id}")
async def delete_analysis_result(report_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    """Delete one saved batch result and its report/trace artifacts."""
    report = await session.get(Report, report_id)
    if report is None or not (report.summary.get("analysis_result") or report.summary.get("analysis_mode") == "consolidated_batch"):
        raise HTTPException(404, "Analysis result not found")

    settings = get_settings()
    summary = report.summary
    for path in (
        report.markdown_path,
        report.html_path,
        summary.get("original_ai_response_text_path"),
    ):
        _delete_managed_artifact(settings.storage_root, path)
    _delete_managed_artifact(settings.storage_root, summary.get("analysis_trace_directory"), directory=True)
    await session.delete(report)
    await session.commit()
    return {"deleted": True}


@router.post("/search")
async def search(payload: SearchRequest, session: AsyncSession = Depends(get_session)) -> list[dict]:
    settings = get_settings()
    analyzer = AIAnalysisService(settings) if settings.ai_api_key else None
    return await SearchService(session, analyzer).search(payload.query, payload.limit)
