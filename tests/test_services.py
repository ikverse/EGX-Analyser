from datetime import date, datetime, timedelta, timezone
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
from app import api, database
from app.models import Base, Image, Recommendation, Report, StockMention
from app.schemas import AnalysisResult, CollectionRequest, ExtractedRecommendation, ExtractedStockMention, MessageCreate, TelegramChatSelect
from app.ai.service import (
    AIAnalysisService,
    AnalysisOutcome,
    _analysis_result_from_payload,
    _build_analysis_prompt,
    _image_visual_signature,
    _prepared_image_data_url,
    _visually_same_image,
    _write_provider_request_trace,
    analysis_output_schema,
)
from app.reports import (
    _attach_source_images,
    _client_inquiry_rows,
    _consolidated_source_table,
    bind_source_image_references,
)
from app.services import AnalyticsService, MessageService, SearchService
from app.config_store import load_secrets_into_environment, update_config
from app.content_updates import ContentUpdateService, generate_seed, public_key_from_seed, sign_bytes, verify_bytes
from app.telegram_auth import TelegramAuthenticator
from app.runtime import next_day_analysis_window, selected_date_analysis_window
from app.collector.telegram import is_promotional_message
from app.reports import ReportService
from app.analysis_trace import create_selected_input_trace, export_analysis_trace, save_analysis_performance, save_consolidated_response, save_model_validation
from app.analysis_filter import has_past_recommendation_context, is_non_actionable_stock_update
from app.analysis_validation import normalize_consolidated_output, validate_consolidated_output
from app.channel_names import clean_channel_name
from app.prompt_customization import (
    load_prompt_customization,
    prompt_customization_block,
    prompt_customization_path,
    reset_prompt_customization,
    restore_prompt_customization,
    save_prompt_customization,
)
from app.repositories import StockRepository
from app.stock_catalog import EGXStockCatalog, normalize_stock_name
from app.entry_points import normalize_entry_point
from zoneinfo import ZoneInfo


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


def test_results_table_keeps_fixed_columns_when_entry_is_a_range():
    repository_root = Path(__file__).resolve().parents[1]
    app_source = (repository_root / "desktop" / "src" / "App.tsx").read_text(encoding="utf-8")
    styles = (repository_root / "desktop" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "<colgroup>" in app_source
    assert app_source.count('<col className="result-col-') == 17
    assert '<th className="numeric">Entry</th>' in app_source
    assert '<td className="numeric entry-value">' in app_source
    assert ".consolidated-table .result-col-entry { width: 140px; }" in styles
    assert "table-layout: fixed;" in styles
    assert "width: 2195px;" in styles


def test_entry_point_ranges_preserve_exact_source_bounds():
    assert normalize_entry_point(24.5) == (24.5, None, None)
    assert normalize_entry_point("24.50-25.20") == (None, 24.5, 25.2)
    assert normalize_entry_point("\u0645\u0646 \u0662\u0664\u066b\u0665\u0660 \u0625\u0644\u0649 \u0662\u0665\u066b\u0662\u0660") == (None, 24.5, 25.2)


def test_visual_duplicate_detection_handles_recompressed_reposts(tmp_path):
    from PIL import Image as PillowImage

    original = tmp_path / "original.jpg"
    repost = tmp_path / "repost.jpg"
    different = tmp_path / "different.jpg"
    image = PillowImage.new("RGB", (320, 180), (20, 55, 95))
    image.save(original, quality=95)
    image.save(repost, quality=75)
    PillowImage.new("RGB", (320, 180), (95, 35, 20)).save(different, quality=75)

    assert _visually_same_image(_image_visual_signature(str(original)), _image_visual_signature(str(repost)))
    assert not _visually_same_image(_image_visual_signature(str(original)), _image_visual_signature(str(different)))


@pytest.mark.asyncio
async def test_same_template_images_are_sent_separately_for_stock_aware_review(tmp_path):
    from PIL import Image as PillowImage, ImageDraw

    skpc = tmp_path / "skpc.jpg"
    alcn = tmp_path / "alcn.jpg"
    for path, ticker, values in (
        (skpc, "SKPC", "16.000 16.500 16.900 15.700"),
        (alcn, "ALCN", "29.850 30.500 31.150 29.300"),
    ):
        image = PillowImage.new("RGB", (1920, 1080), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1920, 180), fill=(20, 52, 108))
        draw.rectangle((110, 280, 1760, 420), fill=(235, 240, 249))
        draw.text((260, 230), ticker, fill=(0, 30, 190))
        draw.text((620, 330), values, fill=(10, 10, 10))
        image.save(path, quality=92)

    assert _visually_same_image(_image_visual_signature(str(skpc)), _image_visual_signature(str(alcn)))
    captured: dict[str, object] = {}
    service = object.__new__(AIAnalysisService)
    service.settings = SimpleNamespace()
    service.prompt = ""

    async def fake_analyze_prompt(source_data, image_paths, input_metrics, *_args, **_kwargs):
        captured.update(
            source_data=source_data,
            image_paths=image_paths,
            input_metrics=dict(input_metrics),
            interleaved_parts=_kwargs.get("interleaved_parts"),
        )
        payload = {
            "analysis_period": "test", "top_consolidated_recommendations": [], "achieved_targets": [],
            "client_inquiry_responses": [],
            "text_based_categories": {"most_important_stocks": [], "trading_stocks": [], "watchlist_stocks": []},
            "daily_breakdown": {},
        }
        return AnalysisOutcome(
            result=_analysis_result_from_payload(payload), raw_response=json.dumps(payload),
            input_metrics=dict(input_metrics),
        )

    service._analyze_prompt = fake_analyze_prompt
    outcome = await service.analyze_consolidated([
        {"source": "CFI", "telegram_message_id": 3904, "published_at": "2026-07-22T07:23:35+03:00",
         "text": "", "image_paths": [str(skpc)], "transcripts": []},
        {"source": "CFI", "telegram_message_id": 3905, "published_at": "2026-07-22T07:25:32+03:00",
         "text": "", "image_paths": [str(alcn)], "transcripts": []},
        {"source": "CFI", "telegram_message_id": 3906, "published_at": "2026-07-22T07:26:00+03:00",
         "text": "", "image_paths": [str(skpc)], "transcripts": []},
    ], "test", "2026-07-23")

    assert captured["image_paths"] == [str(skpc), str(alcn)]
    metrics = captured["input_metrics"]
    assert isinstance(metrics, dict)
    assert metrics["duplicate_image_count"] == 1
    assert metrics["near_duplicate_image_count"] == 1
    interleaved_parts = captured["interleaved_parts"]
    assert isinstance(interleaved_parts, list)
    assert "TELEGRAM_ID: 3904" in interleaved_parts[0][0]
    assert interleaved_parts[1][1] == str(skpc)
    assert "IMAGE_REF 1" in interleaved_parts[1][0]
    assert "different ticker, date, recommendation, or trade values" in str(interleaved_parts)
    assert outcome.source_image_references[1]["source_message_id"] == "3904"
    assert outcome.source_image_references[1]["path"] == str(skpc)
    assert outcome.source_image_references[2]["source_message_id"] == "3905"
    source_data = str(captured["source_data"])
    assert "There is no prior-date or next-session exception" in source_data
    assert "differs from the target effective trading date, even by one day" in source_data
    assert "data_points[].effective_date_basis to watching" in source_data
    assert "voice-note transcripts" in source_data
    assert "visibly placed directly beneath it in the same recommendation" in source_data
    assert "NEWS EXCLUSION independently to every image/photo, ordinary text message" in source_data
    assert "عاجل, خبر عاجل, أخبار, خبر" in source_data
    assert "managed Include phrases" in source_data
    assert "SELL-ZONE TARGETS AND RETURNS" in source_data
    assert "entry 26.80–27.00" in source_data
    assert "return_tp1_pct=3.70" in source_data
    assert "return_tp2_pct=6.48" in source_data
    assert "MANDATORY DATE ELIGIBILITY SELF-AUDIT" in source_data


