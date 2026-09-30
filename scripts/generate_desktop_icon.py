"""Create the Windows application icon used by the Tauri bundle."""
from pathlib import Path

from PIL import Image


def main() -> None:
    project_root = Path(__file__).parents[1]
    source = project_root / "desktop" / "public" / "branding" / "egx-analyzer-icon.png"
    output = project_root / "desktop" / "src-tauri" / "icons" / "icon.ico"
    if not source.exists():
        raise FileNotFoundError(f"Desktop icon source is missing: {source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(source).convert("RGBA")
    image.save(output, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
