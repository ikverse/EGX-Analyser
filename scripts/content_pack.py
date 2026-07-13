import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.content_updates import generate_seed, public_key_from_seed, sign_manifest

PRIVATE_KEY_PATH = ROOT / ".content-update-private.key"
PUBLIC_KEY_PATH = ROOT / "app" / "content_pack_public_key.txt"
SOURCE_PATH = ROOT / "remote-content" / "source"
ARCHIVE_PATH = ROOT / "remote-content" / "content-pack.zip"
MANIFEST_PATH = ROOT / "remote-content" / "content-pack.json"
ARCHIVE_URL = "https://raw.githubusercontent.com/ikverse/EGX-Analyser/main/remote-content/content-pack.zip"


def read_seed() -> bytes:
    try:
        return base64.b64decode(PRIVATE_KEY_PATH.read_text(encoding="utf-8").strip(), validate=True)
    except (OSError, ValueError) as error:
        raise SystemExit("Run `python scripts/content_pack.py init` before publishing a content pack.") from error


def initialize() -> None:
    if PRIVATE_KEY_PATH.exists() or PUBLIC_KEY_PATH.exists():
        raise SystemExit("A content update key already exists. Do not replace it after publishing packs.")
    seed = generate_seed()
    PRIVATE_KEY_PATH.write_text(base64.b64encode(seed).decode("ascii") + "\n", encoding="utf-8")
    PUBLIC_KEY_PATH.write_text(base64.b64encode(public_key_from_seed(seed)).decode("ascii") + "\n", encoding="utf-8")
    print(f"Created private signing key: {PRIVATE_KEY_PATH}")
    print(f"Created public verification key: {PUBLIC_KEY_PATH}")
    print("Back up the private key securely. Never commit or share it.")


def build(version: str) -> None:
    seed = read_seed()
    if not PUBLIC_KEY_PATH.exists():
        raise SystemExit("The public verification key is missing.")
    files = [path for path in SOURCE_PATH.iterdir() if path.is_file() and path.name in {"recommendation.md", "stock_aliases.json"}]
    if not files:
        raise SystemExit("Add recommendation.md or stock_aliases.json under remote-content/source first.")
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(files):
            archive.write(file_path, file_path.name)
    checksum = hashlib.sha256(ARCHIVE_PATH.read_bytes()).hexdigest()
    manifest = {"version": version, "archive_url": ARCHIVE_URL, "sha256": checksum}
    manifest["signature"] = sign_manifest(seed, manifest)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built signed content pack {version}.")


parser = argparse.ArgumentParser(description="Create and sign EGX Intelligence content packs.")
subcommands = parser.add_subparsers(dest="command", required=True)
subcommands.add_parser("init")
build_parser = subcommands.add_parser("build")
build_parser.add_argument("--version", required=True)
arguments = parser.parse_args()

if arguments.command == "init":
    initialize()
else:
    build(arguments.version)