def test_source_table_keeps_entry_range_without_averaging():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "COMI", "stock_name_en": "CIB", "stock_name_ar": "CIB Arabic",
            "rank": 1, "mention_count": 1, "status": "active", "data_points": [{
                "date": "2026-07-16", "source": "CFI", "buy_price": None,
                "buy_price_low": 24.5, "buy_price_high": 25.2,
                "visible_source_date": "2026-07-16", "date_evidence": "16-Jul-2026",
                "timing_evidence": None,
            }],
        }],
    }

    row = _consolidated_source_table(payload)[0]
    assert row["buy_price"] is None
    assert row["buy_price_low"] == 24.5
    assert row["buy_price_high"] == 25.2
    assert row["visible_source_date"] == "2026-07-16"
    assert row["date_evidence"] == "16-Jul-2026"
    assert row["timing_evidence"] is None


def test_sell_zone_targets_keep_explicit_per_target_returns():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "HRHO",
            "stock_name_en": "EFG Holding",
            "mention_count": 1,
            "rank": 1,
            "status": "active",
            "data_points": [{
                "source": "Ostoul",
                "source_message_id": "19246",
                "recommendation_type": "buy",
                "buy_price_low": 26.80,
                "buy_price_high": 27.00,
                "target_1": 28.00,
                "return_tp1_pct": 3.70,
                "target_2": 28.75,
                "return_tp2_pct": 6.48,
                "stop_loss": 26.10,
            }],
        }],
    }

    row = _consolidated_source_table(payload)[0]

    assert row["recommendation_type"] == "buy"
    assert row["buy_price"] is None
    assert row["buy_price_low"] == 26.80
    assert row["buy_price_high"] == 27.00
    assert row["target_1"] == 28.00
    assert row["return_tp1_pct"] == 3.70
    assert row["target_2"] == 28.75
    assert row["return_tp2_pct"] == 6.48


def test_missing_target_returns_are_calculated_from_upper_entry_bound():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "HRHO",
            "mention_count": 1,
            "data_points": [{
                "source": "Ostoul",
                "source_message_id": "19246",
                "recommendation_type": "buy",
                "buy_price_low": 26.80,
                "buy_price_high": 27.00,
                "target_1": 28.00,
                "target_2": 28.75,
            }],
        }],
    }

    row = _consolidated_source_table(payload)[0]

    assert row["return_tp1_pct"] == 3.70
    assert row["return_tp2_pct"] == 6.48
    assert row["expected_return_pct"] == 3.70


def test_sell_recommendation_return_calculation_uses_inverse_price_direction():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "COMI",
            "mention_count": 1,
            "data_points": [{
                "source": "Example",
                "source_message_id": "1",
                "recommendation_type": "sell",
                "buy_price": 100,
                "target_1": 95,
                "target_2": 90,
            }],
        }],
    }

    row = _consolidated_source_table(payload)[0]

    assert row["return_tp1_pct"] == 5.0
    assert row["return_tp2_pct"] == 10.0


def test_legacy_expected_return_is_preserved_as_tp1_return():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "COMI",
            "mention_count": 1,
            "data_points": [{
                "source": "Legacy",
                "source_message_id": "1",
                "target_1": 105,
                "expected_return_pct": "4.25%",
            }],
        }],
    }

    row = _consolidated_source_table(payload)[0]

    assert row["return_tp1_pct"] == 4.25
    assert row["return_tp2_pct"] is None


