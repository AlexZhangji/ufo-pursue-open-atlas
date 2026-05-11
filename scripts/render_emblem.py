#!/usr/bin/env python3
"""Render the PURSUE Open Atlas emblem to PNG at multiple sizes.

GitHub and HuggingFace avatars require raster (PNG/JPG); SVG isn't
accepted for profile/repo avatars. We draw the emblem with Pillow
primitives + Consolas (Windows) / DejaVu Sans Mono (fallback) instead of
going through Cairo so there's no system-library dependency.

Outputs (docs/branding/):
    emblem-256.png             paper bg, square — repo avatar
    emblem-512.png             paper bg, square — repo avatar (larger)
    emblem-transparent-512.png transparent bg — inline embedding
    emblem-social-1280x640.png paper bg, emblem centered — GH social preview

Run from repo root:
    python scripts/render_emblem.py
"""

from __future__ import annotations
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "branding"

# Colors
INK_BLACK  = (26, 24, 21, 255)   # #1a1815
INK_RED    = (168, 50, 50, 255)  # #a83232 — oxidized archival red
PAPER      = (244, 241, 236, 255)# #f4f1ec
CORNER_DIM = (216, 208, 194, 255)# #d8d0c2 — corner registration marks

# Font candidates (first available wins for each weight).
FONT_REG_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
FONT_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/consolab.ttf",
    "/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]


def first_existing(paths):
    for p in paths:
        if Path(p).exists():
            return p
    raise RuntimeError(f"No font found in {paths}")


def load_font(path, size):
    return ImageFont.truetype(path, size=size)


def draw_centered_text(draw, x_center, y_baseline, text, font, fill, letter_spacing=0):
    """Pillow's anchor doesn't handle letter-spacing; do it manually so
    we can match the SVG's wide-tracking look. y_baseline is where the
    text baseline sits."""
    chars = list(text)
    widths = [draw.textlength(c, font=font) for c in chars]
    total = sum(widths) + letter_spacing * max(0, len(chars) - 1)
    cursor_x = x_center - total / 2
    # Approximate ascent so we can position by baseline-ish (top-anchored draw).
    # Pillow doesn't expose ascent cleanly; we use font.getmetrics() ascent.
    ascent, _descent = font.getmetrics()
    y_top = y_baseline - ascent
    for c, w in zip(chars, widths):
        draw.text((cursor_x, y_top), c, font=font, fill=fill)
        cursor_x += w + letter_spacing


def star_points(cx, cy, r_outer, r_inner, n=5, rot_deg=-90):
    """n-point star centered at (cx, cy). rot_deg=-90 → first vertex up."""
    pts = []
    for i in range(2 * n):
        a = math.radians(rot_deg + i * 180 / n)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw_emblem(img, draw, size, *, with_corners=False):
    """Draw the emblem into a (size x size) region whose center is at
    (size/2, size/2). Used for both square avatars and centered on
    wider social-preview canvases."""
    s = size
    cx = cy = s / 2

    # Two concentric rings.
    pad = s * 0.025
    r_outer = s / 2 - pad
    r_inner = s / 2 - pad - s * 0.045
    stroke_outer = max(1.0, s * 0.011)
    stroke_inner = max(1.0, s * 0.0045)
    # Pillow draws filled ellipses; for an outline ring use ellipse with
    # outline= argument and width=.
    draw.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
                 outline=INK_BLACK, width=int(round(stroke_outer)))
    draw.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
                 outline=INK_BLACK, width=int(round(stroke_inner)))

    # Top red star.
    star_cy = cy - s * 0.27
    star_r_out = s * 0.075
    star_r_in  = s * 0.030
    pts = star_points(cx, star_cy, star_r_out, star_r_in)
    draw.polygon(pts, fill=INK_RED)

    # Side dots.
    dot_r = max(1.0, s * 0.011)
    dot_y = cy
    dot_dx = s * 0.365
    for dx in (-dot_dx, dot_dx):
        draw.ellipse([cx + dx - dot_r, dot_y - dot_r,
                      cx + dx + dot_r, dot_y + dot_r],
                     fill=INK_BLACK)

    # Type.
    font_pursue  = load_font(first_existing(FONT_BOLD_CANDIDATES), int(s * 0.115))
    font_subline = load_font(first_existing(FONT_REG_CANDIDATES),  int(s * 0.072))
    # Year band was running ~7% over the inner ring at Consolas widths.
    # Tightened font + letter-spacing to give clear margin.
    font_year    = load_font(first_existing(FONT_REG_CANDIDATES),  int(s * 0.046))

    draw_centered_text(draw, cx, cy - s * 0.020,
                       "PURSUE", font_pursue, INK_BLACK,
                       letter_spacing=s * 0.012)
    draw_centered_text(draw, cx, cy + s * 0.085,
                       "OPEN · ATLAS", font_subline, INK_BLACK,
                       letter_spacing=s * 0.024)

    # Bottom rule + year band — red.
    rule_y = cy + s * 0.185
    rule_x0 = cx - s * 0.115
    rule_x1 = cx + s * 0.115
    draw.line([rule_x0, rule_y, rule_x1, rule_y],
              fill=INK_RED, width=max(1, int(s * 0.0055)))
    draw_centered_text(draw, cx, cy + s * 0.275,
                       "MMXXVI · REL 01", font_year, INK_RED,
                       letter_spacing=s * 0.012)

    if with_corners:
        # Faint corner registration marks — only on the paper-bg avatars,
        # not on transparent (would look orphaned).
        margin = s * 0.04
        leg = s * 0.04
        w = max(1, int(s * 0.003))
        for ox, oy, dx1, dy1, dx2, dy2 in [
            (margin,     margin,     0, leg,  leg, 0),
            (s - margin, margin,    -leg, 0,  0, leg),
            (margin,     s - margin, 0, -leg, leg, 0),
            (s - margin, s - margin, -leg, 0, 0, -leg),
        ]:
            draw.line([ox + dx1, oy + dy1, ox, oy], fill=CORNER_DIM, width=w)
            draw.line([ox, oy, ox + dx2, oy + dy2], fill=CORNER_DIM, width=w)


