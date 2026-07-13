import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.content_updates import sign_manifest

ARCHIVE_PATH = ROOT / "remote-engine" / "engine-pack.zip"
MANIFEST_PATH = ROOT / "remote-engine" / "engine-pack.json"
ARCHIVE_URL = "https://raw.githubusercontent.com/ikverse/EGX-Analyser/main/remote-engine/engine-pack.zip"
PRIVATE_KEY_PATH = ROOT / ".content-update-private.key"


def read_seed() -> bytes:
    if not PRIVATE_KEY_PATH.exists():
        raise SystemExit(
            "Missing .content-update-private.key. Run scripts/enable-content-updates.ps1 first."
        )
    try:
        seed = base64.b64decode(PRIVATE_KEY_PATH.read_text(encoding="utf-8").strip())
    except ValueError as error:
        raise SystemExit("The content update signing key is invalid.") from error
    if len(seed) != 32:
        raise SystemExit("The content update signing key must be 32 bytes.")
    return seed


def build(version: str) -> None:
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "egx-intelligence-api", "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'app' / 'content_pack_public_key.txt'};app",
        "--add-data", f"{ROOT / 'app' / 'ai' / 'prompts'};app/ai/prompts",
        "--hidden-import", "aiosqlite", "desktop/sidecar_server.py",
    ], cwd=ROOT, check=True)
    engine = ROOT / "dist" / "egx-intelligence-api.exe"
    if not engine.exists():
        raise SystemExit("The engine executable was not created.")
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(engine, engine.name)
    manifest = {"version": version, "archive_url": ARCHIVE_URL, "sha256": hashlib.sha256(ARCHIVE_PATH.read_bytes()).hexdigest()}
    manifest["signature"] = sign_manifest(read_seed(), manifest)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built signed engine pack {version}.")


parser = argparse.ArgumentParser(description="Create a signed EGX Intelligence engine patch.")
parser.add_argument("--version", required=True)
arguments = parser.parse_args()
build(arguments.version)
