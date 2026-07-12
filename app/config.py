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
    openai_model: str = "gpt-5.5"
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session: str = "egx_collector"
    telegram_channels: str = ""
    storage_root: Path = Path("storage")
    @property
    def channels(self) -> list[str]:
        return [item.strip().lstrip("@") for item in self.telegram_channels.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    load_secrets_into_environment()
    return Settings()
