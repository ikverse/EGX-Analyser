from datetime import datetime, timedelta, timezone
import io
import os
import pytest
from fastapi import HTTPException
from httpx import Request, Response
from openai import AuthenticationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app import api
from app.models import Base, Image, Recommendation
from app.schemas import AnalysisResult, ExtractedRecommendation, MessageCreate, TelegramChatSelect
from app.ai.service import analysis_output_schema
from app.services import AnalyticsService, MessageService, SearchService
from app.config_store import load_secrets_into_environment, update_config
from app.content_updates import ContentUpdateService, generate_seed, public_key_from_seed, sign_bytes, verify_bytes
from app.engine_updates import EngineUpdateService
from app.telegram_auth import TelegramAuthenticator
from app.runtime import selected_analysis_start
from app.collector.telegram import is_promotional_message
from app.reports import ReportService


class FakeAnalyzer:
    async def analyze(self, text: str, image_paths: list[str], transcripts: list[str] | None = None) -> AnalysisResult:
        assert image_paths == ["chart.jpg"]
        assert transcripts == []
        return AnalysisResult(recommendations=[ExtractedRecommendation(
            company_name="Commercial International Bank", ticker="CIB", signal="BUY", confidence=.91
        )], image_observations=["RSI bullish"])

    async def embed(self, content: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "CIB" in content else [0.0, 1.0, 0.0]


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
    assert (await SearchService(session, FakeAnalyzer()).search("CIB outlook", 5))[0]["id"] == message.id


def test_local_settings_encrypt_secrets(monkeypatch, tmp_path):
    config_file = tmp_path / ".env"
    monkeypatch.setenv("EGX_CONFIG_FILE", str(config_file))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    update_config({"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "gpt-5.5"})
    assert "test-secret" not in config_file.read_text(encoding="utf-8")
    assert (tmp_path / "secrets.json").exists()
    load_secrets_into_environment()
    assert os.environ["OPENAI_API_KEY"] == "test-secret"


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


def test_engine_patch_stages_only_the_sidecar(tmp_path):
    import zipfile

    settings = type("Settings", (), {
        "storage_root": tmp_path / "storage", "engine_pack_manifest_url": "https://example.test/engine", "engine_version": "1.0.0"
    })()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("egx-intelligence-api.exe", b"engine")

    manager = EngineUpdateService(settings)
    manager._stage("1.0.1", archive_bytes.getvalue())

    assert (manager.pending / "egx-intelligence-api.exe").read_bytes() == b"engine"
    assert (manager.pending / ".version").read_text(encoding="utf-8") == "1.0.1"


def test_selected_analysis_starts_three_days_before_request():
    requested_at = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    assert selected_analysis_start(requested_at) == datetime(2026, 7, 10, 12, tzinfo=timezone.utc)


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
    session.add(Recommendation(message_id=stock_message.id, company_name="CIB", signal="BUY", confidence=.9, indicators=[]))
    await session.flush()
    report = await ReportService(session, type("Settings", (), {"storage_root": tmp_path})()).generate_selected_chat_report(
        [stock_message.channel_id, non_stock_message.channel_id], datetime.now(timezone.utc) - timedelta(days=3), datetime.now(timezone.utc)
    )
    statuses = {item["channel"]: item["status"] for item in report.summary["channel_results"]}
    assert statuses["stocks"] == "recommendations_found"
    assert statuses["general"] == "not_stock_related"
