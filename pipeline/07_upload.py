"""
Step 7: Upload video + thumbnail to YouTube via Data API v3.

OAuth: loads client_secrets.json (repo root or config/), stores token in config/youtube_token.json.
Resumable upload with title/description/tags from script JSON.

Usage:
    python pipeline/07_upload.py --video output/video_xxx.mp4 \
        --thumbnail output/thumbnail_xxx.jpg \
        --script output/script_xxx.json
    python pipeline/07_upload.py ... --test   # uploads as private
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
    BASE_DIR,
    LOGS_DIR,
    OUTPUT_DIR,
    VIDEO_CATEGORY_ID,
    YOUTUBE_PLAYLIST_ID,
)

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"07_upload_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Google API imports ────────────────────────────────────────────────────────

try:
    import google.oauth2.credentials
    import google_auth_oauthlib.flow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request
    import pickle
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    log.warning("google-api-python-client or google-auth-oauthlib not installed.")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

PLAYLIST_NAME = "How Your Mind Works"

CONFIG_DIR = os.path.join(BASE_DIR, "config")
TOKEN_PATH = os.path.join(CONFIG_DIR, "youtube_token.json")


def find_client_secrets() -> str | None:
    """Search for client_secrets.json in repo root and config/."""
    for p in [
        os.path.join(BASE_DIR, "client_secrets.json"),
        os.path.join(CONFIG_DIR, "client_secrets.json"),
    ]:
        if os.path.exists(p):
            return p
    return None


def get_authenticated_service():
    """Build authenticated YouTube service using OAuth2."""
    if not GOOGLE_API_AVAILABLE:
        raise ImportError("Google API libraries not installed")

    creds = None

    # Load existing token
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, "r") as f:
                token_data = json.load(f)
            creds = google.oauth2.credentials.Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=token_data.get("client_id"),
                client_secret=token_data.get("client_secret"),
                scopes=token_data.get("scopes", SCOPES),
            )
        except Exception as exc:
            log.warning("Could not load token: %s", exc)
            creds = None

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            log.info("Token refreshed")
        except Exception as exc:
            log.warning("Token refresh failed: %s", exc)
            creds = None

    # Full OAuth flow if needed
    if not creds or not creds.valid:
        secrets_path = find_client_secrets()
        if not secrets_path:
            raise FileNotFoundError(
                "client_secrets.json not found in repo root or config/. "
                "Download it from Google Cloud Console."
            )
        flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
            secrets_path, SCOPES
        )
        creds = flow.run_local_server(port=0)
        _save_token(creds)
        log.info("OAuth flow completed, token saved to %s", TOKEN_PATH)

    return build("youtube", "v3", credentials=creds)


def _save_token(creds) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }
    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)


def upload_video(
    youtube,
    video_path: str,
    title: str,
    description: str,
    tags: list,
    privacy: str = "public",
) -> str:
    """Upload video with resumable upload. Returns video ID."""
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": VIDEO_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 8,  # 8 MB chunks
    )

    log.info("Starting upload: %s", title)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log.info("  Upload progress: %d%%", pct)

    video_id = response["id"]
    log.info("Upload complete. Video ID: %s", video_id)
    return video_id


def set_thumbnail(youtube, video_id: str, thumbnail_path: str) -> bool:
    """Set thumbnail for an uploaded video."""
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
        ).execute()
        log.info("Thumbnail set for video %s", video_id)
        return True
    except HttpError as exc:
        log.warning("Thumbnail set failed: %s", exc)
        return False


def get_or_create_playlist(youtube, name: str) -> str | None:
    """Return playlist ID matching name, creating it if it doesn't exist."""
    try:
        # Search existing playlists
        resp = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        for item in resp.get("items", []):
            if item["snippet"]["title"].lower() == name.lower():
                pid = item["id"]
                log.info("Found existing playlist '%s': %s", name, pid)
                return pid

        # Create new playlist
        created = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": name, "description": ""},
                "status": {"privacyStatus": "public"},
            },
        ).execute()
        pid = created["id"]
        log.info("Created playlist '%s': %s", name, pid)
        return pid
    except Exception as exc:
        log.warning("Playlist get/create failed: %s", exc)
        return None


def add_to_playlist(youtube, video_id: str, playlist_id: str) -> bool:
    """Add a video to a playlist."""
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        ).execute()
        log.info("Added video %s to playlist %s", video_id, playlist_id)
        return True
    except Exception as exc:
        log.warning("Add to playlist failed: %s", exc)
        return False