def test_qwen_models_return_every_accessible_model():
    catalog = [
        {"id": "qwen-plus", "architecture": {"input_modalities": ["text"]}},
        {"id": "qwen3-vl-flash", "architecture": {"input_modalities": ["text", "image"]}},
        {"id": "qwen-vl-max", "architecture": {"input_modalities": ["text", "image"]}},
        {"id": "qwen3-vl-235b-a22b-instruct"},
        {"id": "qwen3-vl-plus-2026-01-01"},
    ]

    assert api._qwen_vision_models(catalog) == [
        "qwen-plus",
        "qwen-vl-max",
        "qwen3-vl-235b-a22b-instruct",
        "qwen3-vl-flash",
        "qwen3-vl-plus-2026-01-01",
    ]


def test_ollama_models_return_every_installed_model():
    catalog = [
        {"name": "qwen3:4b", "details": {"families": ["qwen3"]}},
        {"name": "llava:7b", "details": {"families": ["llama", "clip"]}},
        {"name": "qwen3-vl:8b", "details": {"families": ["qwen3vl", "vision"]}},
        {"name": "qwen3-vl:4b", "details": {"families": ["qwen3vl", "vision"]}},
    ]

    assert api._ollama_vision_models(catalog) == ["llava:7b", "qwen3-vl:4b", "qwen3-vl:8b", "qwen3:4b"]


def test_source_images_are_attached_by_channel_and_telegram_message_id(tmp_path):
    source_image = tmp_path / "COMI.png"
    source_image.write_bytes(b"image")
    channel = SimpleNamespace(handle="ostoulcapital", title="Ostoul Capital")
    message = SimpleNamespace(id=8, telegram_message_id=1946)
    image = SimpleNamespace(path=str(source_image))
    rows = [{"source": "Ostoul Capital", "source_message_id": "1946"}]

    _attach_source_images(rows, [(image, message)], {8: channel})

    assert rows[0]["source_image_paths"] == [str(source_image)]


def test_bound_image_reference_overrides_shifted_model_source_and_uses_exact_image(tmp_path):
    correct_image = tmp_path / "phdc.png"
    incorrect_message_image = tmp_path / "transactions.png"
    correct_image.write_bytes(b"recommendation")
    incorrect_message_image.write_bytes(b"not-a-recommendation")
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "PHDC",
            "data_points": [{
                "source": "Wrong source",
                "source_message_id": "60112",
                "source_image_ref": 30,
            }],
        }],
    }

    bind_source_image_references(payload, {
        30: {
            "path": str(correct_image),
            "source": "Ostoul",
            "source_message_id": "60116",
            "image_index": "1",
        },
    })
    point = payload["top_consolidated_recommendations"][0]["data_points"][0]
    assert point["source"] == "Ostoul"
    assert point["source_message_id"] == "60116"
    assert point["source_image_path"] == str(correct_image)

    rows = _consolidated_source_table(payload)
    channel = SimpleNamespace(handle="ostoul", title="Ostoul")
    wrong_message = SimpleNamespace(id=12, telegram_message_id=60112)
    wrong_image = SimpleNamespace(path=str(incorrect_message_image))
    _attach_source_images(rows, [(wrong_image, wrong_message)], {12: channel})

    assert rows[0]["source_image_paths"] == [str(correct_image)]


def test_new_result_without_valid_image_reference_does_not_fallback_to_claimed_message(tmp_path):
    unrelated_image = tmp_path / "news.png"
    unrelated_image.write_bytes(b"news")
    channel = SimpleNamespace(handle="ostoul", title="Ostoul")
    message = SimpleNamespace(id=27, telegram_message_id=60127)
    image = SimpleNamespace(path=str(unrelated_image))
    rows = [{
        "source": "Ostoul",
        "source_message_id": "60127",
        "source_image_ref": None,
        "source_image_path": None,
    }]

    _attach_source_images(rows, [(image, message)], {27: channel})

    assert rows[0]["source_image_paths"] == []


@pytest.mark.asyncio
async def test_qwen_request_interleaves_each_image_with_its_source_metadata(tmp_path):
    source_image = tmp_path / "recommendation.jpg"
    source_image.write_bytes(b"provider-image")
    captured: dict[str, object] = {}
    response_payload = {
        "analysis_period": "test",
        "top_consolidated_recommendations": [],
        "achieved_targets": [],
        "client_inquiry_responses": [],
        "text_based_categories": {
            "most_important_stocks": [],
            "trading_stocks": [],
            "watchlist_stocks": [],
        },
        "daily_breakdown": {},
    }

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content=json.dumps(response_payload))),
            ])

    service = object.__new__(AIAnalysisService)
    service.settings = SimpleNamespace(ai_provider="qwen", ai_model="qwen3-vl-plus")
    service.prompt = "Base prompt"
    service.client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    await service._analyze_prompt(
        "Run rules",
        [str(source_image)],
        interleaved_parts=[
            ("MESSAGE | SOURCE: Ostoul | TELEGRAM_ID: 60116", None),
            ("IMAGE_REF 1 | SOURCE: Ostoul | TELEGRAM_ID: 60116", str(source_image)),
            ("MESSAGE | SOURCE: News | TELEGRAM_ID: 60127", None),
        ],
    )

    content = captured["messages"][-1]["content"]
    assert [part["type"] for part in content] == ["text", "text", "text", "image_url", "text"]
    assert "TELEGRAM_ID: 60116" in content[1]["text"]
    assert "IMAGE_REF 1" in content[2]["text"]
    assert content[3]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "TELEGRAM_ID: 60127" in content[4]["text"]


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


