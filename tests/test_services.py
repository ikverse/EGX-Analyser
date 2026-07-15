from datetime import datetime, timedelta, timezone
import base64
import asyncio
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from httpx import Request, Response
from openai import AuthenticationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app import api
from app.models import Base, Image, Recommendation, Report, StockMention
from app.schemas import AnalysisResult, CollectionRequest, ExtractedRecommendation, ExtractedStockMention, MessageCreate, TelegramChatSelect
from app.ai.service import (
    _analysis_result_from_payload,
    _prepared_image_data_url,
    _write_provider_request_trace,
    analysis_output_schema,
)
from app.reports import _client_inquiry_rows, _consolidated_source_table
from app.services import AnalyticsService, MessageService, SearchService
from app.config_store import load_secrets_into_environment, update_config
from app.content_updates import ContentUpdateService, generate_seed, public_key_from_seed, sign_bytes, verify_bytes
from app.telegram_auth import TelegramAuthenticator
from app.runtime import next_day_analysis_window, selected_date_analysis_window
from app.collector.telegram import is_promotional_message
from app.reports import ReportService
from app.analysis_trace import create_selected_input_trace, export_analysis_trace, save_consolidated_response
from app.analysis_filter import has_past_recommendation_context
from app.analysis_validation import enforce_client_inquiry_separation, validate_consolidated_output
from app.repositories import StockRepository
from app.stock_catalog import EGXStockCatalog, normalize_stock_name


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


def test_qwen_vision_models_prioritize_and_return_all_accessible_models():
    catalog = [
        {"id": "qwen-plus", "architecture": {"input_modalities": ["text"]}},
        {"id": "qwen3-vl-flash", "architecture": {"input_modalities": ["text", "image"]}},
        {"id": "qwen-vl-max", "architecture": {"input_modalities": ["text", "image"]}},
        {"id": "qwen3-vl-235b-a22b-instruct"},
        {"id": "qwen3-vl-plus-2026-01-01"},
    ]

    assert api._qwen_vision_models(catalog) == [
        "qwen3-vl-plus-2026-01-01",
        "qwen3-vl-235b-a22b-instruct",
        "qwen3-vl-flash",
        "qwen-vl-max",
    ]


def test_ollama_vision_models_exclude_text_only_models_and_prefer_qwen():
    catalog = [
        {"name": "qwen3:4b", "details": {"families": ["qwen3"]}},
        {"name": "llava:7b", "details": {"families": ["llama", "clip"]}},
        {"name": "qwen3-vl:8b", "details": {"families": ["qwen3vl", "vision"]}},
        {"name": "qwen3-vl:4b", "details": {"families": ["qwen3vl", "vision"]}},
    ]

    assert api._ollama_vision_models(catalog) == ["qwen3-vl:4b", "qwen3-vl:8b", "llava:7b"]

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


async def test_egx_catalog_fills_only_missing_model_identity(session):
    catalog = EGXStockCatalog(session, "https://catalog.invalid/stocks")
    await catalog._upsert([{
        "ticker": "COMI", "name_en": "Commercial International Bank Egypt", "name_ar": "البنك التجاري الدولي",
        "aliases": "CIB|التجاري الدولي",
    }])
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": None, "stock_name_en": "", "stock_name_ar": "التجاري الدولي",
            "data_points": [],
        }],
        "achieved_targets": [], "client_inquiry_responses": [], "text_based_categories": {},
    }

    await catalog.enrich_consolidated_output(payload)
    stock = payload["top_consolidated_recommendations"][0]
    assert stock["stock_code"] == "COMI"
    assert stock["stock_name_en"] == "Commercial International Bank Egypt"
    assert stock["stock_name_ar"] == "التجاري الدولي"
    assert normalize_stock_name("إلـى البنك التجاري الدولي") == normalize_stock_name("الى البنك التجاري الدولي")


