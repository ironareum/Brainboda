"""
Step 5: Render video from audio segments + visual images.

Produces output/video_{type}_{timestamp}.mp4

For each fact segment:
  1. Load fact MP3 → get duration
  2. Pick images from output/visuals/{fact_id}/
  3. ImageClip with Ken Burns zoom (1.0→1.05)
  4. Text overlay: heading (top) + narration (bottom)
  5. Concatenate hook + facts + outro
  6. Mix BGM if output/bgm.mp3 exists (volume 0.08)
  7. Export h264/aac, fps=30

Usage:
    python pipeline/05_render_video.py --script output/script_main_xxx.json
    python pipeline/05_render_video.py --script output/script_main_xxx.json --test
"""

import argparse
import glob
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.channel import (
    FPS,
    LOGS_DIR,
    OUTPUT_DIR,
    SHORT_HEIGHT,
    SHORT_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
VISUALS_DIR = os.path.join(OUTPUT_DIR, "visuals")

log_file = os.path.join(LOGS_DIR, f"05_render_video_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── FFmpeg binary resolution ──────────────────────────────────────────────────

def _find_ffmpeg() -> str:
    """Return path to ffmpeg binary. Tries system PATH then imageio_ffmpeg bundle."""
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"

FFMPEG_BIN = _find_ffmpeg()
log.info("ffmpeg binary: %s", FFMPEG_BIN)

# ── optional imports ──────────────────────────────────────────────────────────

try:
    # Support both MoviePy v1 (moviepy.editor) and v2 (moviepy)
    try:
        from moviepy.editor import (
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            concatenate_videoclips,
        )
        from moviepy.audio.AudioClip import CompositeAudioClip
    except ImportError:
        from moviepy import (
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            concatenate_videoclips,
            CompositeAudioClip,
        )
    MOVIEPY_AVAILABLE = True
    log.info("MoviePy available")
except ImportError:
    MOVIEPY_AVAILABLE = False
    log.warning("MoviePy not installed — will use ffmpeg-only render path")

try:
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    log.warning("Pillow/numpy not available — text overlays disabled")


# ── font detection ────────────────────────────────────────────────────────────

FONT_SEARCH_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/Arial.ttf",
]

FONT_SMALL_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def find_font(paths: list, size: int):
    """Try to load a font from a list of paths."""
    if not PILLOW_AVAILABLE:
        return None
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


def get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds via ffprobe."""
    try:
        # Use ffprobe co-located with ffmpeg binary
        ffprobe = FFMPEG_BIN.replace("ffmpeg", "ffprobe")
        import shutil
        if not os.path.exists(ffprobe):
            ffprobe = shutil.which("ffprobe") or ffprobe
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, timeout=15
        )
        val = result.stdout.strip()
        if val:
            return float(val)
    except Exception:
        pass
    return 30.0  # fallback


def wrap_text(text: str, max_chars: int = 60) -> list[str]:
    """Word-wrap text into lines."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = current + " " + word if current else word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def create_text_overlay_frame(
    base_image_path: str,
    heading: str,
    narration: str,
    width: int,
    height: int,
) -> "np.ndarray | None":
    """Render a PIL image with text overlay. Returns numpy array or None."""
    if not PILLOW_AVAILABLE:
        return None
    try:
        import numpy as np
        # Load and resize base image
        img = Image.open(base_image_path).convert("RGB")
        img = img.resize((width, height), Image.LANCZOS)
        draw = ImageDraw.Draw(img)

        # --- Heading (top, large bold) ---
        font_heading = find_font(FONT_SEARCH_PATHS, size=max(48, height // 18))
        font_narr = find_font(FONT_SMALL_PATHS, size=max(32, height // 26))

        # Heading background strip (top)
        heading_text = heading[:80]
        pad = 20
        h_lines = wrap_text(heading_text, max_chars=45)
        line_h = (height // 18) + 12
        strip_h = len(h_lines) * line_h + pad * 2
        draw.rectangle([(0, 0), (width, strip_h)], fill=(0, 0, 0, 160))

        y = pad
        for line in h_lines:
            try:
                bbox = draw.textbbox((0, 0), line, font=font_heading)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(line) * 28
            x = (width - tw) // 2
            draw.text((x + 2, y + 2), line, fill=(0, 0, 0), font=font_heading)
            draw.text((x, y), line, fill=(255, 255, 255), font=font_heading)
            y += line_h

        # --- Narration (bottom third) ---
        narr_lines = wrap_text(narration[:300], max_chars=65)[-8:]  # max 8 lines
        narr_line_h = (height // 26) + 8
        narr_strip_h = len(narr_lines) * narr_line_h + pad * 2
        narr_y_start = height - narr_strip_h

        draw.rectangle([(0, narr_y_start), (width, height)], fill=(0, 0, 0, 180))

        y = narr_y_start + pad
        for line in narr_lines:
            try:
                bbox = draw.textbbox((0, 0), line, font=font_narr)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(line) * 18
            x = (width - tw) // 2
            draw.text((x + 1, y + 1), line, fill=(0, 0, 0), font=font_narr)
            draw.text((x, y), line, fill=(220, 220, 220), font=font_narr)
            y += narr_line_h

        return np.array(img)
    except Exception as exc:
        log.warning("Text overlay failed: %s", exc)
        return None


def get_images_for_segment(segment_id: str) -> list[str]:
    """Return list of image paths for a segment, or empty list."""
    seg_dir = os.path.join(VISUALS_DIR, segment_id)
    if not os.path.isdir(seg_dir):
        return []
    imgs = sorted(glob.glob(os.path.join(seg_dir, "*.jpg")) +
                  glob.glob(os.path.join(seg_dir, "*.png")))
    return imgs


def make_fallback_image(width: int, height: int, color: str = "#1a1a3a") -> "np.ndarray":
    """Create a solid-color numpy array as fallback."""
    import numpy as np
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    return np.full((height, width, 3), [r, g, b], dtype=np.uint8)


def build_clip_moviepy(
    audio_path: str,
    segment_id: str,
    heading: str,
    narration: str,
    width: int,
    height: int,
) -> "CompositeVideoClip | None":
    """Build a MoviePy video clip for one segment."""
    if not MOVIEPY_AVAILABLE:
        return None
    try:
        import numpy as np
        duration = get_audio_duration(audio_path)
        images = get_images_for_segment(segment_id)

        if images:
            img_path = images[0]
            frame = create_text_overlay_frame(img_path, heading, narration, width, height)
        else:
            frame = None

        if frame is None:
            frame = make_fallback_image(width, height)

        # Ken Burns: zoom from 1.0 to 1.05
        def make_frame(t):
            scale = 1.0 + 0.05 * (t / max(duration, 1))
            img = Image.fromarray(frame)
            new_w = int(width * scale)
            new_h = int(height * scale)
            img_scaled = img.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - width) // 2
            top = (new_h - height) // 2
            img_cropped = img_scaled.crop((left, top, left + width, top + height))
            return np.array(img_cropped)

        try:
            from moviepy.video.VideoClip import VideoClip
        except ImportError:
            from moviepy import VideoClip

        video_clip = VideoClip(make_frame, duration=duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)

        # MoviePy v2 uses with_duration/with_audio; v1 uses set_duration/set_audio
        try:
            video_clip = video_clip.with_duration(min_dur)
            audio_clip = audio_clip.subclipped(0, min_dur)
            clip = video_clip.with_audio(audio_clip)
        except AttributeError:
            video_clip = video_clip.set_duration(min_dur)
            audio_clip = audio_clip.subclip(0, min_dur)
            clip = video_clip.set_audio(audio_clip)
        return clip
    except Exception as exc:
        log.error("build_clip_moviepy failed for %s: %s", segment_id, exc)
        return None


def render_with_ffmpeg(
    segments: list[dict],
    output_path: str,
    width: int,
    height: int,
    bgm_path: str | None,
) -> bool:
    """Pure ffmpeg fallback renderer. Creates a slideshow video."""
    log.info("Using ffmpeg fallback renderer")
    tmpdir = tempfile.mkdtemp()
    segment_videos = []

    for i, seg in enumerate(segments):
        audio_path = seg.get("audio")
        segment_id = seg.get("id", f"seg_{i}")
        heading = seg.get("heading", "")
        narration = seg.get("narration", "")

        if not audio_path or not os.path.exists(audio_path):
            log.warning("Skipping segment %s — no audio", segment_id)
            continue

        duration = get_audio_duration(audio_path)
        images = get_images_for_segment(segment_id)

        # Build a frame image
        if images and PILLOW_AVAILABLE:
            frame = create_text_overlay_frame(images[0], heading, narration, width, height)
        else:
            frame = None

        if frame is not None:
            import numpy as np
            img = Image.fromarray(frame)
            frame_path = os.path.join(tmpdir, f"frame_{i:03d}.jpg")
            img.save(frame_path, "JPEG", quality=85)
        elif images:
            frame_path = images[0]
        else:
            # Generate solid color frame
            frame_path = os.path.join(tmpdir, f"frame_{i:03d}.jpg")
            if PILLOW_AVAILABLE:
                img = Image.new("RGB", (width, height), "#1a1a3a")
                draw = ImageDraw.Draw(img)
                font = find_font(FONT_SEARCH_PATHS, 48)
                draw.text((50, height // 2), heading[:60], fill="white", font=font)
                img.save(frame_path)
            else:
                # Cannot generate frame, skip
                log.warning("No image and no Pillow for segment %s", segment_id)
                continue

        seg_out = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
        cmd = [
            FFMPEG_BIN, "-y",
            "-loop", "1", "-i", frame_path,
            "-i", audio_path,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,zoompan=z='min(zoom+0.0008,1.05)':d={int(duration*FPS)}:s={width}x{height}",
            "-r", str(FPS),
            seg_out,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and os.path.exists(seg_out):
                segment_videos.append(seg_out)
                log.info("  Rendered segment %d: %s", i, seg_out)
            else:
                # Try simpler version without zoompan
                cmd_simple = [
                    FFMPEG_BIN, "-y",
                    "-loop", "1", "-i", frame_path,
                    "-i", audio_path,
                    "-c:v", "libx264", "-tune", "stillimage",
                    "-c:a", "aac", "-b:a", "128k",
                    "-pix_fmt", "yuv420p",
                    "-t", str(duration),
                    "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                    "-r", str(FPS),
                    seg_out,
                ]
                result2 = subprocess.run(cmd_simple, capture_output=True, timeout=300)
                if result2.returncode == 0 and os.path.exists(seg_out):
                    segment_videos.append(seg_out)
                    log.info("  Rendered segment %d (simple): %s", i, seg_out)
                else:
                    log.error("  Segment %d failed: %s", i, result2.stderr.decode()[-500:])
        except Exception as exc:
            log.error("  Segment %d exception: %s", i, exc)

    if not segment_videos:
        log.error("No segments rendered")
        return False

    # Concatenate segments
    concat_list = os.path.join(tmpdir, "concat.txt")
    with open(concat_list, "w") as f:
        for sv in segment_videos:
            f.write(f"file '{os.path.abspath(sv)}'\n")

    concat_out = os.path.join(tmpdir, "concat.mp4")
    cmd_concat = [
        FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c", "copy", concat_out
    ]
    try:
        result = subprocess.run(cmd_concat, capture_output=True, timeout=600)
        if result.returncode != 0:
            log.error("Concat failed: %s", result.stderr.decode()[-500:])
            return False
    except Exception as exc:
        log.error("Concat exception: %s", exc)
        return False

    # Mix BGM if available
    if bgm_path and os.path.exists(bgm_path):
        cmd_bgm = [
            FFMPEG_BIN, "-y",
            "-i", concat_out,
            "-stream_loop", "-1", "-i", bgm_path,
            "-filter_complex",
            "[0:a]volume=1.0[a0];[1:a]volume=0.08[a1];[a0][a1]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            output_path
        ]
        result = subprocess.run(cmd_bgm, capture_output=True, timeout=600)
        if result.returncode == 0:
            log.info("BGM mixed in successfully")
            return True
        log.warning("BGM mix failed, using video without BGM: %s", result.stderr.decode()[-300:])

    # Just copy to output
    import shutil
    shutil.copy2(concat_out, output_path)
    return os.path.exists(output_path)


def render_with_moviepy(
    segments: list[dict],
    output_path: str,
    width: int,
    height: int,
    bgm_path: str | None,
) -> bool:
    """Render video using MoviePy."""
    log.info("Using MoviePy renderer")
    clips = []
    for seg in segments:
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            log.warning("Skipping segment %s — no audio", seg.get("id"))
            continue
        clip = build_clip_moviepy(
            audio_path, seg.get("id", ""), seg.get("heading", ""),
            seg.get("narration", ""), width, height
        )
        if clip:
            clips.append(clip)

    if not clips:
        log.error("No clips built")
        return False

    try:
        final = concatenate_videoclips(clips, method="compose")

        # Mix BGM
        if bgm_path and os.path.exists(bgm_path):
            try:
                bgm = AudioFileClip(bgm_path).volumex(0.08)
                if bgm.duration < final.duration:
                    from moviepy.audio.fx.audio_loop import audio_loop
                    bgm = audio_loop(bgm, duration=final.duration)
                else:
                    bgm = bgm.subclip(0, final.duration)
                mixed = CompositeAudioClip([final.audio, bgm])
                final = final.set_audio(mixed)
                log.info("BGM mixed via MoviePy")
            except Exception as exc:
                log.warning("BGM mix failed: %s", exc)

        final.write_videofile(
            output_path,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=output_path + ".temp_audio.m4a",
            remove_temp=True,
            logger=None,
        )
        return os.path.exists(output_path)
    except Exception as exc:
        log.error("MoviePy write_videofile failed: %s", exc)
        return False


def find_latest_script(output_dir: str, video_type: str = None) -> str | None:
    pattern = os.path.join(output_dir, "script_*.json")
    if video_type:
        pattern = os.path.join(output_dir, f"script_{video_type}_*.json")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def main():
    parser = argparse.ArgumentParser(description="Render video from audio + visuals")
    parser.add_argument("--script", type=str, default=None)
    parser.add_argument("--test", action="store_true",
                        help="Render only first 2 facts for speed")
    args = parser.parse_args()

    log.info("=== 05_render_video.py START ===")

    script_path = args.script or find_latest_script(OUTPUT_DIR)
    if not script_path or not os.path.exists(script_path):
        log.error("No script JSON found.")
        sys.exit(1)
    log.info("Script: %s", script_path)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    video_type = script.get("type", "main")
    is_short = (video_type == "short")
    width = SHORT_WIDTH if is_short else VIDEO_WIDTH
    height = SHORT_HEIGHT if is_short else VIDEO_HEIGHT

    facts = script.get("facts", [])
    if args.test:
        facts = facts[:2]
        log.info("TEST mode — rendering only %d facts", len(facts))

    # Build segment list
    segments = []

    # Hook
    hook_audio = os.path.join(AUDIO_DIR, "hook.mp3")
    if os.path.exists(hook_audio):
        segments.append({
            "id": "hook",
            "audio": hook_audio,
            "heading": "Welcome to Brainboda",
            "narration": script.get("hook", ""),
        })

    # Facts
    for fact in facts:
        n = fact["n"]
        audio = os.path.join(AUDIO_DIR, f"fact_{n:02d}.mp3")
        if os.path.exists(audio):
            segments.append({
                "id": fact["id"],
                "audio": audio,
                "heading": fact.get("heading", f"Fact {n}"),
                "narration": fact.get("narration", ""),
            })

    # Outro
    outro_audio = os.path.join(AUDIO_DIR, "outro.mp3")
    if os.path.exists(outro_audio):
        segments.append({
            "id": "outro",
            "audio": outro_audio,
            "heading": "Thank you for watching",
            "narration": script.get("outro", ""),
        })

    if not segments:
        log.error("No audio segments found in %s — run 03_tts.py first", AUDIO_DIR)
        sys.exit(1)

    log.info("Segments to render: %d", len(segments))

    # Output path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(OUTPUT_DIR, f"video_{video_type}_{timestamp}.mp4")

    # Check existing
    existing = glob.glob(os.path.join(OUTPUT_DIR, f"video_{video_type}_*.mp4"))
    if existing and not args.test:
        latest = max(existing, key=os.path.getmtime)
        log.info("Video already exists: %s — skipping render", latest)
        print(f"\nVideo already exists: {latest}")
        return latest

    bgm_path = os.path.join(OUTPUT_DIR, "bgm.mp3")
    if not os.path.exists(bgm_path):
        bgm_path = None
        log.info("No bgm.mp3 found — skipping BGM")

    # Render
    success = False
    if MOVIEPY_AVAILABLE and PILLOW_AVAILABLE:
        try:
            success = render_with_moviepy(segments, output_path, width, height, bgm_path)
        except Exception as exc:
            log.warning("MoviePy render failed: %s — falling back to ffmpeg", exc)
            success = False

    if not success:
        success = render_with_ffmpeg(segments, output_path, width, height, bgm_path)

    log.info("=== 05_render_video.py DONE ===")

    if success:
        size_mb = os.path.getsize(output_path) / (1024 * 1024) if os.path.exists(output_path) else 0
        print(f"\n{'='*60}")
        print(f"  Video rendered: {output_path}")
        print(f"  Size: {size_mb:.1f} MB")
        print(f"{'='*60}")
    else:
        log.error("Video rendering failed")
        sys.exit(1)

    return output_path


if __name__ == "__main__":
    main()
