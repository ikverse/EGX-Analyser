import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
from typing import Any
import zipfile

import httpx

from app.config import Settings
from app.content_updates import ContentUpdateError, ContentUpdateService, manifest_payload, verify_bytes

_ENGINE_FILE = "egx-intelligence-api.exe"
_MAX_ARCHIVE_BYTES = 150 * 1024 * 1024


class EngineUpdateService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root.parent / "engine-updates"
        self.pending = self.root / "pending"

    def active_version(self) -> str:
        version_path = self.root / "current" / ".version"
        return version_path.read_text(encoding="utf-8").strip() if version_path.exists() else self.settings.engine_version

    def status(self) -> dict[str, object]:
        return {"version": self.active_version(), "source": self.settings.engine_pack_manifest_url}

    async def check_and_stage(self) -> dict[str, object]:
        verifier = ContentUpdateService(self.settings)
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(self.settings.engine_pack_manifest_url)
                response.raise_for_status()
                manifest: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ContentUpdateError("Unable to download the signed engine patch manifest") from error
        required = {"version", "archive_url", "sha256", "signature"}
        if not required.issubset(manifest):
            raise ContentUpdateError("The engine patch manifest is incomplete")
        try:
            signature = base64.b64decode(manifest["signature"], validate=True)
        except (TypeError, ValueError) as error:
            raise ContentUpdateError("The engine patch signature is malformed") from error
        if not verify_bytes(verifier.public_key(), manifest_payload(manifest), signature):
            raise ContentUpdateError("The engine patch signature is invalid")
        if str(manifest["version"]) == self.active_version():
            return {"updated": False, "version": manifest["version"], "restart_required": False}
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                archive = await client.get(manifest["archive_url"])
                archive.raise_for_status()
                archive_bytes = archive.content
        except httpx.HTTPError as error:
            raise ContentUpdateError("Unable to download the engine patch archive") from error
        if len(archive_bytes) > _MAX_ARCHIVE_BYTES or hashlib.sha256(archive_bytes).hexdigest() != manifest["sha256"]:
            raise ContentUpdateError("The engine patch archive integrity check failed")
        self._stage(str(manifest["version"]), archive_bytes)
        return {"updated": True, "version": manifest["version"], "restart_required": True}

    def _stage(self, version: str, archive_bytes: bytes) -> None:
        shutil.rmtree(self.pending, ignore_errors=True)
        self.pending.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                names = {item.filename for item in archive.infolist() if not item.is_dir()}
                if names != {_ENGINE_FILE} or archive.getinfo(_ENGINE_FILE).file_size > _MAX_ARCHIVE_BYTES:
                    raise ContentUpdateError("The engine patch archive includes unsupported files")
                (self.pending / _ENGINE_FILE).write_bytes(archive.read(_ENGINE_FILE))
            (self.pending / ".version").write_text(version, encoding="utf-8")
        except (ContentUpdateError, OSError, zipfile.BadZipFile) as error:
            shutil.rmtree(self.pending, ignore_errors=True)
            raise ContentUpdateError("The engine patch could not be staged") from error
