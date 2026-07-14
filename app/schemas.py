from datetime import datetime
from pydantic import BaseModel, Field
from app.models import Signal


class ExtractedRecommendation(BaseModel):
    company_name: str
    ticker: str | None = None
    signal: Signal
    entry: float | None = None
    target: float | None = None
    target_2: float | None = None
    stop_loss: float | None = None
    reason: str | None = None
    risk_level: str | None = None
    time_horizon: str | None = None
    indicators: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ExtractedStockMention(BaseModel):
    ticker: str = Field(min_length=1, max_length=30)
    company_name: str | None = Field(default=None, max_length=255)
    context: str | None = Field(default=None, max_length=1000)
    table_data: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0, le=1)


class AnalysisResult(BaseModel):
    recommendations: list[ExtractedRecommendation] = Field(default_factory=list)
    stock_mentions: list[ExtractedStockMention] = Field(default_factory=list)
    image_observations: list[str] = Field(default_factory=list)


class MessageCreate(BaseModel):
    channel_handle: str
    telegram_message_id: int
    published_at: datetime
    text: str = ""
    author: str | None = None
    views: int | None = None
    forwarded_from: str | None = None


class ChannelCreate(BaseModel):
    handle: str = Field(min_length=3, max_length=255)
    title: str | None = Field(default=None, max_length=255)


class TelegramChatSelect(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    username: str = Field(default="", max_length=255)
    kind: str = Field(default="channel", max_length=30)


class ChannelUpdate(BaseModel):
    active: bool


class CollectionRequest(BaseModel):
    channel_ids: list[int] = Field(min_length=1)
    analyze: bool = True


class DailyReportRequest(BaseModel):
    report_mode: str = Field(default="calendar", pattern="^(calendar|session)$")
    report_date: datetime | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2)
    limit: int = Field(default=20, ge=1, le=100)


class SettingsUpdate(BaseModel):
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    huggingface_api_key: str | None = None
    qwen_api_key: str | None = None
    qwen_base_url: str | None = Field(default=None, pattern="^https://.+")
    ai_provider: str | None = Field(default=None, pattern="^(qwen|openrouter|huggingface|openai)$")
    openai_model: str | None = None
    analysis_instructions: str | None = Field(default=None, max_length=8000)
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session: str | None = None


class TelegramCodeRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)


class TelegramCodeVerification(BaseModel):
    code: str = Field(min_length=3, max_length=10)
    password: str | None = None
