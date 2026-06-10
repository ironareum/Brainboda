"""
Step 6: Generate YouTube thumbnail (1280x720) using Pillow.

Design:
- Dark gradient background (#0a0a1a → #1a1a3a)
- Large bold title (2 lines max, white + #FFD700 accent)
- BRAINBODA watermark bottom-right
- Simple brain icon drawn with ImageDraw
- Drop shadow on text

Usage:
    python pipeline/06_thumbnail.py --script output/script_main_xxx.json
"""

from typing import List, Optional

import argparse
import glob
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.channel import (
    CHANNEL_NAME,
    LOGS_DIR,
    OUTPUT_DIR,
    THUMBNAIL_HEIGHT,
    THUMBNAIL_WIDTH,
)

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"06_thumbnail_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Pillow ────────────────────────────────────────────────────────────────────

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    log.error("Pillow not installed. Cannot generate thumbnail.")

FONT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/Arial.ttf",
]

FONT_REG_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def find_font(paths: list, size: int):
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def draw_gradient(draw: "ImageDraw.Draw", width: int, height: int):
    """Draw a dark vertical gradient."""
    top_color = (10, 10, 26)     # #0a0a1a
    bot_color = (26, 26, 58)     # #1a1a3a
    for y in range(height):
        t = y / height
        r = int(top_color[0] + t * (bot_color[0] - top_color[0]))
        g = int(top_color[1] + t * (bot_color[1] - top_color[1]))
        b = int(top_color[2] + t * (bot_color[2] - top_color[2]))
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def draw_brain_icon(draw: "ImageDraw.Draw", cx: int, cy: int, r: int = 60):
    """Draw a simple geometric brain icon using ellipses."""
    accent = (255, 215, 0)   # gold
    # Outer shape
    draw.ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8],
                 outline=accent, width=4)
    # Center divider
    draw.line([(cx, cy - r * 0.8), (cx, cy + r * 0.8)], fill=accent, width=3)
    # Folds (small arcs)
    for offset in [-r * 0.4, 0, r * 0.4]:
        draw.arc([cx - r * 0.6 + offset, cy - r * 0.3,
                  cx - r * 0.2 + offset, cy + r * 0.3],
                 start=200, end=340, fill=accent, width=2)


def wrap_title(title: str, max_chars: int = 28) -> List[str]:
    """Split title into max 2 lines."""
    words = title.split()
    if len(title) <= max_chars:
        return [title]
    # Try to split near midpoint
    mid = len(words) // 2
    line1 = " ".join(words[:mid])
    line2 = " ".join(words[mid:])
    return [line1, line2]


def find_accent_word(title: str) -> str:
    """Find a key word to highlight in yellow."""
    accent_keywords = [
        "psychology", "brain", "mind", "secrets", "facts", "tricks",
        "shocking", "dark", "hidden", "people", "behavior", "proven",
        "disturbing", "incredible", "mindblowing",
    ]
    words = title.lower().split()
    for kw in accent_keywords:
        if kw in words:
            # Return original-case version
            idx = words.index(kw)
            return title.split()[idx]
    return ""


