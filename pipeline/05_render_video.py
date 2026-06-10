"""
Step 5: Render video from audio segments + visual images.

Layout:
  - Full-bleed background image (crop-fill, no black bars)
  - Heading: semi-transparent strip overlaid ON the image (top)
  - Narration: subtitle-style, synced to audio timing (bottom)
  - Hook/Outro: gradient background

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

os.makedirs(LOGS_DIR, exist_ok=True)
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
VISUALS_DIR = os.path.join(OUTPUT_DIR, "visuals")

log_file = os.path.join(LOGS_DIR, f"05_render_video_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── ffmpeg binary ─────────────────────────────────────────────────────────────

def _find_ffmpeg():
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"

FFMPEG_BIN = _find_ffmpeg()
log.info("ffmpeg: %s", FFMPEG_BIN)

# ── optional imports ──────────────────────────────────────────────────────────

try:
    try:
        from moviepy.editor import (
            AudioFileClip, CompositeVideoClip, ImageClip, concatenate_videoclips,
        )
        from moviepy.audio.AudioClip import CompositeAudioClip
        from moviepy.video.VideoClip import VideoClip
    except ImportError:
        from moviepy import (
            AudioFileClip, CompositeVideoClip, ImageClip, concatenate_videoclips,
            CompositeAudioClip, VideoClip,
        )
    MOVIEPY_AVAILABLE = True
    log.info("MoviePy available")
except ImportError:
    MOVIEPY_AVAILABLE = False
    log.warning("MoviePy not available — using ffmpeg renderer")

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import numpy as np
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    log.warning("Pillow/numpy not available")

# ── fonts ─────────────────────────────────────────────────────────────────────

BOLD_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REGULAR_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

def find_font(paths, size):
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

# ── image helpers ─────────────────────────────────────────────────────────────

def crop_fill(img: "Image.Image", width: int, height: int) -> "Image.Image":
    """Crop-fill: scale image to fill target size, then center-crop. No black bars."""
    iw, ih = img.size
    scale = max(width / iw, height / ih)
    new_w, new_h = int(iw * scale), int(ih * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return img.crop((left, top, left + width, top + height))


def overlay_rgba(base: "Image.Image", overlay: "Image.Image") -> "Image.Image":
    """Composite an RGBA overlay onto an RGB base image."""
    base_rgba = base.convert("RGBA")
    result = Image.alpha_composite(base_rgba, overlay)
    return result.convert("RGB")


def make_gradient_bg(width: int, height: int) -> "Image.Image":
    """Dark blue gradient background for hook/outro."""
    import numpy as np
    top_color = np.array([10, 10, 30], dtype=np.float32)
    bot_color = np.array([20, 20, 60], dtype=np.float32)
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        t = y / height
        arr[y] = (top_color * (1 - t) + bot_color * t).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def get_images_for_segment(segment_id: str):
    seg_dir = os.path.join(VISUALS_DIR, segment_id)
    if not os.path.isdir(seg_dir):
        return []
    imgs = sorted(
        glob.glob(os.path.join(seg_dir, "*.jpg")) +
        glob.glob(os.path.join(seg_dir, "*.png"))
    )
    return imgs


def get_audio_duration(audio_path: str) -> float:
    try:
        ffprobe = FFMPEG_BIN.replace("ffmpeg", "ffprobe")
        import shutil
        if not os.path.exists(ffprobe):
            ffprobe = shutil.which("ffprobe") or ffprobe
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, timeout=15,
        )
        val = r.stdout.strip()
        if val:
            return float(val)
    except Exception:
        pass
    return 30.0

# ── text / subtitle helpers ───────────────────────────────────────────────────

def wrap_words(text: str, max_chars: int = 50):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def get_subtitle_chunk(narration: str, t: float, duration: float, chunk_size: int = 8) -> str:
    """Return the subtitle text to display at time t (word-group sync)."""
    words = narration.split()
    if not words:
        return ""
    total_words = len(words)
    # How many words should be visible per second (based on 150 wpm)
    wpm = 150
    words_per_sec = wpm / 60
    word_idx = int(t * words_per_sec)
    word_idx = min(word_idx, total_words - 1)
    # Show a chunk of words around current position
    start = max(0, word_idx - chunk_size // 2)
    end = min(total_words, start + chunk_size)
    return " ".join(words[start:end])

# ── frame renderer ────────────────────────────────────────────────────────────

def render_frame(
    base_img: "Image.Image",
    heading: str,
    subtitle: str,
    width: int,
    height: int,
    is_hook_outro: bool = False,
) -> "np.ndarray":
    """
    Render one frame:
    - Full-bleed base image
    - Heading: semi-transparent dark strip overlaid at top
    - Subtitle: semi-transparent dark strip at bottom
    """
    # ── base ──
    frame = crop_fill(base_img.copy(), width, height)

    # ── heading strip (top) ──
    font_h_size = max(52, height // 16)
    font_s_size = max(36, height // 22)
    font_heading = find_font(BOLD_FONTS, font_h_size)
    font_sub = find_font(REGULAR_FONTS, font_s_size)

    pad = 24
    h_lines = wrap_words(heading, max_chars=40)
    line_h = font_h_size + 14
    strip_h = len(h_lines) * line_h + pad * 2

    # Build transparent heading overlay
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # Gradient strip: more opaque at top, fades down
    for y in range(strip_h):
        alpha = int(180 * (1 - y / strip_h * 0.3))
        d.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    y = pad
    for line in h_lines:
        try:
            bbox = d.textbbox((0, 0), line, font=font_heading)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(line) * (font_h_size // 2)
        x = (width - tw) // 2
        # Shadow
        d.text((x + 3, y + 3), line, font=font_heading, fill=(0, 0, 0, 160))
        # Text
        d.text((x, y), line, font=font_heading, fill=(255, 255, 255, 255))
        y += line_h

    frame = overlay_rgba(frame, overlay)

    # ── subtitle strip (bottom) ──
    if subtitle:
        sub_lines = wrap_words(subtitle, max_chars=55)[-3:]  # max 3 lines
        s_line_h = font_s_size + 10
        sub_strip_h = len(sub_lines) * s_line_h + pad * 2
        sub_y_start = height - sub_strip_h

        sub_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub_overlay)
        # Strip background
        for y_off in range(sub_strip_h):
            alpha = int(170 * (y_off / sub_strip_h * 0.4 + 0.6))
            sd.line([(0, sub_y_start + y_off), (width, sub_y_start + y_off)],
                    fill=(0, 0, 0, alpha))

        y = sub_y_start + pad
        for line in sub_lines:
            try:
                bbox = sd.textbbox((0, 0), line, font=font_sub)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(line) * (font_s_size // 2)
            x = (width - tw) // 2
            sd.text((x + 2, y + 2), line, font=font_sub, fill=(0, 0, 0, 140))
            sd.text((x, y), line, font=font_sub, fill=(230, 230, 230, 255))
            y += s_line_h

        frame = overlay_rgba(frame, sub_overlay)

    return np.array(frame)

# ── MoviePy clip builder ──────────────────────────────────────────────────────

def build_clip(
    audio_path: str,
    segment_id: str,
    heading: str,
    narration: str,
    width: int,
    height: int,
    is_hook_outro: bool = False,
):
    """Build a MoviePy clip with synced subtitles and Ken Burns effect."""
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment(segment_id)

    # Load base image
    if images:
        base_img = Image.open(images[0]).convert("RGB")
    elif is_hook_outro:
        base_img = make_gradient_bg(width, height)
    else:
        # Try to grab any available image
        all_imgs = glob.glob(os.path.join(VISUALS_DIR, "*/*.jpg"))
        if all_imgs:
            base_img = Image.open(all_imgs[0]).convert("RGB")
        else:
            base_img = make_gradient_bg(width, height)

    # Pre-render base frame (full-bleed crop)
    base_cropped = crop_fill(base_img, width, height)

    def make_frame(t):
        # Ken Burns: slow zoom 1.0 → 1.05
        scale = 1.0 + 0.05 * (t / max(duration, 1))
        iw, ih = base_cropped.size
        new_w = int(iw * scale)
        new_h = int(ih * scale)
        zoomed = base_cropped.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - width) // 2
        top = (new_h - height) // 2
        frame_img = zoomed.crop((left, top, left + width, top + height))

        # Subtitle: sync to time
        subtitle = get_subtitle_chunk(narration, t, duration)

        return render_frame(frame_img, heading, subtitle, width, height, is_hook_outro)

    try:
        video_clip = VideoClip(make_frame, duration=duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)

        try:
            video_clip = video_clip.with_duration(min_dur)
            audio_clip = audio_clip.subclipped(0, min_dur)
            return video_clip.with_audio(audio_clip)
        except AttributeError:
            video_clip = video_clip.set_duration(min_dur)
            audio_clip = audio_clip.subclip(0, min_dur)
            return video_clip.set_audio(audio_clip)
    except Exception as exc:
        log.error("build_clip failed for %s: %s", segment_id, exc)
        return None

# ── MoviePy renderer ──────────────────────────────────────────────────────────

def render_with_moviepy(segments, output_path, width, height, bgm_path):
    log.info("Using MoviePy renderer")
    clips = []
    for seg in segments:
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            log.warning("Skipping %s — no audio", seg.get("id"))
            continue
        log.info("  Building clip: %s", seg.get("heading", seg.get("id")))
        clip = build_clip(
            audio_path, seg["id"], seg["heading"], seg["narration"],
            width, height, seg.get("is_hook_outro", False),
        )
        if clip:
            clips.append(clip)

    if not clips:
        log.error("No clips built")
        return False

    try:
        final = concatenate_videoclips(clips, method="compose")

        if bgm_path and os.path.exists(bgm_path):
            try:
                bgm = AudioFileClip(bgm_path).volumex(0.08)
                try:
                    bgm = bgm.with_duration(final.duration)
                except AttributeError:
                    if bgm.duration < final.duration:
                        from moviepy.audio.fx.audio_loop import audio_loop
                        bgm = audio_loop(bgm, duration=final.duration)
                    else:
                        bgm = bgm.subclip(0, final.duration)
                mixed = CompositeAudioClip([final.audio, bgm])
                try:
                    final = final.with_audio(mixed)
                except AttributeError:
                    final = final.set_audio(mixed)
                log.info("BGM mixed")
            except Exception as exc:
                log.warning("BGM mix failed: %s", exc)

        final.write_videofile(
            output_path, fps=FPS, codec="libx264", audio_codec="aac",
            temp_audiofile=output_path + ".tmp_audio.m4a",
            remove_temp=True, logger=None,
        )
        return os.path.exists(output_path)
    except Exception as exc:
        log.error("MoviePy write_videofile failed: %s", exc)
        return False

# ── ffmpeg fallback renderer ──────────────────────────────────────────────────

def render_with_ffmpeg(segments, output_path, width, height, bgm_path):
    """Pure ffmpeg fallback: pre-renders frames with Pillow, then muxes."""
    log.info("Using ffmpeg fallback renderer")
    tmpdir = tempfile.mkdtemp()
    segment_videos = []

    for i, seg in enumerate(segments):
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            continue

        duration = get_audio_duration(audio_path)
        images = get_images_for_segment(seg["id"])
        heading = seg.get("heading", "")
        narration = seg.get("narration", "")
        is_ho = seg.get("is_hook_outro", False)

        if images:
            base_img = Image.open(images[0]).convert("RGB")
        elif is_ho:
            base_img = make_gradient_bg(width, height)
        else:
            all_imgs = glob.glob(os.path.join(VISUALS_DIR, "*/*.jpg"))
            base_img = Image.open(all_imgs[0]).convert("RGB") if all_imgs else make_gradient_bg(width, height)

        # Render a static frame (mid-point subtitle)
        mid_subtitle = get_subtitle_chunk(narration, duration / 2, duration)
        if PILLOW_AVAILABLE:
            frame_arr = render_frame(crop_fill(base_img, width, height), heading, mid_subtitle, width, height, is_ho)
            frame_img = Image.fromarray(frame_arr)
        else:
            frame_img = crop_fill(base_img, width, height)

        frame_path = os.path.join(tmpdir, f"frame_{i:03d}.jpg")
        frame_img.save(frame_path, "JPEG", quality=90)

        seg_out = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
        cmd = [
            FFMPEG_BIN, "-y",
            "-loop", "1", "-i", frame_path,
            "-i", audio_path,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            "-vf", f"scale={width}:{height}",
            "-r", str(FPS), seg_out,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode == 0 and os.path.exists(seg_out):
            segment_videos.append(seg_out)
            log.info("  Rendered segment %d", i)
        else:
            log.error("  Segment %d failed: %s", i, r.stderr.decode()[-300:])

    if not segment_videos:
        return False

    concat_list = os.path.join(tmpdir, "concat.txt")
    with open(concat_list, "w") as f:
        for sv in segment_videos:
            f.write(f"file '{os.path.abspath(sv)}'\n")

    concat_out = os.path.join(tmpdir, "concat.mp4")
    r = subprocess.run(
        [FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", concat_out],
        capture_output=True, timeout=600,
    )
    if r.returncode != 0:
        log.error("Concat failed: %s", r.stderr.decode()[-300:])
        return False

    if bgm_path and os.path.exists(bgm_path):
        r2 = subprocess.run([
            FFMPEG_BIN, "-y", "-i", concat_out,
            "-stream_loop", "-1", "-i", bgm_path,
            "-filter_complex", "[0:a]volume=1.0[a0];[1:a]volume=0.08[a1];[a0][a1]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", output_path,
        ], capture_output=True, timeout=600)
        if r2.returncode == 0:
            return True
        log.warning("BGM mix failed, skipping")

    import shutil
    shutil.copy2(concat_out, output_path)
    return os.path.exists(output_path)

# ── script finder ─────────────────────────────────────────────────────────────

def find_latest_script(output_dir, video_type=None):
    pattern = os.path.join(output_dir, f"script_{video_type}_*.json" if video_type else "script_*.json")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=str, default=None)
    parser.add_argument("--test", action="store_true", help="Render only 2 facts")
    args = parser.parse_args()

    log.info("=== 05_render_video.py START ===")

    script_path = args.script or find_latest_script(OUTPUT_DIR)
    if not script_path or not os.path.exists(script_path):
        log.error("No script JSON found.")
        sys.exit(1)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    video_type = script.get("type", "main")
    is_short = (video_type == "short")
    width = SHORT_WIDTH if is_short else VIDEO_WIDTH
    height = SHORT_HEIGHT if is_short else VIDEO_HEIGHT

    facts = script.get("facts", [])
    if args.test:
        facts = facts[:2]
        log.info("TEST mode — rendering %d facts only", len(facts))

    segments = []

    hook_audio = os.path.join(AUDIO_DIR, "hook.mp3")
    if os.path.exists(hook_audio):
        segments.append({
            "id": "hook",
            "audio": hook_audio,
            "heading": "Brainboda",
            "narration": script.get("hook", ""),
            "is_hook_outro": True,
        })

    for fact in facts:
        n = fact["n"]
        audio = os.path.join(AUDIO_DIR, f"fact_{n:02d}.mp3")
        if os.path.exists(audio):
            segments.append({
                "id": fact["id"],
                "audio": audio,
                "heading": f"#{n}  {fact.get('heading', '')}",
                "narration": fact.get("narration", ""),
                "is_hook_outro": False,
            })

    outro_audio = os.path.join(AUDIO_DIR, "outro.mp3")
    if os.path.exists(outro_audio):
        segments.append({
            "id": "outro",
            "audio": outro_audio,
            "heading": "Subscribe to Brainboda",
            "narration": script.get("outro", ""),
            "is_hook_outro": True,
        })

    if not segments:
        log.error("No audio segments found — run 03_tts.py first")
        sys.exit(1)

    log.info("Segments: %d", len(segments))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(OUTPUT_DIR, f"video_{video_type}_{timestamp}.mp4")

    # Skip if non-test video already exists
    if not args.test:
        existing = glob.glob(os.path.join(OUTPUT_DIR, f"video_{video_type}_*.mp4"))
        if existing:
            latest = max(existing, key=os.path.getmtime)
            log.info("Video already exists: %s — delete it to re-render", latest)
            print(f"\nVideo already exists: {latest}")
            return latest

    bgm_path = os.path.join(OUTPUT_DIR, "bgm.mp3")
    if not os.path.exists(bgm_path):
        bgm_path = None

    success = False
    if MOVIEPY_AVAILABLE and PILLOW_AVAILABLE:
        try:
            success = render_with_moviepy(segments, output_path, width, height, bgm_path)
        except Exception as exc:
            log.warning("MoviePy failed: %s — falling back to ffmpeg", exc)

    if not success:
        success = render_with_ffmpeg(segments, output_path, width, height, bgm_path)

    log.info("=== 05_render_video.py DONE ===")

    if success:
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"\n{'='*60}\n  Video: {output_path}\n  Size: {size_mb:.1f} MB\n{'='*60}")
    else:
        log.error("Rendering failed")
        sys.exit(1)

    return output_path


if __name__ == "__main__":
    main()