def render_avatar(size, transparent=False, out_path=None):
    bg = (0, 0, 0, 0) if transparent else PAPER
    img = Image.new("RGBA", (size, size), bg)
    draw = ImageDraw.Draw(img)
    draw_emblem(img, draw, size, with_corners=(not transparent))
    out_path = out_path or OUT_DIR / f"emblem-{size}{'-transparent' if transparent else ''}.png"
    img.save(out_path, "PNG", optimize=True)
    print(f"  wrote {out_path.relative_to(ROOT)}  ({img.size[0]}×{img.size[1]})")


def render_social(width=1280, height=640):
    """GitHub repo social preview — emblem on left, room for text on right.
    Even if we don't add text here, this is the recommended 1280×640
    OG-card size that GH/Twitter scale cleanly."""
    img = Image.new("RGBA", (width, height), PAPER)
    draw = ImageDraw.Draw(img)
    # Emblem at left third, ~540px square.
    emblem_size = 540
    overlay = Image.new("RGBA", (emblem_size, emblem_size), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(overlay)
    draw_emblem(overlay, d2, emblem_size, with_corners=False)
    img.paste(overlay,
              (int(width * 0.085), int((height - emblem_size) / 2)),
              overlay)
    # Right-side title block.
    font_title  = load_font(first_existing(FONT_BOLD_CANDIDATES), 64)
    font_sub    = load_font(first_existing(FONT_REG_CANDIDATES),  26)
    font_meta   = load_font(first_existing(FONT_REG_CANDIDATES),  20)
    tx = int(width * 0.50)
    draw.text((tx, 220), "PURSUE", font=font_title, fill=INK_BLACK)
    draw.text((tx, 295), "OPEN ATLAS",   font=font_title, fill=INK_BLACK)
    draw.text((tx, 380), "U.S. Dept. of War · UAP Release 01",
              font=font_sub, fill=(68, 64, 58, 255))
    draw.text((tx, 415), "4,153 declassified pages · CC0",
              font=font_meta, fill=(106, 100, 90, 255))
    out_path = OUT_DIR / "emblem-social-1280x640.png"
    img.save(out_path, "PNG", optimize=True)
    print(f"  wrote {out_path.relative_to(ROOT)}  ({width}×{height})")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"rendering emblem variants to {OUT_DIR}/")
    render_avatar(256)
    render_avatar(512)
    render_avatar(1024)
    render_avatar(512, transparent=True)
    render_social()
    print("\ndone.")


if __name__ == "__main__":
    main()