async def test_egx_catalog_does_not_replace_model_identity(session):
    catalog = EGXStockCatalog(session, "https://catalog.invalid/stocks")
    await catalog._upsert([{
        "ticker": "COMI", "name_en": "Commercial International Bank Egypt", "name_ar": "CIB Arabic",
        "aliases": "CIB",
    }])
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "COMI", "stock_name_en": "Model Name", "stock_name_ar": "Model Arabic", "data_points": [],
        }],
        "achieved_targets": [], "client_inquiry_responses": [], "text_based_categories": {},
    }

    await catalog.enrich_consolidated_output(payload)

    stock = payload["top_consolidated_recommendations"][0]
    assert stock["stock_code"] == "COMI"
    assert stock["stock_name_en"] == "Model Name"
    assert stock["stock_name_ar"] == "Model Arabic"


async def test_egx_catalog_refresh_cache_waits_until_the_weekly_interval(session, tmp_path):
    catalog = EGXStockCatalog(session, "https://catalog.invalid/stocks", tmp_path, refresh_days=7)
    catalog._save_state({"last_successful_refresh": datetime.now(timezone.utc).isoformat()})

    assert not catalog._refresh_due(catalog._state(), force=False)
    assert catalog._refresh_due(catalog._state(), force=True)
    catalog._save_state({"last_successful_refresh": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()})
    assert catalog._refresh_due(catalog._state(), force=False)


async def test_analysis_results_returns_only_batch_analysis_reports(session):
    now = datetime.now(timezone.utc)
    session.add_all([
        Report(
            report_date=now,
            markdown_path="analysis.md",
            html_path="analysis.html",
            pdf_path="analysis.pdf",
            summary={
                "analysis_result": True,
                "target_date": "2026-07-15",
                "messages_analyzed": 4,
                "stock_source_table": [{"ticker": "COMI", "source": "CFI"}],
            },
        ),
        Report(
            report_date=now - timedelta(minutes=1),
            markdown_path="daily.md",
            html_path="daily.html",
            pdf_path="daily.pdf",
            summary={"mode": "calendar"},
        ),
    ])
    await session.commit()

    results = await api.analysis_results(session)

    assert len(results) == 1
    assert results[0]["target_date"] == "2026-07-15"
    assert results[0]["stock_source_table"][0]["ticker"] == "COMI"


def test_selected_analysis_requires_valid_content_types():
    assert CollectionRequest(channel_ids=[1]).content_types == {"text", "images", "audio"}
    assert CollectionRequest(channel_ids=[1], content_types={"images"}).content_types == {"images"}
    with pytest.raises(ValidationError):
        CollectionRequest(channel_ids=[1], content_types=set())
    with pytest.raises(ValidationError):
        CollectionRequest(channel_ids=[1], content_types={"video"})


async def test_delete_analysis_result_removes_managed_files(session, tmp_path, monkeypatch):
    report_file = tmp_path / "reports" / "result.pdf"
    raw_file = tmp_path / "reports" / "raw.txt"
    trace_directory = tmp_path / "analysis-traces" / "2026-07-14" / "120000"
    report_file.parent.mkdir(parents=True)
    trace_directory.mkdir(parents=True)
    report_file.write_text("report")
    raw_file.write_text("raw")
    (trace_directory / "messages.txt").write_text("trace")
    report = Report(
        markdown_path=str(report_file), html_path=str(report_file), pdf_path=str(report_file),
        summary={
            "analysis_result": True,
            "original_ai_response_text_path": str(raw_file),
            "analysis_trace_directory": str(trace_directory),
        },
    )
    session.add(report)
    await session.commit()
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(storage_root=tmp_path))

    response = await api.delete_analysis_result(report.id, session)

    assert response == {"deleted": True}
    assert not report_file.exists()
    assert not raw_file.exists()
    assert not trace_directory.exists()
    assert await session.get(Report, report.id) is None


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


def test_oversized_image_payload_is_optimized_without_losing_an_image_input(tmp_path):
    from PIL import Image as PillowImage

    image_path = tmp_path / "large-table.png"
    image = PillowImage.effect_noise((2600, 1800), 100).convert("RGB")
    image.save(image_path, format="PNG")

    data_url, original_bytes, sent_bytes, optimized = _prepared_image_data_url(str(image_path))

    assert data_url.startswith("data:image/")
    assert original_bytes > 0
    assert sent_bytes > 0
    assert optimized
    assert sent_bytes < original_bytes


