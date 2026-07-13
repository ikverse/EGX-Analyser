from functools import lru_cache
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.config_store import load_secrets_into_environment


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.getenv("EGX_CONFIG_FILE", ".env"), extra="ignore")
    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./stock_intelligence.db"
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    huggingface_api_key: str | None = None
    qwen_api_key: str | None = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    content_pack_manifest_url: str = "https://raw.githubusercontent.com/ikverse/EGX-Analyser/main/remote-content/content-pack.json"
    ai_provider: str = ""
    openai_model: str = "openrouter/free"
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session: str = "egx_collector"
    telegram_channels: str = ""
    storage_root: Path = Path("storage")
    report_language: str = "bilingual"
    egx_session_start: str = "10:00"
    egx_session_end: str = "14:30"
    @property
    def channels(self) -> list[str]:
        return [item.strip().lstrip("@") for item in self.telegram_channels.split(",") if item.strip()]

    @property
    def ai_api_key(self) -> str | None:
        return {
            "openai": self.openai_api_key,
            "openrouter": self.openrouter_api_key,
            "huggingface": self.huggingface_api_key,
            "qwen": self.qwen_api_key,
        }.get(self.ai_provider)


@lru_cache
def get_settings() -> Settings:
    load_secrets_into_environment()
    settings = Settings()
    if not settings.ai_provider:
        settings.ai_provider = "openai" if settings.openai_api_key else "qwen"
    return settings
