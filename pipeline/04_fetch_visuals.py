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
import random
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

# ── Used URL tracking ─────────────────────────────────────────────────────────

_USED_URLS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "used_image_urls.json"
)

def _load_used_urls() -> set:
    try:
        with open(_USED_URLS_PATH, encoding="utf-8") as f:
            return set(json.load(f).get("urls", []))
    except Exception:
        return set()

def _save_used_urls(used: set):
    os.makedirs(os.path.dirname(_USED_URLS_PATH), exist_ok=True)
    try:
        with open(_USED_URLS_PATH, "w", encoding="utf-8") as f:
            json.dump({"urls": sorted(used)}, f, indent=2)
    except Exception as exc:
        log.warning("Could not save used URLs: %s", exc)


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

def fetch_pixabay(query: str, n: int = 10, page: int = 1,
                  orientation: str = None) -> list[str]:
    """Return up to n image URLs from Pixabay.
    orientation: None (any) | 'vertical' | 'horizontal'
    """
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
            "page": page,
            "safesearch": "true",
            "min_width": 720,
            "order": "popular",
        }
        if orientation:
            params["orientation"] = orientation
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            urls = [h.get("largeImageURL") or h.get("webformatURL") for h in hits if h]
            return [u for u in urls if u][:n + 5]
        log.warning("Pixabay returned HTTP %d", resp.status_code)
    except Exception as exc:
        log.warning("Pixabay fetch failed: %s", exc)
    return []


def fetch_pexels(query: str, n: int = 10, page: int = 1,
                 orientation: str = None) -> list[str]:
    """Return up to n image URLs from Pexels.
    orientation: None (any) | 'portrait' | 'landscape'
    """
    if not PEXELS_KEY or PEXELS_KEY == "YOUR_PEXELS_API_KEY":
        log.debug("Pexels key not configured, skipping")
        return []
    try:
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_KEY}
        params = {"query": query, "per_page": min(n + 8, 30), "page": page, "size": "large"}
        if orientation:
            params["orientation"] = orientation  # portrait | landscape
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


def _collect_urls(queries: list[str], target: int, used_urls: set = None,
                  orientation: str = None) -> list[str]:
    """Try multiple queries across Pixabay + Pexels with random page offset.
    orientation: None=any, 'vertical'/'portrait'=shorts, 'horizontal'/'landscape'=main
    Skips URLs already present in used_urls to avoid cross-run repetition.
    """
    if used_urls is None:
        used_urls = set()
    # Map to per-API orientation names
    pix_orient = "vertical" if orientation == "vertical" else ("horizontal" if orientation == "horizontal" else None)
    pex_orient = "portrait" if orientation == "vertical" else ("landscape" if orientation == "horizontal" else None)

    seen, urls = set(), []
    page = random.randint(1, 4)
    for query in queries:
        if len(urls) >= target + 5:
            break
        for u in fetch_pixabay(query, n=target, page=page, orientation=pix_orient):
            if u not in seen and u not in used_urls:
                seen.add(u)
                urls.append(u)
        for u in fetch_pexels(query, n=target, page=page, orientation=pex_orient):
            if u not in seen and u not in used_urls:
                seen.add(u)
                urls.append(u)
        if len(urls) < target:
            next_page = (page % 5) + 1
            for u in fetch_pixabay(query, n=target, page=next_page, orientation=pix_orient):
                if u not in seen and u not in used_urls:
                    seen.add(u)
                    urls.append(u)
            for u in fetch_pexels(query, n=target, page=next_page, orientation=pex_orient):
                if u not in seen and u not in used_urls:
                    seen.add(u)
                    urls.append(u)
    return urls


def _build_queries(keywords: list, heading: str) -> list[str]:
    """Build specific search queries from fact keywords and heading."""
    kw = [k.strip() for k in keywords if k.strip()][:4]
    heading_words = [w for w in heading.split() if len(w) > 3]

    queries = []

    # Primary: full heading (most specific)
    queries.append(heading)

    # Secondary: top 2 keywords combined
    if len(kw) >= 2:
        queries.append(f"{kw[0]} {kw[1]}")
    elif kw:
        queries.append(kw[0])

    # Tertiary: heading + contextual modifier
    if heading_words:
        queries.append(f"{heading_words[0]} science")
        queries.append(f"{heading_words[0]} behavior")

    # Extra: keyword + visual modifier
    if kw:
        queries.append(f"{kw[0]} human")

    return queries[:5]  # cap at 5 queries


