"""Persistent local configuration with Windows user-bound secret protection."""
import json
import os
from pathlib import Path
import subprocess

SECRET_KEYS = {"OPENAI_API_KEY", "TELEGRAM_API_HASH"}


def config_path() -> Path:
    return Path(os.getenv("EGX_CONFIG_FILE", ".env"))


def _secret_path() -> Path:
    return config_path().with_name("secrets.json")


def _read_public() -> dict[str, str]:
    path = config_path()
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value
    return values


def _write_public(values: dict[str, str]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(f"{key}={value}" for key, value in sorted(values.items())) + "\n", encoding="utf-8")
    temporary.replace(path)


def _protect(value: str) -> str:
    if os.name != "nt":
        return value
    script = """Add-Type -AssemblyName System.Security;$value=[Console]::In.ReadToEnd();$bytes=[Text.Encoding]::UTF8.GetBytes($value);$protected=[Security.Cryptography.ProtectedData]::Protect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser);[Convert]::ToBase64String($protected)"""
    return subprocess.run(["powershell", "-NoProfile", "-Command", script], input=value, text=True,
                          capture_output=True, check=True).stdout.strip()


def _unprotect(value: str) -> str:
    if os.name != "nt":
        return value
    script = """Add-Type -AssemblyName System.Security;$value=[Console]::In.ReadToEnd();$bytes=[Convert]::FromBase64String($value);$plain=[Security.Cryptography.ProtectedData]::Unprotect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser);[Text.Encoding]::UTF8.GetString($plain)"""
    return subprocess.run(["powershell", "-NoProfile", "-Command", script], input=value, text=True,
                          capture_output=True, check=True).stdout.rstrip("\r\n")


def load_secrets_into_environment() -> None:
    public = _read_public()
    migrated = {key: public.pop(key) for key in SECRET_KEYS if public.get(key)}
    secret_file = _secret_path()
    encrypted: dict[str, str] = json.loads(secret_file.read_text(encoding="utf-8")) if secret_file.exists() else {}
    if migrated:
        encrypted.update({key: _protect(value) for key, value in migrated.items()})
        _write_public(public)
    if encrypted:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(json.dumps(encrypted), encoding="utf-8")
        for key, value in encrypted.items():
            os.environ[key] = _unprotect(value)


def update_config(values: dict[str, str]) -> None:
    public = _read_public()
    secret_file = _secret_path()
    encrypted: dict[str, str] = json.loads(secret_file.read_text(encoding="utf-8")) if secret_file.exists() else {}
    for key, value in values.items():
        if not value:
            continue
        if key in SECRET_KEYS:
            encrypted[key] = _protect(value)
            os.environ[key] = value
        else:
            public[key] = value
    _write_public(public)
    if encrypted:
        secret_file.write_text(json.dumps(encrypted), encoding="utf-8")
