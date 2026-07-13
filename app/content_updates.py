import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import secrets
from typing import Any
import zipfile

import httpx

from app.config import Settings

_FIELD = 2**255 - 19
_ORDER = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _FIELD - 2, _FIELD)) % _FIELD
_BASE_Y = (4 * pow(5, _FIELD - 2, _FIELD)) % _FIELD
_ALLOWED_FILES = {"recommendation.md", "stock_aliases.json"}
_MAX_ARCHIVE_BYTES = 2 * 1024 * 1024


class ContentUpdateError(RuntimeError):
    pass


def _recover_x(y: int) -> int:
    value = (y * y - 1) * pow(_D * y * y + 1, _FIELD - 2, _FIELD) % _FIELD
    x = pow(value, (_FIELD + 3) // 8, _FIELD)
    if (x * x - value) % _FIELD:
        x = x * pow(2, (_FIELD - 1) // 4, _FIELD) % _FIELD
    return x


_BASE_POINT = (_recover_x(_BASE_Y), _BASE_Y)
if _BASE_POINT[0] & 1:
    _BASE_POINT = (_FIELD - _BASE_POINT[0], _BASE_POINT[1])


def _add(left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
    left_x, left_y = left
    right_x, right_y = right
    product = _D * left_x * right_x * left_y * right_y
    x = (left_x * right_y + right_x * left_y) * pow(1 + product, _FIELD - 2, _FIELD)
    y = (left_y * right_y + left_x * right_x) * pow(1 - product, _FIELD - 2, _FIELD)
    return x % _FIELD, y % _FIELD


def _multiply(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    result = (0, 1)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _encode(point: tuple[int, int]) -> bytes:
    x, y = point
    encoded = bytearray(y.to_bytes(32, "little"))
    encoded[31] |= (x & 1) << 7
    return bytes(encoded)


def _decode(encoded: bytes) -> tuple[int, int]:
    if len(encoded) != 32:
        raise ContentUpdateError("Invalid Ed25519 key or signature point length")
    sign = encoded[31] >> 7
    y = int.from_bytes(bytes([*encoded[:31], encoded[31] & 127]), "little")
    if y >= _FIELD:
        raise ContentUpdateError("Invalid Ed25519 key or signature point")
    x = _recover_x(y)
    if x & 1 != sign:
        x = _FIELD - x
    if (y * y - x * x - 1 - _D * x * x * y * y) % _FIELD:
        raise ContentUpdateError("Invalid Ed25519 key or signature point")
    return x, y


def public_key_from_seed(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("Ed25519 seeds must contain exactly 32 bytes")
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return _encode(_multiply(_BASE_POINT, scalar))


def sign_bytes(seed: bytes, payload: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("Ed25519 seeds must contain exactly 32 bytes")
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    nonce = int.from_bytes(hashlib.sha512(digest[32:] + payload).digest(), "little") % _ORDER
    encoded_nonce = _encode(_multiply(_BASE_POINT, nonce))
    public_key = public_key_from_seed(seed)
    challenge = int.from_bytes(hashlib.sha512(encoded_nonce + public_key + payload).digest(), "little") % _ORDER
    return encoded_nonce + ((nonce + challenge * scalar) % _ORDER).to_bytes(32, "little")


def verify_bytes(public_key: bytes, payload: bytes, signature: bytes) -> bool:
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        nonce = _decode(signature[:32])
        signer = _decode(public_key)
    except ContentUpdateError:
        return False
    scalar = int.from_bytes(signature[32:], "little")
    if scalar >= _ORDER:
        return False
    challenge = int.from_bytes(hashlib.sha512(signature[:32] + public_key + payload).digest(), "little") % _ORDER
    return secrets.compare_digest(_encode(_multiply(_BASE_POINT, scalar)), _encode(_add(nonce, _multiply(signer, challenge))))


def manifest_payload(manifest: dict[str, Any]) -> bytes:
    fields = {key: manifest[key] for key in ("archive_url", "sha256", "version")}
    return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(seed: bytes, manifest: dict[str, Any]) -> str:
    return base64.b64encode(sign_bytes(seed, manifest_payload(manifest))).decode("ascii")


def generate_seed() -> bytes:
    return os.urandom(32)


class ContentUpdateService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root / "content-updates"
        self.active = self.root / "active"
        self.previous = self.root / "previous"

    @property
    def bundled_public_key_path(self) -> Path:
        return Path(__file__).with_name("content_pack_public_key.txt")

    def public_key(self) -> bytes:
        try:
            encoded = self.bundled_public_key_path.read_text(encoding="utf-8").strip()
            return base64.b64decode(encoded, validate=True)
        except (OSError, ValueError) as error:
            raise ContentUpdateError("Content updates are not configured in this app build") from error

    def active_version(self) -> str | None:
        version_path = self.active / ".version"
        return version_path.read_text(encoding="utf-8").strip() if version_path.exists() else None

    def status(self) -> dict[str, object]:
        try:
            enabled = len(self.public_key()) == 32
        except ContentUpdateError:
            enabled = False
        return {"enabled": enabled, "version": self.active_version(), "source": self.settings.content_pack_manifest_url}

    def file_path(self, filename: str) -> Path | None:
        candidate = self.active / filename
        return candidate if filename in _ALLOWED_FILES and candidate.is_file() else None

    def stock_aliases(self) -> dict[str, str]:
        aliases_path = self.file_path("stock_aliases.json")
        if aliases_path is None:
            return {}
        try:
            values = json.loads(aliases_path.read_text(encoding="utf-8"))
            aliases = values.get("aliases", {})
            return {str(name).strip().casefold(): str(ticker).strip().upper() for name, ticker in aliases.items()}
        except (OSError, ValueError, TypeError):
            return {}

    async def check_and_apply(self) -> dict[str, object]:
        if len(self.public_key()) != 32:
            raise ContentUpdateError("The content update public key is invalid")
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(self.settings.content_pack_manifest_url)
                response.raise_for_status()
                manifest = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ContentUpdateError("Unable to download the signed content update manifest") from error
        required = {"version", "archive_url", "sha256", "signature"}
        if not isinstance(manifest, dict) or not required.issubset(manifest):
            raise ContentUpdateError("The content update manifest is incomplete")
        try:
            signature = base64.b64decode(manifest["signature"], validate=True)
        except (TypeError, ValueError) as error:
            raise ContentUpdateError("The content update signature is malformed") from error
        if not verify_bytes(self.public_key(), manifest_payload(manifest), signature):
            raise ContentUpdateError("The content update signature is invalid")
        if manifest["version"] == self.active_version():
            return {"updated": False, "version": manifest["version"]}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                archive = await client.get(manifest["archive_url"])
                archive.raise_for_status()
                archive_bytes = archive.content
        except httpx.HTTPError as error:
            raise ContentUpdateError("Unable to download the content update archive") from error
        if len(archive_bytes) > _MAX_ARCHIVE_BYTES or hashlib.sha256(archive_bytes).hexdigest() != manifest["sha256"]:
            raise ContentUpdateError("The content update archive integrity check failed")
        self._install_archive(str(manifest["version"]), archive_bytes)
        return {"updated": True, "version": manifest["version"]}

    def _install_archive(self, version: str, archive_bytes: bytes) -> None:
        staging = self.root / f"staging-{version}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                names = {item.filename for item in files}
                if not names or not names.issubset(_ALLOWED_FILES) or sum(item.file_size for item in files) > _MAX_ARCHIVE_BYTES:
                    raise ContentUpdateError("The content update archive includes unsupported files")
                for name in names:
                    target = staging / name
                    target.write_bytes(archive.read(name))
            (staging / ".version").write_text(version, encoding="utf-8")
            shutil.rmtree(self.previous, ignore_errors=True)
            if self.active.exists():
                self.active.replace(self.previous)
            staging.replace(self.active)
        except (ContentUpdateError, OSError, zipfile.BadZipFile) as error:
            shutil.rmtree(staging, ignore_errors=True)
            if not self.active.exists() and self.previous.exists():
                self.previous.replace(self.active)
            raise ContentUpdateError("The content update could not be installed") from error
