"""
Step 4: Fetch visual images for each fact segment.

Downloads 2-3 images per fact from Pixabay/Pexels.
Falls back to solid color placeholder images (Pillow) when APIs fail.

Output: output/visuals/{fact_id}/ — JPEG images

Usage:
    python pipeline/04_fetch_visuals.py --script output/script_main_xxx.json
"""

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
_DEFAULT_VISUALS_DIR = os.path.join(OUTPUT_DIR, "visuals")
# VISUALS_DIR is set after args parsed (may be run-dir based)
VISUALS_DIR = _DEFAULT_VISUALS_DIR

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


def _is_too_bloody(path: str) -> bool:
    """Return True if image looks like gore/biological tissue (blood or raw flesh)."""
    if not PILLOW_AVAILABLE:
        return False
    try:
        import numpy as np
        img = Image.open(path).convert("RGB").resize((120, 68))
        arr = np.array(img, dtype=np.float32)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

        # Pure blood-red: R high, G+B both low
        blood_mask = (r > 140) & (g < 80) & (b < 80) & ((r - g) > 80)
        blood_ratio = blood_mask.sum() / blood_mask.size

        # Raw flesh / dissected tissue: pinkish-beige, R dominates, G mid, B low-mid
        # Catches exposed brain tissue, surgical photos, organ shots
        flesh_mask = (r > 160) & (g > 80) & (g < 165) & (b < 140) & ((r - g) > 35) & ((r - b) > 50)
        flesh_ratio = flesh_mask.sum() / flesh_mask.size

        if blood_ratio > 0.12:
            log.info("    Rejected (blood-red %.0f%%): %s", blood_ratio * 100, os.path.basename(path))
            return True
        if flesh_ratio > 0.30:
            log.info("    Rejected (raw flesh %.0f%%): %s", flesh_ratio * 100, os.path.basename(path))
            return True
    except Exception:
        pass
    return False


def download_image(url: str, dest_path: str) -> bool:
    """Download an image from url to dest_path. Returns True on success."""
    try:
        resp = requests.get(url, headers=HEADERS_REQUESTS, timeout=20, stream=True)
        if resp.status_code == 200:
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            size = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
            if size >= _MIN_IMAGE_BYTES:
                if _is_too_bloody(dest_path):
                    os.remove(dest_path)
                    return False
                log.info("    Downloaded: %s (%.1f KB)", os.path.basename(dest_path), size / 1024)
                return True
            if os.path.exists(dest_path):
                os.remove(dest_path)
            log.debug("    Skipped (too small, %.1f KB): %s", size / 1024, url)
        log.warning("    HTTP %d for %s", resp.status_code, url)
        return False
    except Exception as exc:
        log.warning("    Download failed %s: %s", url, exc)
        return False


_MIN_IMAGE_BYTES = 40_000  # reject images smaller than 40 KB (watermarks/icons)

def fetch_pixabay(query: str, n: int = 10) -> list[str]:
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
            "per_page": min(n + 8, 30),
            "safesearch": "true",
            "min_width": 1000,
            "order": "popular",
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            urls = [h.get("largeImageURL") or h.get("webformatURL") for h in hits if h]
            return [u for u in urls if u][:n + 5]
        log.warning("Pixabay returned HTTP %d", resp.status_code)
    except Exception as exc:
        log.warning("Pixabay fetch failed: %s", exc)
    return []


def fetch_pexels(query: str, n: int = 10) -> list[str]:
    """Return up to n image URLs from Pexels."""
    if not PEXELS_KEY or PEXELS_KEY == "YOUR_PEXELS_API_KEY":
        log.debug("Pexels key not configured, skipping")
        return []
    try:
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_KEY}
        params = {"query": query, "per_page": min(n + 8, 30), "size": "large"}
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            photos = resp.json().get("photos", [])
            urls = [p["src"].get("large2x") or p["src"].get("large") for p in photos if p.get("src")]
            return [u for u in urls if u][:n + 5]
        log.warning("Pexels returned HTTP %d", resp.status_code)
    except Exception as exc:
        log.warning("Pexels fetch failed: %s", exc)
    return []


# Generic psychology/mind queries used for hook images (not fact-specific)
_HOOK_QUERIES = [
    "human mind abstract",
    "psychology thought concept",
    "neuroscience brain illustration",
    "mental focus meditation",
    "thinking person silhouette",
]


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


