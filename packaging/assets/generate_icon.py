#!/usr/bin/env python3
"""Generate Data Handler macOS icon assets."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
PNG_PATH = ROOT / "DataHandlerIcon.png"
ICNS_PATH = ROOT / "DataHandlerIcon.icns"
ICONSET_PATH = ROOT / "DataHandlerIcon.iconset"


def _rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
        alpha,
    )


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _circle(draw: ImageDraw.ImageDraw, center, radius, fill, outline=None, width=1) -> None:
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill, outline=outline, width=width)


def draw_icon(size: int = 1024) -> Image.Image:
    scale = size / 1024

    def s(value: float) -> int:
        return round(value * scale)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Soft macOS-style outer shadow.
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    _rounded(sd, (s(74), s(84), s(950), s(960)), s(210), _rgba("#0D1321", 58))
    shadow = shadow.filter(ImageFilter.GaussianBlur(s(28)))
    canvas.alpha_composite(shadow)

    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    tile_box = (s(84), s(64), s(940), s(920))
    _rounded(bd, tile_box, s(204), _rgba("#F7F3EC"))

    # Subtle warm-to-cool diagonal surface, clipped to the tile mask.
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(s(64), s(921)):
        t = (y - s(64)) / max(1, s(856))
        r = round(250 * (1 - t) + 232 * t)
        g = round(246 * (1 - t) + 241 * t)
        b = round(236 * (1 - t) + 238 * t)
        gd.line((s(84), y, s(940), y), fill=(r, g, b, 255))
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    _rounded(md, tile_box, s(204), 255)
    base.alpha_composite(Image.composite(grad, Image.new("RGBA", (size, size), (0, 0, 0, 0)), mask))

    # Inner rim and highlight keep the shape crisp on light and dark desktops.
    _rounded(bd, tile_box, s(204), None, _rgba("#FFFFFF", 128), s(4))
    _rounded(bd, (s(110), s(92), s(914), s(892)), s(184), None, _rgba("#B9C2C9", 72), s(2))
    canvas.alpha_composite(base)

    art = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)

    # Main data tray.
    tray_shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tsd = ImageDraw.Draw(tray_shadow)
    _rounded(tsd, (s(256), s(405), s(768), s(710)), s(76), _rgba("#0D1321", 42))
    tray_shadow = tray_shadow.filter(ImageFilter.GaussianBlur(s(18)))
    art.alpha_composite(tray_shadow)

    _rounded(d, (s(252), s(386), s(772), s(694)), s(76), _rgba("#273449"))
    _rounded(d, (s(286), s(424), s(738), s(514)), s(42), _rgba("#E8EEF0"))
    _rounded(d, (s(286), s(538), s(738), s(656)), s(46), _rgba("#F9FBF8"))

    # Quiet data rows.
    for y, width, color in (
        (s(454), s(264), "#8FA4A7"),
        (s(484), s(342), "#D06457"),
        (s(580), s(318), "#6A8F8C"),
        (s(618), s(238), "#C5A45A"),
    ):
        d.rounded_rectangle((s(352), y, s(352) + width, y + s(14)), radius=s(7), fill=_rgba(color))

    # Three compact transfer nodes, inspired by task/workflow utility apps.
    connector = _rgba("#6A8F8C", 255)
    d.line((s(394), s(340), s(512), s(286), s(630), s(340)), fill=connector, width=s(18), joint="curve")
    d.line((s(512), s(286), s(512), s(386)), fill=connector, width=s(18))

    for center, fill, radius in (
        ((s(394), s(340)), "#D96459", 54),
        ((s(512), s(286)), "#86AFA9", 58),
        ((s(630), s(340)), "#D6B763", 54),
    ):
        _circle(d, center, s(radius + 8), _rgba("#F7F3EC"))
        _circle(d, center, s(radius), _rgba(fill))
        _circle(d, (center[0] - s(14), center[1] - s(16)), s(13), _rgba("#FFFFFF", 92))

    # Bottom handle suggests packaging/output without adding text.
    _rounded(d, (s(398), s(730), s(626), s(778)), s(24), _rgba("#273449"))
    _rounded(d, (s(432), s(742), s(592), s(758)), s(8), _rgba("#F7F3EC", 210))

    canvas.alpha_composite(art)
    return canvas


def write_iconset(source: Image.Image) -> None:
    if ICONSET_PATH.exists():
        for child in ICONSET_PATH.iterdir():
            child.unlink()
    else:
        ICONSET_PATH.mkdir(parents=True)

    specs = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for filename, target_size in specs:
        resized = source.resize((target_size, target_size), Image.Resampling.LANCZOS)
        resized.save(ICONSET_PATH / filename)


def build_icns() -> None:
    iconutil = shutil.which("iconutil")
    if not iconutil:
        return
    subprocess.run([iconutil, "-c", "icns", str(ICONSET_PATH), "-o", str(ICNS_PATH)], check=True)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    source = draw_icon(1024)
    source.save(PNG_PATH)
    write_iconset(source)
    build_icns()
    print(PNG_PATH)
    if ICNS_PATH.exists():
        print(ICNS_PATH)


if __name__ == "__main__":
    main()