async def test_sqlite_startup_adds_entry_range_columns_to_legacy_database(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with legacy_engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TABLE recommendations (id INTEGER PRIMARY KEY, entry FLOAT, target_2 FLOAT)"
        )
        await connection.exec_driver_sql(
            "INSERT INTO recommendations (id, entry, target_2) VALUES (1, 24.5, 28.0)"
        )
    await legacy_engine.dispose()

    settings = SimpleNamespace(database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)

    await database.init_database()

    engine, _ = database._engine_and_factory()
    async with engine.connect() as connection:
        columns = {
            row[1]: row[2]
            for row in (await connection.exec_driver_sql("PRAGMA table_info(recommendations)")).all()
        }
        saved = (
            await connection.exec_driver_sql(
                "SELECT entry, target_2, entry_low, entry_high FROM recommendations WHERE id = 1"
            )
        ).one()
    await engine.dispose()
    database._engine = None
    database._session_factory = None

    assert columns["entry_low"] == "FLOAT"
    assert columns["entry_high"] == "FLOAT"
    assert saved == (24.5, 28.0, None, None)


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
    now = datetime(2026, 7, 16, 13, 1, 51, tzinfo=timezone.utc)
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
    assert results[0]["generated_at"] == "2026-07-16T16:01:51+03:00"
    assert results[0]["target_date"] == "2026-07-15"
    assert results[0]["stock_source_table"][0]["ticker"] == "COMI"
    assert results[0]["stock_source_table"][0]["target_date"] == "2026-07-15"


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


def test_analysis_performance_is_saved_in_trace(tmp_path):
    trace_directory = tmp_path / "trace"
    trace_directory.mkdir()

    result = save_analysis_performance({"directory": str(trace_directory)}, {"model_request_ms": 1200})

    assert Path(str(result["performance_path"])).exists()
    assert json.loads(Path(str(result["performance_path"])).read_text(encoding="utf-8")) == {
        "unit": "milliseconds", "timings": {"model_request_ms": 1200},
    }


def test_model_retry_audit_is_saved_in_trace(tmp_path):
    trace_directory = tmp_path / "trace"
    trace_directory.mkdir()

    result = save_model_validation(
        {"directory": str(trace_directory)}, [], True,
        {"attempted": True, "status": "passed", "final_validation_warnings": []},
    )

    assert json.loads(Path(str(result["retry_audit_path"])).read_text(encoding="utf-8"))["status"] == "passed"


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


def test_consolidated_parser_uses_stock_notes_summary():
    payload = json.loads(json.dumps(QWEN_CONSOLIDATED_OUTPUT))
    payload["top_consolidated_recommendations"][0]["notes_summary"] = "Concise stock-level finding."

    result = _analysis_result_from_payload(payload)

    assert result.stock_mentions[0].context == "Concise stock-level finding."
    assert result.recommendations[0].reason == "Concise stock-level finding."


def test_third_and_later_targets_are_excluded_from_parsing_and_notes():
    payload = json.loads(json.dumps(QWEN_CONSOLIDATED_OUTPUT))
    stock = payload["top_consolidated_recommendations"][0]
    stock["notes_summary"] = "TP1 38.7; TP2 40; TP3 42; مستهدف ثالث 42; target 4: 44; risk warning."
    stock["data_points"][0]["target_3"] = 42
    stock["data_points"][0]["tp4"] = 44

    result = _analysis_result_from_payload(payload)
    rows = _consolidated_source_table(payload)

    assert result.recommendations[0].target == 38.7
    assert result.recommendations[0].target_2 == 40.0
    assert "TP3" not in (result.recommendations[0].reason or "")
    assert "مستهدف ثالث" not in (result.recommendations[0].reason or "")
    assert "target 4" not in (result.recommendations[0].reason or "")
    assert "المستهدفان الأول والثاني" in rows[0]["notes_summary"]
    assert "38.7" in rows[0]["notes_summary"]
    assert "40" in rows[0]["notes_summary"]
    assert "المخاطر المعلنة" in rows[0]["notes_summary"]
    assert "تحذير من المخاطر" in rows[0]["notes_summary"]
    assert "target_3" not in rows[0]
    assert "tp4" not in rows[0]


def test_stock_notes_merge_bilingual_equivalents_and_keep_distinct_levels():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "COMI", "stock_name_en": "CIB", "mention_count": 3, "rank": 1, "status": "active",
            "data_points": [
                {"source": "One", "source_message_id": "1", "effective_date_basis": "watching",
                 "buy_price_low": 24.5, "buy_price_high": 25.2, "target_1": 27, "notes_ar": "Stock to watch"},
                {"source": "Two", "source_message_id": "2", "target_2": 28, "stop_loss": 23.8,
                 "notes_ar": "سهم للمراقبة"},
                {"source": "Three", "source_message_id": "3", "notes_ar": "تحذير من المخاطر"},
            ],
        }],
        "text_based_categories": {"watchlist_stocks": [{"stock_code": "COMI"}]},
    }

    rows = _consolidated_source_table(payload)
    summaries = {row["notes_summary"] for row in rows}

    assert len(rows) == 3
    assert len(summaries) == 1
    summary = summaries.pop()
    assert "سهماً للمراقبة" in summary
    assert "نطاق الدخول: 24.5–25.2" in summary
    assert "المستهدفان الأول والثاني: 27، 28" in summary
    assert "وقف الخسارة: 23.8" in summary
    assert "ورد تحذير من المخاطر" in summary
    assert "Stock to watch" not in summary
    assert "سهم للمراقبة" not in summary