def fetch_images_for_fact(fact_id: str, keywords: list, heading: str, color_idx: int = 0,
                          visuals_dir: str = None, target: int = 5,
                          used_urls: set = None, orientation: str = None) -> list[str]:
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

    queries = _build_queries(keywords, heading)
    log.info("  Fetching images for: %s | queries: %s", fact_id, queries[:3])

    candidate_urls = _collect_urls(queries, target * 3, used_urls=used_urls or set(),
                                   orientation=orientation)

    saved_paths = list(existing)
    newly_downloaded = []
    for url in candidate_urls:
        if len(saved_paths) >= target:
            break
        dest = os.path.join(fact_dir, f"img_{len(saved_paths)+1:02d}.jpg")
        if download_image(url, dest):
            saved_paths.append(dest)
            newly_downloaded.append(url)

    if not saved_paths:
        log.error("  All sources failed for %s — no images downloaded", fact_id)
    else:
        log.info("  %s → %d images", fact_id, len(saved_paths))

    return saved_paths, newly_downloaded


def fetch_hook_images(visuals_dir: str, target: int = 6, used_urls: set = None,
                      orientation: str = None) -> tuple:
    """Download generic psychology images for the hook segment."""
    hook_dir = os.path.join(visuals_dir, "_hook")
    existing = sorted(glob.glob(os.path.join(hook_dir, "*.jpg")))
    if len(existing) >= target:
        log.info("  [skip] _hook — %d images already downloaded", len(existing))
        return existing, []

    os.makedirs(hook_dir, exist_ok=True)
    candidate_urls = _collect_urls(_HOOK_QUERIES, target * 2, used_urls=used_urls or set(),
                                   orientation=orientation)
    saved = list(existing)
    newly_downloaded = []
    for url in candidate_urls:
        if len(saved) >= target:
            break
        dest = os.path.join(hook_dir, f"img_{len(saved)+1:02d}.jpg")
        if download_image(url, dest):
            saved.append(dest)
            newly_downloaded.append(url)

    log.info("  _hook → %d images", len(saved))
    return saved, newly_downloaded


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
    video_type = script.get("type", "main")
    log.info("Facts to process: %d | video type: %s", len(facts), video_type)

    # Shorts prefer portrait orientation; main videos prefer landscape
    orientation = "vertical" if video_type == "short" else "horizontal"
    log.info("Image orientation preference: %s", orientation)

    # Load previously used URLs to avoid re-downloading the same images
    used_urls = _load_used_urls()
    log.info("Previously used image URLs: %d", len(used_urls))
    newly_used: set = set()

    all_paths: dict[str, list] = {}

    # Fetch hook images (separate pool, generic psychology visuals)
    hook_paths, hook_new = fetch_hook_images(visuals_dir, target=6, used_urls=used_urls,
                                             orientation=orientation)
    if not hook_paths:
        log.error("No hook images fetched — check API keys or network. Aborting.")
        sys.exit(1)
    all_paths["_hook"] = hook_paths
    newly_used.update(hook_new)

    all_paths_facts: dict[str, list] = {}
    for i, fact in enumerate(facts):
        fact_id = fact["id"]
        keywords = fact.get("search_keywords", [])
        heading = fact.get("heading", fact_id)
        result = fetch_images_for_fact(fact_id, keywords, heading, color_idx=i,
                                       visuals_dir=visuals_dir, target=5,
                                       used_urls=used_urls | newly_used,
                                       orientation=orientation)
        paths, fact_new = result
        all_paths_facts[fact_id] = paths
        all_paths[fact_id] = paths
        newly_used.update(fact_new)
        if not paths:
            log.error("No images for %s — check API keys or network. Aborting.", fact_id)
            sys.exit(1)

    # Persist used URLs for next run
    _save_used_urls(used_urls | newly_used)
    log.info("Saved %d used URLs total", len(used_urls | newly_used))

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