def test_client_inquiry_replies_are_kept_out_of_active_recommendations():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "COMI", "stock_name_en": "CIB", "stock_name_ar": "البنك التجاري الدولي",
            "rank": 1, "mention_count": 1, "status": "active", "analysis_summary_ar": "توصية شراء",
            "data_points": [{"source": "CFI", "date": "2026-07-15", "buy_price": 140}],
        }],
        "client_inquiry_responses": [{
            "stock_code": "ALUM", "stock_name_en": "Aluminium Arabia", "stock_name_ar": "الألومنيوم العربية",
            "source": "Ostoul Capital", "date": "2026-07-14", "question_summary_ar": "استفسار عن السهم",
            "reply_summary_ar": "اتجاه عرضي بين الدعم والمقاومة", "buy_price": 22.9, "target_1": 23.6,
            "target_2": 24.15, "stop_loss": 22.5, "support": 20.60, "resistance": 26.40,
        }],
    }

    active_rows = _consolidated_source_table(payload)
    inquiry_rows = _client_inquiry_rows(payload)

    assert [row["ticker"] for row in active_rows] == ["COMI"]
    assert [row["ticker"] for row in inquiry_rows] == ["ALUM"]
    assert inquiry_rows[0]["reply_summary_ar"] == "اتجاه عرضي بين الدعم والمقاومة"
    assert inquiry_rows[0]["target_1"] == 23.6



def test_client_inquiry_rows_keep_model_returned_records_without_local_filtering():
    payload = {
        "client_inquiry_responses": [
            {
                "stock_code": "ALUM", "stock_name_en": "Aluminium Arabia", "source": "Ostoul Capital",
                "source_message_id": "101", "source_excerpt": "Reply to customer inquiries about ALUM.",
            },
            {
                "stock_code": "COMI", "stock_name_en": "CIB", "source": "Ostoul Capital",
                "source_message_id": "999", "source_excerpt": "This message was not included in the analysis.",
            },
            {
                "stock_code": "TMGH", "stock_name_en": "TMG", "source": "Ostoul Capital",
                "source_message_id": "101",
            },
        ],
    }

    rows = _client_inquiry_rows(payload)

    assert [row["ticker"] for row in rows] == ["ALUM", "COMI", "TMGH"]
    assert rows[0]["source_message_id"] == "101"
    assert rows[0]["source_excerpt"] == "Reply to customer inquiries about ALUM."


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


def test_next_day_analysis_window_uses_one_day_before_the_request_to_now_in_cairo():
    from datetime import date

    requested_at = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    start, end, target_date = next_day_analysis_window(requested_at)
    assert start == datetime(2026, 7, 12, 12, tzinfo=timezone.utc)
    assert end == requested_at
    assert target_date == date(2026, 7, 14)


def test_selected_date_analysis_window_uses_prior_day_through_analyze_time():
    from datetime import date

    requested_at = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    start, end, target_date = selected_date_analysis_window(date(2026, 7, 10), requested_at)

    assert start == datetime(2026, 7, 7, 21, tzinfo=timezone.utc)
    assert end == requested_at
    assert target_date == date(2026, 7, 9)


def test_next_day_analysis_window_uses_thursday_through_now_for_a_sunday_target():
    from datetime import date

    requested_at = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    start, end, target_date = next_day_analysis_window(requested_at)

    assert start == datetime(2026, 7, 15, 21, tzinfo=timezone.utc)
    assert end == requested_at
    assert target_date == date(2026, 7, 19)


def test_next_day_analysis_window_keeps_thursday_coverage_on_saturday_for_sunday_target():
    from datetime import date

    requested_at = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    start, end, target_date = next_day_analysis_window(requested_at)

    assert start == datetime(2026, 7, 15, 21, tzinfo=timezone.utc)
    assert end == requested_at
    assert target_date == date(2026, 7, 19)


def test_selected_date_analysis_window_resolves_egypt_weekend_to_thursday():
    from datetime import date

    start, _, target_date = selected_date_analysis_window(date(2026, 7, 18), datetime(2026, 7, 20, tzinfo=timezone.utc))

    assert start == datetime(2026, 7, 14, 21, tzinfo=timezone.utc)
    assert target_date == date(2026, 7, 16)


