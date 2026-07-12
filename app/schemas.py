from datetime import datetime
from pydantic import BaseModel, Field
from app.models import Signal


class ExtractedRecommendation(BaseModel):
    company_name: str
    ticker: str | None = None
    signal: Signal
    entry: float | None = None
    target: float | None = None
    stop_loss: float | None = None
    reason: str | None = None
    risk_level: str | None = None
    time_horizon: str | None = None
    indicators: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class AnalysisResult(BaseModel):
    recommendations: list[ExtractedRecommendation] = Field(default_factory=list)
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


class ChannelUpdate(BaseModel):
    active: bool


class SearchRequest(BaseModel):
    query: str = Field(min_length=2)
    limit: int = Field(default=20, ge=1, le=100)


class SettingsUpdate(BaseModel):
    openai_api_key: str | None = None
    openai_model: str | None = None
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session: str | None = None


class TelegramCodeRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)


class TelegramCodeVerification(BaseModel):
    code: str = Field(min_length=3, max_length=10)
    password: str | None = None