def test_watching_timing_is_preserved_and_generates_arabic_notes():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "FWRY",
            "stock_name_en": "Fawry",
            "mention_count": 1,
            "rank": 1,
            "status": "active",
            "data_points": [{
                "date": "2026-07-22",
                "source": "Ostoul",
                "source_message_id": "19246",
                "effective_date_basis": "watching",
                "visible_source_date": "2026-07-21",
                "date_evidence": "21-Jul-2026",
                "timing_evidence": "تحت المراقبة",
                "buy_price": 19.70,
                "target_1": 20.50,
                "target_2": 21.60,
                "stop_loss": 19.00,
            }],
        }],
        "text_based_categories": {},
    }

    row = _consolidated_source_table(payload)[0]

    assert row["effective_date_bases"] == ["watching"]
    assert row["timing_evidence"] == "تحت المراقبة"
    assert "سهماً للمراقبة" in row["notes_summary"]
    assert row["target_1"] == 20.50
    assert row["target_2"] == 21.60


@pytest.mark.parametrize(
    "watch_phrase",
    ["تحت المراقبة", "سهم للمراقبة", "Watching", "Under watch", "Stock to watch"],
)
def test_watching_phrase_equivalents_generate_one_arabic_meaning(watch_phrase):
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "FWRY",
            "mention_count": 1,
            "data_points": [{
                "source": "Ostoul",
                "source_message_id": "19246",
                "notes_ar": watch_phrase,
            }],
        }],
    }

    summary = _consolidated_source_table(payload)[0]["notes_summary"]

    assert summary.count("سهماً للمراقبة") == 1
    assert "Stock to watch" not in summary
    assert "Under watch" not in summary
    assert "Watching" not in summary


def test_watching_basis_alias_is_backward_compatible():
    payload = {
        "top_consolidated_recommendations": [{
            "stock_code": "FWRY",
            "mention_count": 1,
            "data_points": [{
                "source": "Ostoul",
                "source_message_id": "19246",
                "effective_date_basis": "under-watch",
            }],
        }],
    }

    summary = _consolidated_source_table(payload)[0]["notes_summary"]

    assert "سهماً للمراقبة" in summary


def test_saved_result_rows_receive_backward_compatible_stock_notes():
    legacy_rows = [
        {"ticker": "COMI", "mention_count": 2, "effective_date_bases": ["watching"],
         "timing_evidence": "Watching", "notes_ar": "Stock to watch", "source": "One", "source_dates": []},
        {"ticker": "COMI", "mention_count": 2, "effective_date_bases": ["under-watch"],
         "notes_ar": "سهم مراقبة", "source": "Two", "source_dates": []},
    ]

    rows = api._analysis_table_with_source_images(legacy_rows, [], {})

    assert rows[0]["notes_summary"] == rows[1]["notes_summary"]
    assert "سهماً للمراقبة" in rows[0]["notes_summary"]
    assert "stock to watch" not in rows[0]["notes_summary"]


def test_arabic_model_notes_summary_is_preserved_for_results():
    payload = json.loads(json.dumps(QWEN_CONSOLIDATED_OUTPUT))
    stock = payload["top_consolidated_recommendations"][0]
    stock["notes_summary"] = "توصية مجمعة للسهم مع الالتزام بالمستهدفين الأول والثاني فقط."

    rows = _consolidated_source_table(payload)

    assert rows[0]["notes_summary"] == stock["notes_summary"]


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


def test_legacy_supplementary_guidance_is_removed_from_local_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("EGX_CONFIG_FILE", str(tmp_path / ".env"))
    update_config({"ANALYSIS_INSTRUCTIONS": "legacy supplementary guidance"})

    update_config({"ANALYSIS_INSTRUCTIONS": ""})

    assert "ANALYSIS_INSTRUCTIONS" not in os.environ
    assert "ANALYSIS_INSTRUCTIONS" not in json.loads((tmp_path / "secrets.json").read_text(encoding="utf-8"))


def test_prompt_customization_persists_normalized_phrases_and_history(monkeypatch, tmp_path):
    monkeypatch.setenv("EGX_CONFIG_FILE", str(tmp_path / ".env"))

    saved = save_prompt_customization(
        "سهم تحت المراقبة، توصية شراء قصيرة الأجل, سهم تحت المراقبة",
        "الأسهم الأكثر سيولة، سهم تحت المراقبة",
    )

    assert saved["include_phrases"] == ["توصية شراء قصيرة الأجل"]
    assert saved["exclude_phrases"] == ["الأسهم الأكثر سيولة", "سهم تحت المراقبة"]
    assert saved["history"][0]["include_added"] == ["توصية شراء قصيرة الأجل"]
    assert saved["history"][0]["exclude_added"] == ["الأسهم الأكثر سيولة", "سهم تحت المراقبة"]
    assert load_prompt_customization()["include_phrases"] == ["توصية شراء قصيرة الأجل"]


def test_prompt_customization_extends_base_logic_and_reset_keeps_history(monkeypatch, tmp_path):
    monkeypatch.setenv("EGX_CONFIG_FILE", str(tmp_path / ".env"))
    saved = save_prompt_customization("الشراء باختراق", "توصية سابقة")
    block = prompt_customization_block(saved)

    assert "extends the existing extraction logic without replacing" in block
    assert "الشراء باختراق" in block
    assert "توصية سابقة" in block
    assert "Exclude phrases take priority" in block

    reset = reset_prompt_customization()

    assert reset["include_phrases"] == []
    assert reset["exclude_phrases"] == []
    assert [entry["action"] for entry in reset["history"]] == ["updated", "reset"]


