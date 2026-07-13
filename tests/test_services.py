from datetime import datetime, timedelta, timezone
import asyncio
import io
import json
import os
from pathlib import Path
import pytest
from fastapi import HTTPException
from httpx import Request, Response
from openai import AuthenticationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app import api
from app.models import Base, Image, Recommendation, StockMention
from app.schemas import AnalysisResult, ExtractedRecommendation, ExtractedStockMention, MessageCreate, TelegramChatSelect
from app.ai.service import _analysis_result_from_payload, analysis_output_schema
from app.services import AnalyticsService, MessageService, SearchService
from app.config_store import load_secrets_into_environment, update_config
from app.content_updates import ContentUpdateService, generate_seed, public_key_from_seed, sign_bytes, verify_bytes
from app.telegram_auth import TelegramAuthenticator
from app.runtime import selected_analysis_start
from app.collector.telegram import is_promotional_message
from app.reports import ReportService
from app.analysis_trace import export_analysis_trace
from app.repositories import StockRepository


QWEN_CONSOLIDATED_OUTPUT = {
    "analysis_period": "Last 3 Days",
    "top_consolidated_recommendations": [{
        "stock_code": "MFPC", "stock_name_en": "Mobaco", "stock_name_ar": "موبكو", "mention_count": 3, "rank": 1, "status": "active",
        "data_points": [{"date": "2026-07-12", "source": "CFI", "buy_price": 37.25, "target_1": 38.7,
                         "target_2": 40.0, "stop_loss": 35.55, "support": None, "resistance": None,
                         "expected_return_pct": 3.18, "risk_pct": -1.84}],
        "analysis_summary_ar": "توصية شراء قوية",
    }],
    "achieved_targets": [{"stock_code": "EFII", "stock_name_en": "E-Finance", "status_ar": "تم تحقيق المستهدف", "date": "2026-07-12", "source": "CFI"}],
    "text_based_categories": {"most_important_stocks": [{"stock_code": "MFPC", "stock_name_en": "Mobaco", "stock_name_ar": "موبكو"}], "trading_stocks": [{"stock_code": "MFPC", "stock_name_en": "Mobaco", "stock_name_ar": "موبكو"}], "watchlist_stocks": [{"stock_code": "EFII", "stock_name_en": "E-Finance", "stock_name_ar": "إي فاينانس"}]},
    "daily_breakdown": {"2026-07-12": {"total_mentions": 3, "top_stock_of_day": "MFPC"}},
}


class FakeAnalyzer:
    async def analyze(self, text: str, image_paths: list[str], transcripts: list[str] | None = None) -> AnalysisResult:
        assert image_paths == ["chart.jpg"]
        assert transcripts == []
        return AnalysisResult(recommendations=[ExtractedRecommendation(
            company_name="Commercial International Bank", ticker="CIB", signal="BUY", confidence=.91
        )], image_observations=["RSI bullish"])

    async def embed(self, content: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "CIB" in content else [0.0, 1.0, 0.0]


class StockMentionOnlyAnalyzer:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, text: str, image_paths: list[str], transcripts: list[str] | None = None) -> AnalysisResult:
        self.calls += 1
        return AnalysisResult(stock_mentions=[ExtractedStockMention(ticker="COMI", company_name="CIB", confidence=.8)])

    async def embed(self, content: str) -> list[float]:
        return []


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as current: yield current
    await engine.dispose()


async def test_message_ingestion_is_idempotent(session):
    service = MessageService(session)
    payload = MessageCreate(channel_handle="EGXSignals", telegram_message_id=3, text="شراء CIB", published_at=datetime.now(timezone.utc))
    first, second = await service.ingest(payload), await service.ingest(payload)
    assert first.id == second.id


async def test_channel_creation_normalizes_and_reuses_telegram_chat(session):
    first = await api.get_or_create_channel(session, "@EGXSignals")
    second = await api.get_or_create_channel(session, "egxsignals")
    assert first.id == second.id
    assert first.handle == "egxsignals"


async def test_selected_telegram_chat_is_not_persisted_as_active(session):
    result = await api.select_telegram_chat(TelegramChatSelect(id="123", title="Signals"), session)
    assert result["active"] is False


