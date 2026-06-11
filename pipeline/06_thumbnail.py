"""
Step 6: Generate YouTube thumbnail (1280x720) using Pillow.

4 rotating layout styles (selected by hash of title):
  A - Centered text + yellow underline + badge  (current classic)
  B - Huge single keyword top + image fill      (EVERYTHING style)
  C - Left-aligned bold + vertical accent bar   (NIHILISM style)
  D - Dramatic centered quote / statement       (You shouldn't be alive style)

Usage:
    python pipeline/06_thumbnail.py --script output/script_main_xxx.json
"""

import argparse
import glob
import hashlib
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

os.makedirs(LOGS_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"06_thumbnail_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BOLD_FONTS = [
    os.path.join(_BASE_DIR, "config", "fonts", "Poppins-Bold.ttf"),
    "/Library/Fonts/Poppins-Bold.ttf",
    "~/Library/Fonts/Poppins-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REGULAR_FONTS = [
    os.path.join(_BASE_DIR, "config", "fonts", "Poppins-SemiBold.ttf"),
    os.path.join(_BASE_DIR, "config", "fonts", "Poppins-Regular.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import numpy as np
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    log.error("Pillow not installed.")


# ── helpers ───────────────────────────────────────────────────────────────────

def find_font(paths, size):
    for p in paths:
        expanded = os.path.expanduser(p)
        if os.path.exists(expanded):
            try:
                return ImageFont.truetype(expanded, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def crop_fill(img, width, height):
    iw, ih = img.size
    scale = max(width / iw, height / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - width) // 2
    top = (nh - height) // 2
    return img.crop((left, top, left + width, top + height))


def find_best_bg_image(run_dir: str) -> str | None:
    if run_dir:
        visuals_dir = os.path.join(run_dir, "visuals")
        images = sorted(glob.glob(os.path.join(visuals_dir, "*/*.jpg")))
        images_by_size = sorted(images, key=lambda p: os.path.getsize(p), reverse=True)
        if images_by_size:
            return images_by_size[0]
    return None


def wrap_text(text: str, draw, font, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        try:
            bb = draw.textbbox((0, 0), test, font=font)
            w = bb[2] - bb[0]
        except Exception:
            w = len(test) * 30
        if w <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def text_w(draw, text, font):
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0], bb[3] - bb[1]
    except Exception:
        return len(text) * int(font.size * 0.6), int(font.size)


def draw_shadow_text(draw, xy, text, font, fill=(255, 255, 255),
                     shadow=(0, 0, 0), shadow_offsets=((5, 5), (4, 4), (-2, -2))):
    x, y = xy
    for dx, dy in shadow_offsets:
        draw.text((x + dx, y + dy), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def darken_bg(img_rgb, factor=0.45):
    arr = np.array(img_rgb, dtype=np.float32)
    arr = (arr * factor).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def add_vignette(img, strength=160):
    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(H):
        t = y / H
        alpha = int(strength * abs(t - 0.5) * 2)
        od.line([(0, y), (W, y)], fill=(0, 0, 0, min(alpha, 220)))
    base = img.convert("RGBA")
    return Image.alpha_composite(base, overlay).convert("RGB")


def draw_badge(draw, W, facts_badge, bold_fonts, accent=(255, 215, 0)):
    badge_font_size = 60
    badge_font = find_font(bold_fonts, badge_font_size)
    try:
        bb = draw.textbbox((0, 0), facts_badge, font=badge_font)
        btw, bth = bb[2] - bb[0], bb[3] - bb[1]
    except Exception:
        btw, bth = len(facts_badge) * 34, badge_font_size
    pad_x, pad_y = 28, 22
    bx1 = W - btw - pad_x * 2 - 30
    by1 = 30
    bx2 = W - 30
    by2 = by1 + bth + pad_y * 2
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=14, fill=accent)
    # Use dark text for light accents, white for dark accents
    text_color = (0, 0, 0) if sum(accent) > 380 else (255, 255, 255)
    draw.text((bx1 + pad_x, by1 + pad_y), facts_badge, font=badge_font, fill=text_color)


# ── Layout A: Centered classic ────────────────────────────────────────────────
# White bold text centered, yellow underline, badge top-right

def layout_a(img, draw, W, H, hook_text, facts_badge, accent=(255, 215, 0)):
    max_text_w = int(W * 0.85)
    font_size = 130
    font = find_font(BOLD_FONTS, font_size)
    lines = []
    for _ in range(15):
        font = find_font(BOLD_FONTS, font_size)
        lines = wrap_text(hook_text, draw, font, max_text_w)
        if len(lines) <= 2:
            break
        font_size = int(font_size * 0.88)

    line_h = int(font_size * 1.18)
    total_text_h = len(lines) * line_h
    text_top = (H - total_text_h) // 2 - 20

    for i, line in enumerate(lines):
        y = text_top + i * line_h
        tw, _ = text_w(draw, line, font)
        x = (W - tw) // 2
        draw_shadow_text(draw, (x, y), line, font)

    accent_y = text_top + total_text_h + 18
    bar_w = int(W * 0.55)
    bar_x = (W - bar_w) // 2
    draw.rectangle([bar_x, accent_y, bar_x + bar_w, accent_y + 6], fill=accent)

    if facts_badge:
        draw_badge(draw, W, facts_badge, BOLD_FONTS, accent=accent)


# ── Layout B: Huge keyword top + subtitle ─────────────────────────────────────
# One big word dominates top half (EVERYTHING style), subtitle small below

def layout_b(img, draw, W, H, hook_text, facts_badge, accent=(255, 215, 0)):
    words = hook_text.split()
    # Use longest word as hero, rest as subtitle
    keyword = max(words, key=len).upper()
    subtitle_words = [w for w in words if w.lower() != keyword.lower()]
    subtitle = " ".join(subtitle_words).upper() if subtitle_words else ""

    # Hero word — fill top 55% width
    font_size = 200
    for _ in range(20):
        font = find_font(BOLD_FONTS, font_size)
        tw, _ = text_w(draw, keyword, font)
        if tw <= int(W * 0.92):
            break
        font_size = int(font_size * 0.92)

    # Draw hero word — vertically centered accounting for subtitle
    sub_font_size = 58
    sub_font = find_font(BOLD_FONTS, sub_font_size)
    subtitle_words_list = wrap_text(subtitle, draw, sub_font, int(W * 0.80)) if subtitle else []
    subtitle_h = len(subtitle_words_list) * int(sub_font_size * 1.2) + 20 if subtitle_words_list else 0

    tw, th = text_w(draw, keyword, font)
    total_block_h = th + subtitle_h
    y = (H - total_block_h) // 2 - 20  # vertically center the whole block
    x = (W - tw) // 2
    draw_shadow_text(draw, (x, y), keyword, font,
                     shadow_offsets=((6, 6), (5, 5), (-3, -3)))

    # Subtitle
    if subtitle_words_list:
        sub_y = y + th + 20
        for line in subtitle_words_list:
            stw, _ = text_w(draw, line, sub_font)
            sx = (W - stw) // 2
            draw_shadow_text(draw, (sx, sub_y), line, sub_font,
                             fill=accent, shadow_offsets=((3, 3),))
            sub_y += int(sub_font_size * 1.2)

    if facts_badge:
        draw_badge(draw, W, facts_badge, BOLD_FONTS, accent=accent)


# ── Layout C: Left-aligned + vertical accent bar ──────────────────────────────
# Bold text flush left, yellow vertical bar on left edge (NIHILISM style)

def layout_c(img, draw, W, H, hook_text, facts_badge, accent=(255, 215, 0)):
    bar_x = 60
    bar_w = 8
    text_x = bar_x + bar_w + 28
    max_text_w = int(W * 0.62)

    font_size = 120
    font = find_font(BOLD_FONTS, font_size)
    lines = []
    for _ in range(15):
        font = find_font(BOLD_FONTS, font_size)
        lines = wrap_text(hook_text.upper(), draw, font, max_text_w)
        if len(lines) <= 3:
            break
        font_size = int(font_size * 0.88)

    line_h = int(font_size * 1.15)
    total_text_h = len(lines) * line_h
    text_top = (H - total_text_h) // 2

    for i, line in enumerate(lines):
        y = text_top + i * line_h
        draw_shadow_text(draw, (text_x, y), line, font,
                         shadow_offsets=((4, 4), (3, 3)))

    # Accent vertical bar
    bar_top = text_top - 10
    bar_bot = text_top + total_text_h + 10
    draw.rectangle([bar_x, bar_top, bar_x + bar_w, bar_bot], fill=accent)

    if facts_badge:
        draw_badge(draw, W, facts_badge, BOLD_FONTS, accent=accent)


# ── Layout D: Dramatic centered statement ────────────────────────────────────
# Smaller font, sentence-case, no shouting — cinematic quote style

def layout_d(img, draw, W, H, hook_text, facts_badge, accent=(255, 215, 0)):
    max_text_w = int(W * 0.78)
    font_size = 100
    font = find_font(BOLD_FONTS, font_size)
    lines = []
    for _ in range(15):
        font = find_font(BOLD_FONTS, font_size)
        lines = wrap_text(hook_text, draw, font, max_text_w)
        if len(lines) <= 3:
            break
        font_size = int(font_size * 0.88)

    line_h = int(font_size * 1.22)
    total_text_h = len(lines) * line_h
    # Slightly lower than center for dramatic feel
    text_top = (H - total_text_h) // 2 + 30

    for i, line in enumerate(lines):
        y = text_top + i * line_h
        tw, _ = text_w(draw, line, font)
        x = (W - tw) // 2
        draw_shadow_text(draw, (x, y), line, font,
                         shadow_offsets=((5, 5), (4, 4), (-1, -1)))

    # Thin accent dot-line above text
    dot_y = text_top - 28
    dot_x = (W - 120) // 2
    draw.rectangle([dot_x, dot_y, dot_x + 120, dot_y + 4], fill=accent)

    if facts_badge:
        draw_badge(draw, W, facts_badge, BOLD_FONTS, accent=accent)


# ── Color palette (accent colors per layout/video) ────────────────────────────
# Each layout gets a distinct accent color; cycles based on title hash

ACCENT_COLORS = [
    (255, 215, 0),    # yellow  (classic)
    (0, 220, 200),    # cyan-teal
    (255, 80, 120),   # hot pink
    (100, 200, 255),  # sky blue
    (180, 255, 100),  # lime green
    (255, 150, 30),   # orange
]


def pick_accent(title: str) -> tuple:
    h = int(hashlib.md5(title.encode()).hexdigest(), 16)
    return ACCENT_COLORS[h % len(ACCENT_COLORS)]


# ── Layout dispatcher ─────────────────────────────────────────────────────────

LAYOUTS = [layout_a, layout_b, layout_c, layout_d]
LAYOUT_NAMES = ["A (centered classic)", "B (huge keyword)", "C (left-align)", "D (dramatic quote)"]


def pick_layout(title: str):
    idx = int(hashlib.md5(title.encode()).hexdigest(), 16) % len(LAYOUTS)
    return idx, LAYOUTS[idx]


# ── Main generator ────────────────────────────────────────────────────────────

def generate_thumbnail(script: dict, run_dir: str, output_path: str) -> bool:
    if not PILLOW_AVAILABLE:
        log.error("Pillow required")
        return False

    W, H = THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT

    thumbnail_hook = script.get("thumbnail_hook", "")
    title = script.get("title", "Brainboda Psychology Facts")
    n_facts = len(script.get("facts", []))
    video_type = script.get("type", "main")

    hook_text = thumbnail_hook or title
    facts_badge = f"{n_facts} FACTS" if n_facts and video_type == "main" else ""

    layout_idx, layout_fn = pick_layout(title)
    accent = pick_accent(title)
    log.info("Thumbnail layout: %s | accent: %s", LAYOUT_NAMES[layout_idx], accent)

    # ── Background ────────────────────────────────────────────────────────────
    bg_path = find_best_bg_image(run_dir)
    if bg_path:
        log.info("Background image: %s", bg_path)
        bg = Image.open(bg_path).convert("RGB")
        bg = crop_fill(bg, W, H)
        bg = darken_bg(bg, factor=0.40)
    else:
        bg = Image.new("RGB", (W, H), (10, 10, 26))

    img = add_vignette(bg)
    draw = ImageDraw.Draw(img)

    layout_fn(img, draw, W, H, hook_text, facts_badge, accent=accent)

    img.save(output_path, "JPEG", quality=95)
    log.info("Thumbnail saved: %s (%.1f KB)", output_path, os.path.getsize(output_path) / 1024)
    return True


def find_latest_script(output_dir: str, video_type: str = None) -> str | None:
    pattern = os.path.join(output_dir, "script_*.json")
    if video_type:
        pattern = os.path.join(output_dir, f"script_{video_type}_*.json")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def main():
    parser = argparse.ArgumentParser(description="Generate YouTube thumbnail")
    parser.add_argument("--script", type=str, default=None)
    parser.add_argument("--run-dir", type=str, default=None)
    args = parser.parse_args()

    log.info("=== 06_thumbnail.py START ===")

    script_path = args.script
    if not script_path and args.run_dir:
        candidate = os.path.join(args.run_dir, "script.json")
        if os.path.exists(candidate):
            script_path = candidate
    if not script_path:
        script_path = find_latest_script(OUTPUT_DIR)
    if not script_path or not os.path.exists(script_path):
        log.error("No script JSON found.")
        sys.exit(1)
    log.info("Script: %s", script_path)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    run_dir = args.run_dir or os.path.dirname(os.path.abspath(script_path))

    if args.run_dir:
        output_path = os.path.join(args.run_dir, "thumbnail.jpg")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(OUTPUT_DIR, f"thumbnail_{timestamp}.jpg")

    success = generate_thumbnail(script, run_dir, output_path)
    log.info("=== 06_thumbnail.py DONE ===")

    if success:
        print(f"\n{'='*60}")
        print(f"  Thumbnail: {output_path}")
        print(f"  Hook text: {script.get('thumbnail_hook', '(no hook)')}")
        print(f"{'='*60}")
        return output_path
    else:
        log.error("Thumbnail generation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