def test_analysis_prompt_keeps_base_prompt_and_appends_phrase_guidance(monkeypatch, tmp_path):
    monkeypatch.setenv("EGX_CONFIG_FILE", str(tmp_path / ".env"))
    save_prompt_customization("سهم تحت المراقبة", "الأسهم الأكثر سيولة")

    prompt = _build_analysis_prompt("UNCHANGED BASE PROMPT", "MESSAGE SOURCE DATA")

    assert prompt.startswith("UNCHANGED BASE PROMPT\n\nMANAGED RECOMMENDATION PHRASE GUIDANCE")
    assert "Include phrases: سهم تحت المراقبة" in prompt
    assert "Exclude phrases: الأسهم الأكثر سيولة" in prompt
    assert "Return only one JSON object" in prompt
    assert "Every returned image, text, or audio data point must contain visible_source_date" in prompt
    assert "effective_date_basis is explicit_date or watching only" in prompt
    assert "For explicit_date, timing_evidence must be null" in prompt
    assert "visible_source_date, date_evidence, timing_evidence" in prompt
    assert "using null rather than omitting an unavailable field" in prompt
    assert "A recommendation with a missing, ambiguous, past, future, or otherwise different source date is ineligible" in prompt
    assert "For watching, timing_evidence must be the exact same-stock phrase" in prompt
    assert "NEWS EXCLUSION HAS HIGHEST PRIORITY" in prompt
    assert "every image/photo, ordinary text message, and voice-note transcript" in prompt
    assert "عاجل" in prompt
    assert "breaking news" in prompt
    assert "Managed include phrases never override this exclusion" in prompt
    assert "منطقة البيع" in prompt
    assert "return_tp1_pct" in prompt
    assert "return_tp2_pct" in prompt
    assert "application calculates missing returns separately" in prompt
    assert "text or voice-note transcripts" in prompt
    assert "copy the supplied MESSAGE DATE timestamp into date_evidence" in prompt
    assert prompt.endswith("MESSAGE SOURCE DATA")


def test_prompt_customization_restores_a_historical_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("EGX_CONFIG_FILE", str(tmp_path / ".env"))
    save_prompt_customization("سهم تحت المراقبة", "توصية سابقة")
    save_prompt_customization("توصية شراء قصيرة الأجل", "الأسهم الأكثر سيولة")

    restored = restore_prompt_customization(0)

    assert restored["include_phrases"] == ["سهم تحت المراقبة"]
    assert restored["exclude_phrases"] == ["توصية سابقة"]
    assert restored["history"][-1]["action"] == "restored"
    assert restored["history"][-1]["restored_from_index"] == 0


def test_prompt_customization_reset_recovers_a_damaged_file(monkeypatch, tmp_path):
    monkeypatch.setenv("EGX_CONFIG_FILE", str(tmp_path / ".env"))
    prompt_customization_path().write_text("{damaged", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Reset to default prompt"):
        prompt_customization_block()

    recovered = reset_prompt_customization()

    assert recovered["include_phrases"] == []
    assert recovered["history"][-1]["action"] == "reset"
    assert recovered["history"][-1]["recovered_corrupt_file"]
    assert list(tmp_path.glob("prompt-customization.corrupt-*.json"))


@pytest.mark.asyncio
async def test_settings_returns_only_recent_prompt_history_with_total(monkeypatch, tmp_path):
    monkeypatch.setenv("EGX_CONFIG_FILE", str(tmp_path / ".env"))
    for index in range(55):
        save_prompt_customization(f"include phrase {index}", "")
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(
        openai_api_key=None,
        ai_api_key="configured",
        ai_provider="qwen",
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_session=str(tmp_path / "telegram"),
        openai_model="qwen3-vl-plus",
        ollama_model="qwen3-vl:4b",
        ollama_base_url="http://127.0.0.1:11434",
    ))

    status = await api.settings_status()

    assert status["prompt_customization_history_total"] == 55
    assert len(status["prompt_customization_history"]) == 50
    assert status["prompt_customization_history"][0]["history_index"] == 5


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


def test_next_day_analysis_window_uses_current_session_before_egx_opens():
    cairo = ZoneInfo("Africa/Cairo")
    requested_at = datetime(2026, 7, 16, 0, 30, tzinfo=cairo).astimezone(timezone.utc)

    start, end, target_date = next_day_analysis_window(requested_at)

    assert target_date == date(2026, 7, 16)
    assert start == requested_at - timedelta(days=1)
    assert end == requested_at


def test_next_day_analysis_window_uses_current_session_immediately_before_egx_opens():
    cairo = ZoneInfo("Africa/Cairo")
    requested_at = datetime(2026, 7, 16, 9, 59, tzinfo=cairo).astimezone(timezone.utc)

    _, _, target_date = next_day_analysis_window(requested_at)

    assert target_date == date(2026, 7, 16)


def test_next_day_analysis_window_uses_current_session_during_egx_hours():
    cairo = ZoneInfo("Africa/Cairo")
    requested_at = datetime(2026, 7, 16, 10, 0, tzinfo=cairo).astimezone(timezone.utc)

    _, _, target_date = next_day_analysis_window(requested_at)

    assert target_date == date(2026, 7, 16)


def test_next_day_analysis_window_uses_current_session_at_egx_close():
    cairo = ZoneInfo("Africa/Cairo")
    requested_at = datetime(2026, 7, 16, 14, 30, tzinfo=cairo).astimezone(timezone.utc)

    _, _, target_date = next_day_analysis_window(requested_at)

    assert target_date == date(2026, 7, 16)


def test_selected_date_analysis_window_uses_prior_day_through_analyze_time():
    requested_at = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    start, end, target_date = selected_date_analysis_window(date(2026, 7, 10), requested_at)

    assert start == datetime(2026, 7, 7, 21, tzinfo=timezone.utc)
    assert end == requested_at
    assert target_date == date(2026, 7, 9)


def test_next_day_analysis_window_uses_sunday_after_thursday_market_close():
    cairo = ZoneInfo("Africa/Cairo")
    requested_at = datetime(2026, 7, 16, 14, 31, tzinfo=cairo).astimezone(timezone.utc)
    start, end, target_date = next_day_analysis_window(requested_at)

    assert start == datetime(2026, 7, 15, 21, tzinfo=timezone.utc)
    assert end == requested_at
    assert target_date == date(2026, 7, 19)


