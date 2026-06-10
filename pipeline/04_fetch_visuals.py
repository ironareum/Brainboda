"""
Step 4: Fetch visual images for each fact segment.

Downloads 2-3 images per fact from Pixabay/Pexels.
Falls back to solid color placeholder images (Pillow) when APIs fail.

Output: output/visuals/{fact_id}/ — JPEG images

Usage:
    python pipeline/04_fetch_visuals.py --script output/script_main_xxx.json
"""

from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import argparse
import glob
import json
import logging
import os
import sys
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.channel import (
    LOGS_DIR,
    OUTPUT_DIR,
    PIXABAY_API_KEY,
    PEXELS_API_KEY,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
)

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)
VISUALS_DIR = os.path.join(OUTPUT_DIR, "visuals")
os.makedirs(VISUALS_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"04_fetch_visuals_{datetime.now():%Y%m%d_%H%M%S}.log")
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
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    log.warning("Pillow not installed. Placeholder generation disabled.")

# ── API keys — env vars take priority, then config ───────────────────────────

PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", PIXABAY_API_KEY)
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", PEXELS_API_KEY)

PLACEHOLDER_COLORS = [
    "#1a1a3a", "#0a2a4a", "#1a3a1a", "#3a1a1a",
    "#2a2a1a", "#1a2a3a", "#2a1a3a", "#3a2a1a",
]

HEADERS_REQUESTS = {"User-Agent": "Brainboda/1.0"}


def file_exists_nonempty(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


def download_image(url: str, dest_path: str) -> bool:
    """Download an image from url to dest_path. Returns True on success."""
    try:
        resp = requests.get(url, headers=HEADERS_REQUESTS, timeout=20, stream=True)
        if resp.status_code == 200:
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            if file_exists_nonempty(dest_path):
                log.info("    Downloaded: %s (%.1f KB)", os.path.basename(dest_path),
                         os.path.getsize(dest_path) / 1024)
                return True
        log.warning("    HTTP %d for %s", resp.status_code, url)
        return False
    except Exception as exc:
        log.warning("    Download failed %s: %s", url, exc)
        return False


def fetch_pixabay(query: str, n: int = 3) -> List[str]:
    """Return up to n image URLs from Pixabay."""
    if not PIXABAY_KEY or PIXABAY_KEY == "YOUR_PIXABAY_API_KEY":
        log.debug("Pixabay key not configured, skipping")
        return []
    try:
        url = "https://pixabay.com/api/"
        params = {
            "key": PIXABAY_KEY,
            "q": query,
            "image_type": "photo",
            "per_page": n + 2,
            "safesearch": "true",
            "min_width": 800,
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            urls = [h.get("webformatURL") or h.get("largeImageURL") for h in hits[:n] if h]
            return [u for u in urls if u]
        log.warning("Pixabay returned HTTP %d", resp.status_code)
    except Exception as exc:
        log.warning("Pixabay fetch failed: %s", exc)
    return []


def fetch_pexels(query: str, n: int = 3) -> List[str]:
    """Return up to n image URLs from Pexels."""
    if not PEXELS_KEY or PEXELS_KEY == "YOUR_PEXELS_API_KEY":
        log.debug("Pexels key not configured, skipping")
        return []
    try:
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_KEY}
        params = {"query": query, "per_page": n + 2}
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            photos = resp.json().get("photos", [])
            urls = [p["src"].get("large") or p["src"].get("medium") for p in photos[:n] if p.get("src")]
            return [u for u in urls if u]
        log.warning("Pexels returned HTTP %d", resp.status_code)
    except Exception as exc:
        log.warning("Pexels fetch failed: %s", exc)
    return []


def generate_placeholder(dest_path: str, label: str, color_idx: int = 0) -> bool:
    """Generate a solid-color placeholder image with text label."""
    if not PILLOW_AVAILABLE:
        log.error("Pillow not available — cannot generate placeholder")
        return False
    try:
        color = PLACEHOLDER_COLORS[color_idx % len(PLACEHOLDER_COLORS)]
        img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color)
        draw = ImageDraw.Draw(img)

        # Overlay label text
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        except Exception:
            font = ImageFont.load_default()

        text = label[:50]
        # Center text
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (VIDEO_WIDTH - tw) // 2
        y = (VIDEO_HEIGHT - th) // 2
        draw.text((x + 3, y + 3), text, fill="#000000aa", font=font)
        draw.text((x, y), text, fill="#ffffff", font=font)

        img.save(dest_path, "JPEG", quality=85)
        log.info("    Generated placeholder: %s", os.path.basename(dest_path))
        return True
    except Exception as exc:
        log.error("Placeholder generation failed: %s", exc)
        return False