async def test_consensus_counts_signals(session):
    message = await MessageService(session).ingest(MessageCreate(channel_handle="signals", telegram_message_id=1, published_at=datetime.now(timezone.utc)))
    session.add_all([Recommendation(message_id=message.id, company_name="CIB", signal="BUY", confidence=.9, indicators=[]), Recommendation(message_id=message.id, company_name="CIB", signal="BUY", confidence=.8, indicators=[]), Recommendation(message_id=message.id, company_name="CIB", signal="SELL", confidence=.7, indicators=[])])
    await session.flush()
    result = await AnalyticsService(session).consensus()
    assert result[0]["sentiment"] == "BUY" and result[0]["buy_count"] == 2


async def test_analysis_is_idempotent_and_persists_embedding(session):
    message = await MessageService(session).ingest(MessageCreate(
        channel_handle="signals", telegram_message_id=9, text="BUY CIB", published_at=datetime.now(timezone.utc)
    ))
    session.add(Image(message_id=message.id, path="chart.jpg", mime_type="image/jpeg"))
    await session.flush()
    service = MessageService(session, FakeAnalyzer())
    first = await service.analyze(message)
    second = await service.analyze(message)
    assert len(first) == len(second) == 1
    assert '"ticker": "CIB"' in (message.ai_response_raw or "")
    assert (await SearchService(session, FakeAnalyzer()).search("CIB outlook", 5))[0]["id"] == message.id


async def test_stock_code_only_analysis_is_not_repeated(session):
    message = await MessageService(session).ingest(MessageCreate(
        channel_handle="signals", telegram_message_id=10, text="COMI table", published_at=datetime.now(timezone.utc)
    ))
    analyzer = StockMentionOnlyAnalyzer()
    service = MessageService(session, analyzer)
    await service.analyze(message)
    await service.analyze(message)
    assert analyzer.calls == 1
    await service.analyze(message, force=True)
    assert analyzer.calls == 2
    assert len((await session.scalars(StockMention.__table__.select())).all()) == 1


def test_qwen_consolidated_output_normalizes_to_recommendations():
    result = _analysis_result_from_payload(QWEN_CONSOLIDATED_OUTPUT)
    assert result.stock_mentions[0].ticker == "MFPC"
    assert result.stock_mentions[0].table_data["stock_name_ar"] == "موبكو"
    assert result.recommendations[0].entry == 37.25
    assert result.recommendations[0].target_2 == 40.0


def test_local_settings_encrypt_secrets(monkeypatch, tmp_path):
    config_file = tmp_path / ".env"
    monkeypatch.setenv("EGX_CONFIG_FILE", str(config_file))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    update_config({"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "gpt-5.5",
                   "ANALYSIS_INSTRUCTIONS": "Prioritize EGX tables.\nحلل أسهم EGX مع سياق القناة."})
    assert "test-secret" not in config_file.read_text(encoding="utf-8")
    assert (tmp_path / "secrets.json").exists()
    load_secrets_into_environment()
    assert os.environ["OPENAI_API_KEY"] == "test-secret"
    assert os.environ["ANALYSIS_INSTRUCTIONS"] == "Prioritize EGX tables.\nحلل أسهم EGX مع سياق القناة."


@pytest.mark.asyncio
async def test_reset_telegram_session_removes_persisted_files(tmp_path):
    session_path = tmp_path / "telegram"
    for suffix in (".session", ".session-journal", ".session-shm", ".session-wal"):
        (tmp_path / f"telegram{suffix}").write_text("test", encoding="utf-8")
    await TelegramAuthenticator().reset_session(str(session_path))
    assert not list(tmp_path.glob("telegram.session*"))