def test_next_day_analysis_window_uses_sunday_on_friday_and_saturday():
    cairo = ZoneInfo("Africa/Cairo")
    friday = datetime(2026, 7, 17, 12, tzinfo=cairo).astimezone(timezone.utc)
    saturday = datetime(2026, 7, 18, 12, tzinfo=cairo).astimezone(timezone.utc)

    friday_start, friday_end, friday_target = next_day_analysis_window(friday)
    saturday_start, saturday_end, saturday_target = next_day_analysis_window(saturday)

    assert friday_start == datetime(2026, 7, 15, 21, tzinfo=timezone.utc)
    assert friday_end == friday
    assert friday_target == date(2026, 7, 19)
    assert saturday_start == datetime(2026, 7, 15, 21, tzinfo=timezone.utc)
    assert saturday_end == saturday
    assert saturday_target == date(2026, 7, 19)


def test_next_day_analysis_window_uses_next_egx_day_after_regular_close():
    cairo = ZoneInfo("Africa/Cairo")
    requested_at = datetime(2026, 7, 13, 14, 31, tzinfo=cairo).astimezone(timezone.utc)

    _, _, target_date = next_day_analysis_window(requested_at)

    assert target_date == date(2026, 7, 14)


def test_next_day_analysis_window_handles_cairo_midnight_boundary():
    cairo = ZoneInfo("Africa/Cairo")
    requested_at = datetime(2026, 7, 12, 0, 0, tzinfo=cairo).astimezone(timezone.utc)

    start, end, target_date = next_day_analysis_window(requested_at)

    assert target_date == date(2026, 7, 12)
    assert start == datetime(2026, 7, 10, 21, tzinfo=timezone.utc)
    assert end == requested_at


def test_next_day_analysis_window_keeps_thursday_coverage_on_saturday_for_sunday_target():
    requested_at = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    start, end, target_date = next_day_analysis_window(requested_at)

    assert start == datetime(2026, 7, 15, 21, tzinfo=timezone.utc)
    assert end == requested_at
    assert target_date == date(2026, 7, 19)


def test_selected_date_analysis_window_resolves_egypt_weekend_to_thursday():
    start, _, target_date = selected_date_analysis_window(date(2026, 7, 18), datetime(2026, 7, 20, tzinfo=timezone.utc))

    assert start == datetime(2026, 7, 14, 21, tzinfo=timezone.utc)
    assert target_date == date(2026, 7, 16)


def test_minimal_validation_trusts_model_classification_for_known_telegram_ids():
    messages = [{"source": "Ostoul", "telegram_message_id": 7, "text": "ردًا على استفسارات عملائنا"}]
    payload = {"top_consolidated_recommendations": [{"data_points": [{
        "source": "Ostoul", "source_message_id": "7",
    }]}], "client_inquiry_responses": []}

    warnings = validate_consolidated_output(payload, messages)

    assert warnings == []


def test_minimal_validation_keeps_known_rows_and_restores_local_sources():
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

    warnings = validate_consolidated_output(payload, messages)

    assert payload["top_consolidated_recommendations"][0]["mention_count"] == 2
    assert len(payload["top_consolidated_recommendations"][0]["data_points"]) == 2
    assert warnings == []
    assert payload["top_consolidated_recommendations"][0]["data_points"][0]["source"] == "Ostoul"


def test_minimal_validation_does_not_reject_duplicate_trade_values():
    messages = [
        {"source": "Ostoul", "telegram_message_id": 10, "text": ""},
        {"source": "Ostoul", "telegram_message_id": 11, "text": ""},
        {"source": "Ostoul", "telegram_message_id": 12, "text": ""},
    ]
    values = {
        "recommendation_type": "buy", "buy_price_low": 15.10, "buy_price_high": 15.15,
        "target_1": 16.40, "target_2": 18.55, "stop_loss": 14.60,
    }
    payload = {"top_consolidated_recommendations": [
        {"stock_code": "PHDC", "stock_name_ar": "بالم هيلز", "data_points": [
            {"source": "Ostoul", "source_message_id": "10",
             "recommendation_evidence": "PHDC - سهم المراقبة - النصيحة بالشراء", **values},
            {"source": "Ostoul", "source_message_id": "11",
             "recommendation_evidence": "PHDC - الأسهم الأكثر سيولة", **values},
        ]},
        {"stock_code": "MASR", "stock_name_ar": "مدينة مصر", "data_points": [
            {"source": "Ostoul", "source_message_id": "12",
             "recommendation_evidence": "MASR - توصية شراء قصيرة الأجل", **values},
        ]},
    ]}

    warnings = validate_consolidated_output(payload, messages)

    assert warnings == []


def test_consolidated_validation_does_not_judge_recommendation_meaning():
    messages = [{"source": "Ostoul", "telegram_message_id": 25, "text": ""}]
    payload = {"top_consolidated_recommendations": [{
        "stock_code": "OFH",
        "data_points": [{
            "source": "Ostoul",
            "source_message_id": "25",
            "recommendation_evidence": "previous recommendation target reached",
            "recommendation_type": "buy",
            "buy_price_low": 0.720,
            "buy_price_high": 0.724,
            "target_1": 0.738,
            "target_2": 0.749,
            "stop_loss": 0.710,
        }],
    }]}

    assert validate_consolidated_output(payload, messages) == []


