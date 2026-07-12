"""Create the Windows application icon used by the Tauri bundle."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    output = Path(__file__).parents[1] / "desktop" / "src-tauri" / "icons" / "icon.ico"
    output.parent.mkdir(parents=True, exist_ok=True)
    size = 256
    image = Image.new("RGBA", (size, size), "#0f172a")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, 238, 238), radius=48, fill="#123a2c", outline="#4ade80", width=8)
    draw.line((56, 182, 105, 132, 142, 152, 202, 75), fill="#86efac", width=14, joint="curve")
    draw.polygon(((184, 76), (207, 70), (201, 95)), fill="#86efac")
    font = ImageFont.truetype("arialbd.ttf", 50)
    draw.text((63, 48), "EGX", font=font, fill="#f8fafc")
    image.save(output, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