async def test_model_listing_masks_invalid_openai_key(monkeypatch):
    class FailingModels:
        async def list(self):
            response = Response(401, request=Request("GET", "https://api.openai.com/v1/models"))
            raise AuthenticationError("invalid key", response=response, body=None)

    class FailingClient:
        models = FailingModels()

    monkeypatch.setattr(api, "get_settings", lambda: type("Settings", (), {
        "ai_provider": "openai", "ai_api_key": "test-key", "openai_api_key": "test-key"
    })())
    monkeypatch.setattr(api, "AsyncOpenAI", lambda **_: FailingClient())

    with pytest.raises(HTTPException) as error:
        await api.available_models()

    assert error.value.status_code == 401
    assert error.value.detail == "OpenAI rejected the saved API key. Replace it in Settings and save."


def test_analysis_output_schema_is_strict_for_openai():
    schema = analysis_output_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    recommendation = schema["$defs"]["ExtractedRecommendation"]
    assert recommendation["additionalProperties"] is False
    assert set(recommendation["required"]) == set(recommendation["properties"])


def test_analysis_result_normalizes_common_model_field_aliases():
    result = _analysis_result_from_payload({
        "recommendations": [{"code": "COMI", "company": "CIB", "action": "buy", "tp1": "100", "confidence": "0.9"}],
        "stock_mentions": [{"code": "COMI", "company": "CIB", "table_data": {"entry": 92}}],
        "image_observations": ["Bullish chart"],
    })
    assert result.recommendations[0].ticker == "COMI"
    assert result.recommendations[0].signal.value == "BUY"
    assert result.recommendations[0].target == 100.0
    assert result.stock_mentions[0].ticker == "COMI"


def test_content_pack_signature_matches_ed25519_reference_vector():
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    payload = b""
    signature = sign_bytes(seed, payload)
    assert public_key_from_seed(seed).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert signature.hex() == (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    assert verify_bytes(public_key_from_seed(seed), payload, signature)
    assert not verify_bytes(public_key_from_seed(seed), payload + b"x", signature)


def test_content_pack_installs_prompt_and_aliases(tmp_path):
    import zipfile

    settings = type("Settings", (), {"storage_root": tmp_path, "content_pack_manifest_url": "https://example.test/pack"})()
    manager = ContentUpdateService(settings)
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("recommendation.md", "Updated prompt")
        archive.writestr("stock_aliases.json", '{"aliases":{"CIB Arabic":"CIB"}}')
    manager._install_archive("1.0.0", archive_bytes.getvalue())
    assert manager.active_version() == "1.0.0"
    assert manager.file_path("recommendation.md").read_text(encoding="utf-8") == "Updated prompt"
    assert manager.stock_aliases()["cib arabic"] == "CIB"


def test_selected_analysis_starts_three_days_before_request():
    requested_at = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    assert selected_analysis_start(now=requested_at) == datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    assert selected_analysis_start(5, requested_at) == datetime(2026, 7, 8, 12, tzinfo=timezone.utc)


def test_promotional_messages_are_skipped_without_hiding_trade_posts():
    assert is_promotional_message("إعلان: اشترك في قناتنا المدفوعة للحصول على خصم")
    assert not is_promotional_message("اشترك معنا: شراء CIB دخول 92 هدف 100")


async def test_selected_chat_report_marks_non_stock_context(session, tmp_path):
    stock_message = await MessageService(session).ingest(MessageCreate(
        channel_handle="stocks", telegram_message_id=1, text="BUY CIB entry 90", published_at=datetime.now(timezone.utc)
    ))
    non_stock_message = await MessageService(session).ingest(MessageCreate(
        channel_handle="general", telegram_message_id=1, text="Football match news", published_at=datetime.now(timezone.utc)
    ))
    stock = await StockRepository(session).resolve("CIB", "Commercial International Bank")
    stock_message.ai_response_raw = '{"recommendations":[{"ticker":"CIB","signal":"BUY"}]}'
    session.add(Recommendation(message_id=stock_message.id, stock_id=stock.id, company_name="CIB", ticker_raw="CIB", signal="BUY", confidence=.9, indicators=[]))
    session.add(StockMention(message_id=stock_message.id, stock_id=stock.id, ticker_raw="CIB", company_name_raw="Commercial International Bank", context="CIB row", table_data={"price": "92.5", "target": "100"}, confidence=.9))
    await session.flush()
    report = await ReportService(session, type("Settings", (), {"storage_root": tmp_path})()).generate_selected_chat_report(
        [stock_message.channel_id, non_stock_message.channel_id], datetime.now(timezone.utc) - timedelta(days=3), datetime.now(timezone.utc) + timedelta(minutes=1), 3
    )
    statuses = {item["channel"]: item["status"] for item in report.summary["channel_results"]}
    assert statuses["stocks"] == "recommendations_found"
    assert statuses["general"] == "not_stock_related"
    assert report.summary["stock_code_summary"][0]["ticker"] == "CIB"
    assert report.summary["stock_code_summary"][0]["by_chat"]["stocks"] == 1
    details = report.summary["stock_code_details"]
    assert details == [{"ticker": "CIB", "company": "Commercial International Bank", "channel": "stocks",
                        "occurrences": 1, "details": [{"price": "92.5", "target": "100", "context": "CIB row"}]}]
    raw_text_path = Path(report.summary["original_ai_response_text_path"])
    raw_pdf_path = Path(report.summary["original_ai_response_pdf_path"])
    assert raw_text_path.exists() and raw_pdf_path.exists()
    assert stock_message.ai_response_raw in raw_text_path.read_text(encoding="utf-8")


async def test_report_uses_qwen_consolidated_source(session, tmp_path):
    message = await MessageService(session).ingest(MessageCreate(
        channel_handle="signals", telegram_message_id=15, text="MFPC", published_at=datetime.now(timezone.utc)
    ))
    message.ai_response_raw = json.dumps(QWEN_CONSOLIDATED_OUTPUT, ensure_ascii=False)
    await session.flush()
    report = await ReportService(session, type("Settings", (), {"storage_root": tmp_path})()).generate_selected_chat_report(
        [message.channel_id], datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc) + timedelta(minutes=1), 1
    )
    assert report.summary["consolidated_source"]["analysis_period"] == "Last 3 Days"
    assert report.summary["stock_code_details"][0]["channel"] == "CFI"
    assert "Qwen consolidated analysis" in Path(report.markdown_path).read_text(encoding="utf-8")