def test_consolidated_validation_warns_when_inquiries_are_returned_as_recommendations():
    messages = [{"source": "Ostoul", "telegram_message_id": 7, "text": "ردًا على استفسارات عملائنا"}]
    payload = {"top_consolidated_recommendations": [{"data_points": [{
        "source": "Ostoul", "source_message_id": "7",
    }]}], "client_inquiry_responses": []}

    warnings = validate_consolidated_output(payload, messages)

    assert any("placed in recommendations" in warning for warning in warnings)
    assert any("absent from client inquiries" in warning for warning in warnings)


def test_client_inquiry_data_points_are_removed_from_recommendations_locally():
    messages = [
        {"source": "Ostoul", "telegram_message_id": 7, "text": "\u0631\u062f\u064b\u0627 \u0639\u0644\u0649 \u0627\u0633\u062a\u0641\u0633\u0627\u0631\u0627\u062a \u0639\u0645\u0644\u0627\u0626\u0646\u0627"},
        {"source": "CFI", "telegram_message_id": 8, "text": "Dated EGX buy recommendation"},
    ]
    payload = {"top_consolidated_recommendations": [{
        "stock_code": "COMI", "mention_count": 2,
        "data_points": [
            {"source": "Ostoul", "source_message_id": "7"},
            {"source": "CFI", "source_message_id": "8"},
        ],
    }]}

    sanitized, warnings = enforce_client_inquiry_separation(payload, messages)

    assert payload["top_consolidated_recommendations"][0]["mention_count"] == 2
    assert sanitized["top_consolidated_recommendations"][0]["mention_count"] == 1
    assert sanitized["top_consolidated_recommendations"][0]["data_points"] == [{"source": "CFI", "source_message_id": "8"}]
    assert warnings == ["1 marked client inquiry recommendation data point(s) were automatically excluded."]


def test_past_recommendation_caption_detection_handles_arabic_and_english_markers():
    assert has_past_recommendation_context("\u0631\u062f\u064b\u0627 \u0639\u0644\u0649 \u0627\u0644\u062a\u0648\u0635\u064a\u0629 \u0627\u0644\u0633\u0627\u0628\u0642\u0629")
    assert has_past_recommendation_context("Previous recommendation: CIB target achieved")
    assert not has_past_recommendation_context("\u062a\u0648\u0635\u064a\u0629 \u0634\u0631\u0627\u0621 \u062c\u062f\u064a\u062f\u0629 \u0644\u062c\u0644\u0633\u0629 \u0627\u0644\u063a\u062f")


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
    assert len(details) == 1
    assert details[0]["ticker"] == "CIB"
    assert details[0]["company"] == "Commercial International Bank"
    assert details[0]["channel"] == "stocks"
    assert details[0]["occurrences"] == 1
    assert details[0]["details"] == [{"price": "92.5", "target": "100", "context": "CIB row"}]
    assert "CIB row" in (details[0].get("notes") or "")
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


async def test_selected_chat_report_prefers_explicit_batch_result_and_preserves_raw_output(session, tmp_path):
    message = await MessageService(session).ingest(MessageCreate(
        channel_handle="signals", telegram_message_id=16, text="Unrelated historic response", published_at=datetime.now(timezone.utc)
    ))
    message.ai_response_raw = '{"recommendations": []}'
    await session.flush()
    raw_response = json.dumps(QWEN_CONSOLIDATED_OUTPUT, ensure_ascii=False)
    report = await ReportService(session, type("Settings", (), {"storage_root": tmp_path})()).generate_selected_chat_report(
        [message.channel_id], datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc) + timedelta(minutes=1),
        1, consolidated_source=QWEN_CONSOLIDATED_OUTPUT, consolidated_raw_response=raw_response,
    )
    assert report.summary["analysis_mode"] == "consolidated_batch"
    assert report.summary["stock_code_summary"][0]["ticker"] == "MFPC"
    assert raw_response in Path(report.summary["original_ai_response_text_path"]).read_text(encoding="utf-8")


