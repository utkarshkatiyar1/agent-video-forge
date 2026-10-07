"""Caption overlays rendered with Pillow (avoids FFmpeg drawtext font/escaping issues on Windows)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def wrap(text: str, font, max_width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and font.getlength(trial) > max_width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def render_caption_overlay(text: str, width: int, height: int, out: Path) -> Path:
    """Transparent full-frame PNG with a rounded caption bar near the bottom."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = load_font(max(24, height // 16))
    lines = wrap(text, font, int(width * 0.8))
    line_h = font.getbbox("Ag")[3] + 8
    box_h, pad = line_h * len(lines), 22
    box_w = int(max(font.getlength(l) for l in lines)) + pad * 2
    x0, y1 = (width - box_w) // 2, int(height * 0.93)
    y0 = y1 - box_h - pad * 2
    d.rounded_rectangle([x0, y0, x0 + box_w, y1], radius=18, fill=(0, 0, 0, 165))
    for i, line in enumerate(lines):
        w = font.getlength(line)
        d.text(((width - w) / 2, y0 + pad + i * line_h), line, font=font, fill=(255, 255, 255, 255))
    img.save(out, "PNG")
    return out