async def test_analysis_trace_saves_message_text_and_images(session, tmp_path):
    message = await MessageService(session).ingest(MessageCreate(
        channel_handle="signals", telegram_message_id=8, text="BUY CIB", published_at=datetime.now(timezone.utc)
    ))
    source_image = tmp_path / "source-chart.jpg"
    source_image.write_bytes(b"chart")
    session.add(Image(message_id=message.id, path=str(source_image), mime_type="image/jpeg"))
    await session.flush()
    trace = await export_analysis_trace(
        session, tmp_path / "storage", [message.channel_id], datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc) + timedelta(minutes=1)
    )
    assert "BUY CIB" in Path(str(trace["text_path"])).read_text(encoding="utf-8")
    assert Path(str(trace["images_path"])).joinpath("8_source-chart.jpg").read_bytes() == b"chart"


async def test_stock_repository_persists_learned_ticker_name_mapping(session):
    repository = StockRepository(session)
    stock = await repository.resolve("cib", "Commercial International Bank")
    same_stock = await repository.resolve("CIB", "البنك التجاري الدولي")
    assert stock.id == same_stock.id
    assert same_stock.name_en == "Commercial International Bank"
    assert "البنك التجاري الدولي" in same_stock.aliases


async def test_collection_lock_returns_409(monkeypatch):
    """A manual collection request while the background lock is held must get 409."""
    from app import api as api_module
    from app.runtime import LocalRuntime

    locked_runtime = LocalRuntime()
    # Acquire the lock so collect_once raises immediately.
    await locked_runtime._collection_lock.acquire()

    monkeypatch.setattr(api_module, "runtime", locked_runtime, raising=False)
    # Patch the module-level import used inside run_collection.
    import app.main as main_module
    monkeypatch.setattr(main_module, "runtime", locked_runtime)

    with pytest.raises(HTTPException) as exc_info:
        await api_module.run_collection()

    assert exc_info.value.status_code == 409
    assert "already running" in exc_info.value.detail.lower()
    locked_runtime._collection_lock.release()