def _collect_urls(queries: list[str], target: int) -> list[str]:
    """Try multiple queries across Pixabay + Pexels, return deduplicated URL list."""
    seen, urls = set(), []
    for query in queries:
        if len(urls) >= target + 5:
            break
        for u in fetch_pixabay(query, n=target):
            if u not in seen:
                seen.add(u)
                urls.append(u)
        for u in fetch_pexels(query, n=target):
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def fetch_images_for_fact(fact_id: str, keywords: list, heading: str, color_idx: int = 0,
                          visuals_dir: str = None, target: int = 10) -> list[str]:
    """Download images for a fact into visuals/{fact_id}/. Returns list of saved paths.

    img_01.jpg  — reserved for the title card frame (not used in narration slides)
    img_02+     — used during narration (cycling through)
    """
    base_dir = visuals_dir or VISUALS_DIR
    fact_dir = os.path.join(base_dir, fact_id)

    existing = sorted(glob.glob(os.path.join(fact_dir, "*.jpg")))
    if len(existing) >= target:
        log.info("  [skip] %s — %d images already downloaded", fact_id, len(existing))
        return existing

    os.makedirs(fact_dir, exist_ok=True)

    # Build multiple search queries for variety
    kw = keywords[:3] if keywords else []
    primary = " ".join(kw) if kw else heading
    secondary = (kw[0] + " concept abstract") if kw else (heading + " concept")
    tertiary = (kw[0] + " psychology human") if kw else "psychology human mind"
    queries = [primary, secondary, tertiary]
    log.info("  Fetching images for: %s (queries: %s)", fact_id, queries[:2])

    candidate_urls = _collect_urls(queries, target * 2)

    saved_paths = list(existing)  # keep any already-downloaded
    for url in candidate_urls:
        if len(saved_paths) >= target:
            break
        dest = os.path.join(fact_dir, f"img_{len(saved_paths)+1:02d}.jpg")
        if download_image(url, dest):
            saved_paths.append(dest)

    if not saved_paths:
        log.error("  All sources failed for %s — no images downloaded", fact_id)
    else:
        log.info("  %s → %d images", fact_id, len(saved_paths))

    return saved_paths


def fetch_hook_images(visuals_dir: str, target: int = 6) -> list[str]:
    """Download generic psychology images for the hook segment."""
    hook_dir = os.path.join(visuals_dir, "_hook")
    existing = sorted(glob.glob(os.path.join(hook_dir, "*.jpg")))
    if len(existing) >= target:
        log.info("  [skip] _hook — %d images already downloaded", len(existing))
        return existing

    os.makedirs(hook_dir, exist_ok=True)
    candidate_urls = _collect_urls(_HOOK_QUERIES, target * 2)
    saved = list(existing)
    for url in candidate_urls:
        if len(saved) >= target:
            break
        dest = os.path.join(hook_dir, f"img_{len(saved)+1:02d}.jpg")
        if download_image(url, dest):
            saved.append(dest)

    log.info("  _hook → %d images", len(saved))
    return saved


def find_latest_script(output_dir: str, video_type: str = None) -> str | None:
    pattern = os.path.join(output_dir, "script_*.json")
    if video_type:
        pattern = os.path.join(output_dir, f"script_{video_type}_*.json")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def main():
    parser = argparse.ArgumentParser(description="Fetch visual images for each fact")
    parser.add_argument("--script", type=str, default=None)
    parser.add_argument("--run-dir", type=str, default=None,
                        help="Run output directory. Visuals go to {run-dir}/visuals/")
    args = parser.parse_args()

    log.info("=== 04_fetch_visuals.py START ===")

    # Resolve visuals dir
    visuals_dir = os.path.join(args.run_dir, "visuals") if args.run_dir else _DEFAULT_VISUALS_DIR
    os.makedirs(visuals_dir, exist_ok=True)

    # Resolve script path
    script_path = args.script
    if not script_path and args.run_dir:
        candidate = os.path.join(args.run_dir, "script.json")
        if os.path.exists(candidate):
            script_path = candidate
    if not script_path:
        script_path = find_latest_script(OUTPUT_DIR)
    if not script_path or not os.path.exists(script_path):
        log.error("No script JSON found. Run 02_build_script.py first.")
        sys.exit(1)
    log.info("Script: %s", script_path)
    log.info("Visuals dir: %s", visuals_dir)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    facts = script.get("facts", [])
    log.info("Facts to process: %d", len(facts))

    # Fetch hook images (separate pool, generic psychology visuals)
    hook_paths = fetch_hook_images(visuals_dir, target=6)
    if not hook_paths:
        log.error("No hook images fetched — check API keys or network. Aborting.")
        sys.exit(1)
    all_paths["_hook"] = hook_paths

    all_paths_facts: dict[str, list] = {}
    for i, fact in enumerate(facts):
        fact_id = fact["id"]
        keywords = fact.get("search_keywords", [])
        heading = fact.get("heading", fact_id)
        paths = fetch_images_for_fact(fact_id, keywords, heading, color_idx=i,
                                      visuals_dir=visuals_dir, target=10)
        all_paths_facts[fact_id] = paths
        all_paths[fact_id] = paths
        if not paths:
            log.error("No images for %s — check API keys or network. Aborting.", fact_id)
            sys.exit(1)

    log.info("=== 04_fetch_visuals.py DONE ===")

    total = sum(len(v) for v in all_paths_facts.values())
    print(f"\n{'='*60}")
    print(f"  Hook images : {len(hook_paths)}")
    print(f"  Fact images : {total} across {len(all_paths_facts)} facts")
    print(f"  Output dir  : {visuals_dir}")
    print(f"{'='*60}")
    for fact_id, paths in all_paths_facts.items():
        print(f"  {fact_id[:30]:<30} {len(paths)} images")

    return all_paths


if __name__ == "__main__":
    main()
