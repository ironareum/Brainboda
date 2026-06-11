"""
Step 0 (optional): Download free BGM from Pixabay Music API.

Downloads cinematic/ambient music tracks into config/bgm/{segment}/ folders.
Run once manually (or periodically) to refresh the BGM pool.

Pixabay Music API: https://pixabay.com/api/?media_type=music
License: Pixabay Content License — free for commercial use, no attribution required.

Usage:
    python pipeline/00_fetch_bgm.py
    python pipeline/00_fetch_bgm.py --segment facts --count 5
    python pipeline/00_fetch_bgm.py --query "cinematic ambient" --segment hook
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
from config.channel import LOGS_DIR, PIXABAY_API_KEY

os.makedirs(LOGS_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"00_fetch_bgm_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", PIXABAY_API_KEY)

# Queries per segment — cinematic/ambient works well for psychology content
_SEGMENT_QUERIES = {
    "hook":  ["cinematic dramatic", "epic orchestral intro", "suspense tension music"],
    "facts": ["cinematic ambient", "documentary background music", "calm cinematic instrumental"],
    "outro": ["cinematic outro", "peaceful ambient music", "inspirational ending"],
}

_MIN_DURATION_S = 60   # reject tracks shorter than 60s
_MAX_DURATION_S = 600  # reject tracks longer than 10min


def _extract_music_url(hit: dict) -> str | None:
    """Try all known field paths for the audio download URL."""
    # Direct audio field (newer API)
    audio = hit.get("audio")
    if isinstance(audio, dict):
        for k in ("mp3", "url", "download"):
            if audio.get(k):
                return audio[k]
    # Flat fields
    for key in ("audioURL", "audio_url", "musicURL", "previewURL", "largeImageURL", "webformatURL"):
        if hit.get(key):
            return hit[key]
    return None


def fetch_pixabay_music(query: str, n: int = 10) -> list[dict]:
    """Search Pixabay Music API, return list of {url, title, duration} dicts."""
    if not PIXABAY_KEY or PIXABAY_KEY == "YOUR_PIXABAY_API_KEY":
        log.error("PIXABAY_API_KEY not configured — set it in config/channel.py or environment")
        return []
    try:
        url = "https://pixabay.com/api/"
        params = {
            "key": PIXABAY_KEY,
            "q": query,
            "media_type": "music",
            "per_page": min(n + 5, 20),
            "order": "popular",
        }
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", [])
            if hits:
                log.debug("Sample hit keys: %s", list(hits[0].keys()))
                log.debug("Sample hit: %s", json.dumps(hits[0], indent=2)[:500])
            results = []
            for h in hits:
                audio_url = _extract_music_url(h)
                duration = h.get("duration", 0)
                title = h.get("tags", query)[:50]
                if not audio_url:
                    log.debug("  No audio URL in hit: %s", list(h.keys()))
                    continue
                # Accept any duration > 0; skip only truly short clips (jingles < 30s)
                if duration > 0 and duration < 30:
                    log.debug("  Skipped (too short, %ds): %s", duration, title)
                    continue
                results.append({"url": audio_url, "title": title, "duration": duration})
            log.info("  Pixabay music '%s': %d usable (from %d hits)", query, len(results), len(hits))
            return results[:n]
        log.warning("Pixabay music API returned HTTP %d for '%s'", resp.status_code, query)
        log.debug("Response: %s", resp.text[:300])
    except Exception as exc:
        log.warning("Pixabay music fetch failed: %s", exc)
    return []


def download_audio(url: str, dest_path: str) -> bool:
    try:
        resp = requests.get(url, timeout=60, stream=True,
                            headers={"User-Agent": "Brainboda/1.0"})
        if resp.status_code == 200:
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            size = os.path.getsize(dest_path)
            if size > 50_000:
                log.info("  Downloaded: %s (%.1f KB)", os.path.basename(dest_path), size / 1024)
                return True
            os.remove(dest_path)
            log.debug("  Too small (%.1f KB), skipped: %s", size / 1024, url)
        else:
            log.warning("  HTTP %d: %s", resp.status_code, url)
    except Exception as exc:
        log.warning("  Download failed: %s — %s", url, exc)
    return False


def fetch_bgm_for_segment(segment: str, queries: list[str], target: int, bgm_dir: str) -> int:
    """Download up to `target` tracks into bgm_dir. Returns count of new files."""
    os.makedirs(bgm_dir, exist_ok=True)
    existing = glob.glob(os.path.join(bgm_dir, "*.mp3"))
    if len(existing) >= target:
        log.info("  [skip] %s — %d tracks already present", segment, len(existing))
        return 0

    needed = target - len(existing)
    log.info("  %s: need %d more tracks (have %d)", segment, needed, len(existing))

    downloaded = 0
    seen_urls = set()
    for query in queries:
        if downloaded >= needed:
            break
        tracks = fetch_pixabay_music(query, n=needed * 2)
        for track in tracks:
            if downloaded >= needed:
                break
            url = track["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            idx = len(existing) + downloaded + 1
            dest = os.path.join(bgm_dir, f"bgm_{segment}_{idx:02d}.mp3")
            if download_audio(url, dest):
                downloaded += 1

    log.info("  %s: downloaded %d new tracks", segment, downloaded)
    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Download BGM tracks from Pixabay Music")
    parser.add_argument("--segment", choices=["hook", "facts", "outro", "all"], default="all")
    parser.add_argument("--count", type=int, default=5, help="Target tracks per segment")
    parser.add_argument("--query", type=str, default=None, help="Override search query")
    args = parser.parse_args()

    log.info("=== 00_fetch_bgm.py START ===")

    bgm_base = os.path.join(_BASE_DIR, "config", "bgm")
    segments = ["hook", "facts", "outro"] if args.segment == "all" else [args.segment]

    total_new = 0
    for seg in segments:
        queries = [args.query] if args.query else _SEGMENT_QUERIES.get(seg, ["cinematic ambient"])
        bgm_dir = os.path.join(bgm_base, seg)
        log.info("Fetching BGM for segment: %s | queries: %s", seg, queries)
        n = fetch_bgm_for_segment(seg, queries, args.count, bgm_dir)
        total_new += n

    log.info("=== 00_fetch_bgm.py DONE — %d new tracks downloaded ===", total_new)

    print(f"\n{'='*60}")
    for seg in segments:
        bgm_dir = os.path.join(bgm_base, seg)
        files = glob.glob(os.path.join(bgm_dir, "*.mp3"))
        print(f"  {seg:<8} — {len(files)} tracks in {bgm_dir}")
    print(f"{'='*60}")
    print()
    print("  NOTE: Pixabay Music may require a separate API endpoint.")
    print("  If 0 tracks downloaded, check the API response in the log.")
    print("  You can also manually place .mp3 files in config/bgm/{segment}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
