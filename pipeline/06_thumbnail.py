"""
Step 6: Generate YouTube thumbnail (1280x720) using Pillow.

Design:
- Background: best image from visuals/ (darkened overlay)
- Large bold thumbnail_hook text centered (auto-sized)
- N FACTS badge (top-right)
- BRAINBODA watermark bottom-right

Usage:
    python pipeline/06_thumbnail.py --script output/script_main_xxx.json
"""

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
    """Pick the best background image from visuals/ in the run dir."""
    if run_dir:
        visuals_dir = os.path.join(run_dir, "visuals")
        images = sorted(glob.glob(os.path.join(visuals_dir, "*/*.jpg")))
        # Prefer non-placeholder images (larger files)
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

    # ── Background ────────────────────────────────────────────────────────────
    bg_path = find_best_bg_image(run_dir)
    if bg_path:
        log.info("Background image: %s", bg_path)
        bg = Image.open(bg_path).convert("RGB")
        bg = crop_fill(bg, W, H)
        # Darken with numpy
        arr = np.array(bg, dtype=np.float32)
        arr = (arr * 0.45).clip(0, 255).astype(np.uint8)
        bg = Image.fromarray(arr)
    else:
        log.info("No visuals found — using gradient background")
        bg = Image.new("RGB", (W, H), (10, 10, 26))
        d_bg = ImageDraw.Draw(bg)
        for y in range(H):
            t = y / H
            c = (int(10 + t * 16), int(10 + t * 16), int(26 + t * 32))
            d_bg.line([(0, y), (W, y)], fill=c)

    img = bg.copy()
    draw = ImageDraw.Draw(img)

    # ── Dark gradient overlay (bottom fade) ───────────────────────────────────
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(H):
        t = y / H
        # Dark at edges, lighter in middle
        alpha = int(120 + 80 * abs(t - 0.5) * 2)
        od.line([(0, y), (W, y)], fill=(0, 0, 0, min(alpha, 200)))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay)
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Hook text (main) — auto-size font to fit 2 lines max ─────────────────
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
    # Position: center of frame, slightly above middle
    text_top = (H - total_text_h) // 2 - 20

    for i, line in enumerate(lines):
        y = text_top + i * line_h
        try:
            bb = draw.textbbox((0, 0), line, font=font)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(line) * int(font_size * 0.6)
        x = (W - tw) // 2
        # Strong drop shadow
        for dx, dy in [(5, 5), (4, 4), (-2, -2)]:
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    # ── Accent underline ──────────────────────────────────────────────────────
    accent_y = text_top + total_text_h + 18
    bar_w = int(W * 0.55)
    bar_x = (W - bar_w) // 2
    draw.rectangle([bar_x, accent_y, bar_x + bar_w, accent_y + 6], fill=(255, 215, 0))

    # ── N FACTS badge (top-right) ─────────────────────────────────────────────
    if facts_badge:
        badge_font_size = 52
        badge_font = find_font(BOLD_FONTS, badge_font_size)
        try:
            bb = draw.textbbox((0, 0), facts_badge, font=badge_font)
            btw, bth = bb[2] - bb[0], bb[3] - bb[1]
        except Exception:
            btw, bth = len(facts_badge) * 30, badge_font_size
        pad = 20
        bx1 = W - btw - pad * 2 - 30
        by1 = 30
        bx2 = W - 30
        by2 = by1 + bth + pad
        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=12, fill=(255, 215, 0))
        draw.text((bx1 + pad, by1 + pad // 2), facts_badge, font=badge_font, fill=(0, 0, 0))

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