@pytest.mark.asyncio
async def test_consolidated_analysis_uses_one_model_request():
    invalid = {
        "analysis_period": "test", "top_consolidated_recommendations": [{
            "stock_code": "COMI", "stock_name_en": "CIB", "data_points": [{
                "source": "CFI", "source_message_id": "7", "recommendation_type": "buy", "target_1": 100,
            }],
        }], "client_inquiry_responses": [],
    }
    corrected = json.loads(json.dumps(invalid))
    corrected["top_consolidated_recommendations"][0]["data_points"][0]["recommendation_evidence"] = (
        "COMI - توصية شراء"
    )
    responses = [invalid, corrected]
    service = object.__new__(AIAnalysisService)
    service.settings = SimpleNamespace()
    service.prompt = ""

    async def fake_analyze_prompt(*_args, **_kwargs):
        payload = responses.pop(0)
        return AnalysisOutcome(
            result=_analysis_result_from_payload(payload), raw_response=json.dumps(payload, ensure_ascii=False),
            input_metrics={"model_request_ms": 10},
        )

    service._analyze_prompt = fake_analyze_prompt
    outcome = await service.analyze_consolidated(
        [{"source": "CFI", "telegram_message_id": 7, "published_at": "2026-07-16T10:00:00+03:00",
          "text": "", "image_paths": [], "transcripts": []}],
        "test", "2026-07-16",
    )

    assert outcome.correction_attempted is False
    assert outcome.validation_warnings == []
    assert outcome.retry_audit["status"] == "not_required"
    assert outcome.input_metrics["model_request_count"] == 1
    assert len(responses) == 1
    point = json.loads(outcome.raw_response)["top_consolidated_recommendations"][0]["data_points"][0]
    assert point["source"] == "CFI"
    assert "recommendation_evidence" not in point


def test_minimal_provenance_excludes_unknown_ids_and_restores_one_image_reference():
    messages = [{
        "source": "إسأل فني📉🐎",
        "telegram_message_id": 60035,
        "text": "",
    }]
    payload = {"top_consolidated_recommendations": [{
        "stock_code": "COMI",
        "mention_count": 2,
        "data_points": [
            {"source_message_id": "60035", "source": "Changed model label"},
            {"source_message_id": "99999"},
        ],
    }]}
    references = {
        4: {
            "path": "recommendation.jpg",
            "source": "إسأل فني",
            "source_message_id": "60035",
            "image_index": "1",
        },
    }

    warnings = normalize_consolidated_output(payload, messages, references)

    assert warnings == ["Excluded recommendation with unknown Telegram message 99999."]
    stock = payload["top_consolidated_recommendations"][0]
    assert stock["mention_count"] == 1
    assert stock["data_points"][0]["source"] == "إسأل فني"
    assert stock["data_points"][0]["source_image_ref"] == 4


def test_channel_names_remove_emojis_without_changing_words():
    assert clean_channel_name("إسأل فني📉🐎") == "إسأل فني"
    assert clean_channel_name("CFI Egypt 📊") == "CFI Egypt"


def test_past_recommendation_caption_detection_handles_arabic_and_english_markers():
    assert has_past_recommendation_context("\u0631\u062f\u064b\u0627 \u0639\u0644\u0649 \u0627\u0644\u062a\u0648\u0635\u064a\u0629 \u0627\u0644\u0633\u0627\u0628\u0642\u0629")
    assert has_past_recommendation_context("Previous recommendation: CIB target achieved")
    assert not has_past_recommendation_context("\u062a\u0648\u0635\u064a\u0629 \u0634\u0631\u0627\u0621 \u062c\u062f\u064a\u062f\u0629 \u0644\u062c\u0644\u0633\u0629 \u0627\u0644\u063a\u062f")


def test_target_hit_or_previous_update_is_excluded_before_model_analysis():
    assert is_non_actionable_stock_update("وصل إلى المستهدف الأول")
    assert is_non_actionable_stock_update("تم تحقيق المستهدف الرئيسي")
    assert is_non_actionable_stock_update("Target reached for CIB")
    assert is_non_actionable_stock_update("Previous recommendation: CIB")
    assert not is_non_actionable_stock_update("إشارة تداول شراء لجلسة الغد")


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


async def test_empty_selected_analysis_returns_422_instead_of_logging_error(session, tmp_path, monkeypatch):
    from app import api as api_module
    import app.main as main_module

    class EmptyRuntime:
        async def collect_once(self, *_args, **_kwargs):
            return {
                "messages_in_window": 0,
                "messages_analyzed": 0,
                "messages_reanalyzed": 0,
                "messages_already_saved": 0,
            }

    monkeypatch.setattr(main_module, "runtime", EmptyRuntime())
    monkeypatch.setattr(api_module, "get_settings", lambda: SimpleNamespace(storage_root=tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        await api_module.analyze_selected_channels(
            CollectionRequest(channel_ids=[999], content_types={"images"}), session,
        )

    assert exc_info.value.status_code == 422
    assert "No selected content was found" in exc_info.value.detail
    trace = max((tmp_path / "analysis-traces").glob("*/*"), key=lambda path: path.stat().st_mtime)
    assert json.loads((trace / "model-input.json").read_text(encoding="utf-8"))["messages"] == []


async def test_running_selected_analysis_can_be_cancelled(session, monkeypatch):
    from app import api as api_module
    import app.main as main_module

    collection_started = asyncio.Event()
    keep_collecting = asyncio.Event()

    class SlowRuntime:
        async def collect_once(self, *_args, **_kwargs):
            collection_started.set()
            await keep_collecting.wait()
            raise AssertionError("Cancelled collection should not complete")

    monkeypatch.setattr(main_module, "runtime", SlowRuntime())
    request_id = "cancel-test-123"
    analysis_task = asyncio.create_task(api_module.analyze_selected_channels(
        CollectionRequest(channel_ids=[999], content_types={"images"}, request_id=request_id), session,
    ))
    await asyncio.wait_for(collection_started.wait(), timeout=1)

    response = await api_module.cancel_selected_analysis(request_id)

    assert response == {"cancelled": True}
    with pytest.raises(asyncio.CancelledError):
        await analysis_task
    assert request_id not in api_module._active_analysis_tasks
