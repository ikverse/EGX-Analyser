"""Entrypoint packaged with PyInstaller for the EGX desktop application."""
import os
from pathlib import Path

app_data = Path(os.getenv("LOCALAPPDATA", Path.home())) / "EGX Intelligence"
app_data.mkdir(parents=True, exist_ok=True)
config_path = app_data / ".env"
os.environ["EGX_CONFIG_FILE"] = str(config_path)
os.environ.setdefault("STORAGE_ROOT", str(app_data / "storage"))
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(app_data / 'intelligence.db').as_posix()}")
os.environ["TELEGRAM_SESSION"] = str(app_data / "telegram")

import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_config=None, access_log=False)