def find_latest_script(output_dir: str) -> str | None:
    files = glob.glob(os.path.join(output_dir, "script_*.json"))
    return max(files, key=os.path.getmtime) if files else None


def find_latest_video(output_dir: str) -> str | None:
    files = glob.glob(os.path.join(output_dir, "video_*.mp4"))
    return max(files, key=os.path.getmtime) if files else None


def find_latest_thumbnail(output_dir: str) -> str | None:
    files = glob.glob(os.path.join(output_dir, "thumbnail_*.jpg"))
    return max(files, key=os.path.getmtime) if files else None


def main():
    parser = argparse.ArgumentParser(description="Upload video to YouTube")
    parser.add_argument("--video", type=str, default=None,
                        help="Path to MP4. If omitted, auto-detects latest in output/")
    parser.add_argument("--thumbnail", type=str, default=None,
                        help="Path to thumbnail JPG. If omitted, auto-detects.")
    parser.add_argument("--script", type=str, default=None,
                        help="Script JSON for title/description/tags")
    parser.add_argument("--run-dir", type=str, default=None,
                        help="Run output directory. Auto-detect video/thumbnail/script from run-dir.")
    parser.add_argument("--test", action="store_true",
                        help="Upload as private instead of public")
    args = parser.parse_args()

    log.info("=== 07_upload.py START ===")

    # Resolve paths — run-dir takes precedence for auto-detection
    if args.run_dir:
        script_path = args.script or os.path.join(args.run_dir, "script.json")
        video_path = args.video or os.path.join(args.run_dir, "video.mp4")
        thumbnail_path = args.thumbnail or os.path.join(args.run_dir, "thumbnail.jpg")
        # Fall back to None if files don't exist
        if not os.path.exists(script_path):
            script_path = find_latest_script(OUTPUT_DIR)
        if not os.path.exists(video_path):
            video_path = find_latest_video(OUTPUT_DIR)
        if not os.path.exists(thumbnail_path):
            thumbnail_path = find_latest_thumbnail(OUTPUT_DIR)
    else:
        script_path = args.script or find_latest_script(OUTPUT_DIR)
        video_path = args.video or find_latest_video(OUTPUT_DIR)
        thumbnail_path = args.thumbnail or find_latest_thumbnail(OUTPUT_DIR)

    if not video_path or not os.path.exists(video_path):
        log.error("No video file found. Run 05_render_video.py first.")
        sys.exit(1)

    if not script_path or not os.path.exists(script_path):
        log.error("No script JSON found.")
        sys.exit(1)

    log.info("Video: %s", video_path)
    log.info("Thumbnail: %s", thumbnail_path)
    log.info("Script: %s", script_path)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    title = script.get("title", "Brainboda Psychology Facts")
    description = script.get("description", "")
    tags = script.get("tags", [])
    privacy = "private" if args.test else "public"

    log.info("Title: %s", title)
    log.info("Privacy: %s", privacy)

    if not GOOGLE_API_AVAILABLE:
        log.error("Google API libraries not installed. Run: pip install google-api-python-client google-auth-oauthlib")
        sys.exit(1)

    try:
        youtube = get_authenticated_service()
    except FileNotFoundError as exc:
        log.error("OAuth credentials missing: %s", exc)
        sys.exit(1)
    except Exception as exc:
        log.error("Authentication failed: %s", exc)
        sys.exit(1)

    try:
        video_id = upload_video(youtube, video_path, title, description, tags, privacy)
    except HttpError as exc:
        log.error("Upload HttpError: %s", exc)
        sys.exit(1)
    except Exception as exc:
        log.error("Upload failed: %s", exc)
        sys.exit(1)

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    log.info("Video URL: %s", video_url)

    if thumbnail_path and os.path.exists(thumbnail_path):
        set_thumbnail(youtube, video_id, thumbnail_path)

    # Add to playlist
    if YOUTUBE_PLAYLIST_ID:
        add_to_playlist(youtube, video_id, YOUTUBE_PLAYLIST_ID)

    log.info("=== 07_upload.py DONE ===")

    print(f"\n{'='*60}")
    print(f"  Upload complete!")
    print(f"  YouTube URL: {video_url}")
    print(f"  Playlist:    {PLAYLIST_NAME}")
    print(f"  Privacy:     {privacy}")
    print(f"{'='*60}")

    return video_url


if __name__ == "__main__":
    main()