def generate_thumbnail(title: str, output_path: str) -> bool:
    """Generate a 1280x720 thumbnail. Returns True on success."""
    if not PILLOW_AVAILABLE:
        log.error("Pillow required for thumbnail generation")
        return False

    W, H = THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT

    img = Image.new("RGB", (W, H), (10, 10, 26))
    draw = ImageDraw.Draw(img)

    # Gradient background
    draw_gradient(draw, W, H)

    # Decorative dots / pattern
    for i in range(0, W, 80):
        for j in range(0, H, 80):
            draw.ellipse([i - 1, j - 1, i + 1, j + 1], fill=(255, 255, 255, 20))

    # Brain icon top-left
    draw_brain_icon(draw, cx=120, cy=120, r=70)

    # Title text
    font_title = find_font(FONT_BOLD_PATHS, size=90)
    font_small = find_font(FONT_REG_PATHS, size=36)

    lines = wrap_title(title, max_chars=25)
    accent_word = find_accent_word(title)

    # Calculate total text height
    line_h = 110
    total_h = len(lines) * line_h
    start_y = (H - total_h) // 2 - 20

    for line_idx, line in enumerate(lines):
        y = start_y + line_idx * line_h

        # Render each word, colouring accent word gold
        words_in_line = line.split()
        # Measure full line width for centering
        try:
            bbox = draw.textbbox((0, 0), line, font=font_title)
            total_w = bbox[2] - bbox[0]
        except Exception:
            total_w = len(line) * 50

        x = (W - total_w) // 2

        for word in words_in_line:
            try:
                bbox = draw.textbbox((0, 0), word, font=font_title)
                word_w = bbox[2] - bbox[0]
            except Exception:
                word_w = len(word) * 50

            color = (255, 215, 0) if word.lower() == accent_word.lower() else (255, 255, 255)

            # Drop shadow
            draw.text((x + 4, y + 4), word, fill=(0, 0, 0), font=font_title)
            draw.text((x, y), word, fill=color, font=font_title)

            # Space after word
            try:
                space_bbox = draw.textbbox((0, 0), " ", font=font_title)
                x += word_w + (space_bbox[2] - space_bbox[0])
            except Exception:
                x += word_w + 20

    # Accent bar under title
    bar_y = start_y + len(lines) * line_h + 10
    draw.rectangle([(W // 4, bar_y), (3 * W // 4, bar_y + 4)], fill=(255, 215, 0))

    # BRAINBODA watermark bottom-right
    watermark = CHANNEL_NAME.upper()
    draw.text((W - 20, H - 50), watermark, fill=(180, 180, 180), font=font_small, anchor="ra")

    # Subtle vignette
    vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for i in range(80):
        alpha = int(150 * (i / 80))
        vd.rectangle([i, i, W - i, H - i], outline=(0, 0, 0, alpha))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, vignette)
    img = img.convert("RGB")

    img.save(output_path, "JPEG", quality=95)
    log.info("Thumbnail saved: %s (%.1f KB)", output_path, os.path.getsize(output_path) / 1024)
    return True


def find_latest_script(output_dir: str, video_type: str = None) -> Optional[str]:
    pattern = os.path.join(output_dir, "script_*.json")
    if video_type:
        pattern = os.path.join(output_dir, f"script_{video_type}_*.json")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def main():
    parser = argparse.ArgumentParser(description="Generate YouTube thumbnail")
    parser.add_argument("--script", type=str, default=None)
    args = parser.parse_args()

    log.info("=== 06_thumbnail.py START ===")

    script_path = args.script or find_latest_script(OUTPUT_DIR)
    if not script_path or not os.path.exists(script_path):
        log.error("No script JSON found.")
        sys.exit(1)
    log.info("Script: %s", script_path)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    title = script.get("title", "Brainboda Psychology Facts")
    log.info("Title: %s", title)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(OUTPUT_DIR, f"thumbnail_{timestamp}.jpg")

    # Check existing
    existing = glob.glob(os.path.join(OUTPUT_DIR, "thumbnail_*.jpg"))
    if existing:
        latest = max(existing, key=os.path.getmtime)
        log.info("Thumbnail already exists: %s — skipping", latest)
        print(f"\nThumbnail already exists: {latest}")
        return latest

    success = generate_thumbnail(title, output_path)

    log.info("=== 06_thumbnail.py DONE ===")

    if success:
        print(f"\n{'='*60}")
        print(f"  Thumbnail: {output_path}")
        print(f"  Size: {THUMBNAIL_WIDTH}x{THUMBNAIL_HEIGHT}")
        print(f"{'='*60}")
        return output_path
    else:
        log.error("Thumbnail generation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