async def test_consolidated_report_preserves_every_model_data_point(session, tmp_path):
    message = await MessageService(session).ingest(MessageCreate(
        channel_handle="signals", telegram_message_id=17, text="MFPC updates", published_at=datetime.now(timezone.utc)
    ))
    payload = json.loads(json.dumps(QWEN_CONSOLIDATED_OUTPUT))
    payload["top_consolidated_recommendations"][0]["data_points"].append({
        "date": "2026-07-13", "source": "CFI", "buy_price": 38.0, "target_1": 39.2,
        "target_2": 40.5, "stop_loss": 36.0, "support": 37.0, "resistance": 39.2,
        "expected_return_pct": 3.1, "risk_pct": -1.9,
        "recommendation_type": "sell", "notes_ar": "ملاحظة مصدرية مستقلة",
    })
    await session.flush()
    report = await ReportService(session, type("Settings", (), {"storage_root": tmp_path})()).generate_selected_chat_report(
        [message.channel_id], datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc) + timedelta(minutes=1),
        1, consolidated_source=payload, consolidated_raw_response=json.dumps(payload),
    )
    rows = report.summary["stock_source_table"]
    assert len(rows) == 2
    assert all(row["source"] == "CFI" for row in rows)
    assert all(row["source_entries"] == 1 for row in rows)
    assert [row["buy_price"] for row in rows] == [37.25, 38.0]
    assert rows[1]["recommendation_type"] == "sell"
    assert rows[1]["notes_ar"] == "ملاحظة مصدرية مستقلة"


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


async def test_analysis_trace_saves_consolidated_response(session, tmp_path):
    message = await MessageService(session).ingest(MessageCreate(
        channel_handle="signals", telegram_message_id=18, text="BUY CIB", published_at=datetime.now(timezone.utc)
    ))
    await session.flush()
    trace = await export_analysis_trace(
        session, tmp_path / "storage", [message.channel_id], datetime.now(timezone.utc) - timedelta(days=1),
        datetime.now(timezone.utc) + timedelta(minutes=1), '{"top_consolidated_recommendations": []}',
    )
    assert Path(str(trace["consolidated_response_path"])).read_text(encoding="utf-8") == '{"top_consolidated_recommendations": []}'


def test_selected_input_trace_contains_only_the_model_batch(tmp_path):
    source_image = tmp_path / "selected-chart.jpg"
    source_image.write_bytes(b"selected-image")
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    trace = create_selected_input_trace(
        tmp_path / "storage",
        [{
            "source": "Selected channel", "published_at": start.isoformat(), "telegram_message_id": 42,
            "text": "Selected text only", "transcripts": ["Selected transcript"],
            "image_paths": [str(source_image)],
        }],
        start, end, "Source messages: 2026-07-14", "2026-07-15", {"text", "images", "audio"},
        [{"telegram_message_id": "77", "reason": "past_recommendation_context_in_message_caption"}],
    )
    payload = json.loads(Path(str(trace["json_path"])).read_text(encoding="utf-8"))
    assert payload["messages"] == [{
        "source": "Selected channel", "published_at": start.isoformat(), "telegram_message_id": 42,
        "text": "Selected text only", "audio_transcripts": ["Selected transcript"],
        "image_files": ["images/42_1_selected-chart.jpg"],
    }]
    assert Path(str(trace["images_path"])).joinpath("42_1_selected-chart.jpg").read_bytes() == b"selected-image"
    assert json.loads(Path(str(trace["excluded_path"])).read_text(encoding="utf-8")) == [{
        "telegram_message_id": "77", "reason": "past_recommendation_context_in_message_caption",
    }]
    completed = save_consolidated_response(trace, '{"top_consolidated_recommendations": []}')
    assert Path(str(completed["consolidated_response_path"])).is_file()


def test_provider_request_trace_saves_final_prompt_and_sent_image_bytes(tmp_path):
    data_url = "data:image/jpeg;base64," + base64.b64encode(b"provider-image").decode()
    _write_provider_request_trace(tmp_path, "Exact prompt sent to the model", [(data_url, 30, 14, True)])
    assert (tmp_path / "provider-prompt.txt").read_text(encoding="utf-8") == "Exact prompt sent to the model"
    assert (tmp_path / "sent-images" / "image-1.jpg").read_bytes() == b"provider-image"
    manifest = json.loads((tmp_path / "sent-images.json").read_text(encoding="utf-8"))
    assert manifest == [{
        "reference": 1, "file": "sent-images/image-1.jpg", "mime_type": "image/jpeg",
        "original_bytes": 30, "sent_bytes": 14, "optimized": True,
    }]


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