def fetch_images_for_fact(fact_id: str, keywords: list, heading: str, color_idx: int = 0) -> List[str]:
    """Download images for a fact into output/visuals/{fact_id}/. Returns list of saved paths."""
    fact_dir = os.path.join(VISUALS_DIR, fact_id)

    # Check if already downloaded
    existing = glob.glob(os.path.join(fact_dir, "*.jpg"))
    if len(existing) >= 2:
        log.info("  [skip] %s — %d images already downloaded", fact_id, len(existing))
        return existing

    os.makedirs(fact_dir, exist_ok=True)

    query = " ".join(keywords[:3]) if keywords else heading
    log.info("  Fetching images for: %s (query: '%s')", fact_id, query)

    saved_paths = []
    target = 3

    # Try Pixabay first
    pixabay_urls = fetch_pixabay(query, n=target)
    for i, url in enumerate(pixabay_urls):
        if len(saved_paths) >= target:
            break
        dest = os.path.join(fact_dir, f"img_{len(saved_paths)+1:02d}.jpg")
        if download_image(url, dest):
            saved_paths.append(dest)

    # Try Pexels if we still need more
    if len(saved_paths) < 2:
        pexels_urls = fetch_pexels(query, n=target)
        for url in pexels_urls:
            if len(saved_paths) >= target:
                break
            dest = os.path.join(fact_dir, f"img_{len(saved_paths)+1:02d}.jpg")
            if download_image(url, dest):
                saved_paths.append(dest)

    # Generate placeholders if still empty
    if not saved_paths:
        log.info("  Both APIs failed — generating placeholder images for %s", fact_id)
        for i in range(2):
            dest = os.path.join(fact_dir, f"img_{i+1:02d}.jpg")
            if generate_placeholder(dest, heading, color_idx=color_idx + i):
                saved_paths.append(dest)

    return saved_paths


def find_latest_script(output_dir: str, video_type: str = None) -> Optional[str]:
    pattern = os.path.join(output_dir, "script_*.json")
    if video_type:
        pattern = os.path.join(output_dir, f"script_{video_type}_*.json")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def main():
    parser = argparse.ArgumentParser(description="Fetch visual images for each fact")
    parser.add_argument("--script", type=str, default=None)
    args = parser.parse_args()

    log.info("=== 04_fetch_visuals.py START ===")

    script_path = args.script or find_latest_script(OUTPUT_DIR)
    if not script_path or not os.path.exists(script_path):
        log.error("No script JSON found. Run 02_build_script.py first.")
        sys.exit(1)
    log.info("Script: %s", script_path)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    facts = script.get("facts", [])
    log.info("Facts to process: %d", len(facts))

    all_paths: Dict[str, list] = {}
    for i, fact in enumerate(facts):
        fact_id = fact["id"]
        keywords = fact.get("search_keywords", [])
        heading = fact.get("heading", fact_id)
        paths = fetch_images_for_fact(fact_id, keywords, heading, color_idx=i)
        all_paths[fact_id] = paths
        log.info("  %s → %d images", fact_id, len(paths))

    # Hook/outro placeholders
    for segment in [("hook", "Psychology Brain"), ("outro", "Subscribe Brainboda")]:
        seg_id, seg_label = segment
        seg_dir = os.path.join(VISUALS_DIR, seg_id)
        existing = glob.glob(os.path.join(seg_dir, "*.jpg"))
        if not existing:
            os.makedirs(seg_dir, exist_ok=True)
            dest = os.path.join(seg_dir, "img_01.jpg")
            generate_placeholder(dest, seg_label, color_idx=0)

    log.info("=== 04_fetch_visuals.py DONE ===")

    total = sum(len(v) for v in all_paths.values())
    print(f"\n{'='*60}")
    print(f"  Visuals fetched: {total} images across {len(all_paths)} facts")
    print(f"  Output dir: {VISUALS_DIR}")
    print(f"{'='*60}")
    for fact_id, paths in all_paths.items():
        print(f"  {fact_id[:30]:<30} {len(paths)} images")

    return all_paths


if __name__ == "__main__":
    main()
