"""Interactive Telegram authorization for the local desktop application."""
from pathlib import Path

from telethon import TelegramClient
from app.config import get_settings


class TelegramAuthenticator:
    def __init__(self) -> None:
        self.client: TelegramClient | None = None
        self.phone: str | None = None

    async def request_code(self, phone: str) -> None:
        settings = get_settings()
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise RuntimeError("Save Telegram API ID and API hash first")
        if self.client is not None:
            await self.client.disconnect()
        self.client = TelegramClient(settings.telegram_session, settings.telegram_api_id, settings.telegram_api_hash)
        await self.client.connect()
        await self.client.send_code_request(phone)
        self.phone = phone

    async def verify(self, code: str, password: str | None = None) -> bool:
        if self.client is None or self.phone is None:
            raise RuntimeError("Request a Telegram code first")
        await self.client.sign_in(phone=self.phone, code=code, password=password)
        authorized = await self.client.is_user_authorized()
        await self.client.disconnect()
        self.client = None
        return authorized

    async def reset_session(self, session_path: str) -> None:
        if self.client is not None:
            await self.client.disconnect()
            self.client = None
        self.phone = None
        for suffix in (".session", ".session-journal", ".session-shm", ".session-wal"):
            Path(f"{session_path}{suffix}").unlink(missing_ok=True)
