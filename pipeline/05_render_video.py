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
_DEFAULT_AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
_DEFAULT_VISUALS_DIR = os.path.join(OUTPUT_DIR, "visuals")
# These are set dynamically in main() based on --run-dir
AUDIO_DIR = _DEFAULT_AUDIO_DIR
VISUALS_DIR = _DEFAULT_VISUALS_DIR

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

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOLD_FONTS = [
    "/Library/Fonts/Poppins-Bold.ttf",
    "~/Library/Fonts/Poppins-Bold.ttf",
    os.path.join(_BASE_DIR, "config", "fonts", "Poppins-Bold.ttf"),
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REGULAR_FONTS = [
    "/Library/Fonts/Poppins-Regular.ttf",
    "~/Library/Fonts/Poppins-Regular.ttf",
    os.path.join(_BASE_DIR, "config", "fonts", "Poppins-Regular.ttf"),
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


def get_images_for_segment(segment_id: str, visuals_dir: str = None):
    base = visuals_dir or VISUALS_DIR
    seg_dir = os.path.join(base, segment_id)
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

# ── text helpers ─────────────────────────────────────────────────────────────

import re as _re

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


def extract_key_sentence(narration: str) -> str:
    """Extract the most impactful sentence for display."""
    sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
    # Skip "Fact N: Title." opener, use second sentence
    for s in sentences[1:]:
        if len(s) > 30:
            return s[:120]  # cap length
    return sentences[0][:120] if sentences else ""


# ── frame renderer ────────────────────────────────────────────────────────────

def render_frame(
    base_img: "Image.Image",
    heading: str,
    narration: str,
    width: int,
    height: int,
    is_hook_outro: bool = False,
    fact_n: int = None,
    key_insight: str = None,
) -> "np.ndarray":
    """
    Render one frame:
    - Full-bleed background image
    - TOP-LEFT: Fact number badge (circle #N) for fact segments
    - CENTER: Key sentence in a styled rounded-rectangle text box (30-75% vertical)
    - Hook/Outro: channel name centered + key sentence box
    """
    # ── base ──
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    font_h_size = max(52, height // 16)
    font_text_size = max(40, height // 14)
    font_badge_size = max(36, height // 18)
    font_heading = find_font(BOLD_FONTS, font_h_size)
    font_text = find_font(BOLD_FONTS, font_text_size)
    font_badge = find_font(BOLD_FONTS, font_badge_size)

    pad_h = 30
    pad_v = 20

    # ── Fact number badge (top-left circle) ──────────────────────────────────
    if fact_n is not None and not is_hook_outro:
        badge_r = height // 14
        badge_cx = badge_r + 30
        badge_cy = badge_r + 30
        d.ellipse(
            [badge_cx - badge_r, badge_cy - badge_r,
             badge_cx + badge_r, badge_cy + badge_r],
            fill=(0, 0, 0, 180),
        )
        badge_text = f"#{fact_n}"
        try:
            bb = d.textbbox((0, 0), badge_text, font=font_badge)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
        except Exception:
            tw, th = len(badge_text) * (font_badge_size // 2), font_badge_size
        d.text(
            (badge_cx - tw // 2, badge_cy - th // 2),
            badge_text, font=font_badge, fill=(255, 255, 255, 255),
        )

    # ── Hook/Outro: "BRAINBODA" or heading at center-top ─────────────────────
    if is_hook_outro:
        brand_text = heading  # e.g. "Brainboda" or "Subscribe to Brainboda"
        try:
            bb = d.textbbox((0, 0), brand_text, font=font_heading)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(brand_text) * (font_h_size // 2)
        bx = (width - tw) // 2
        by = int(height * 0.12)
        d.text((bx + 3, by + 3), brand_text, font=font_heading, fill=(0, 0, 0, 160))
        d.text((bx, by), brand_text, font=font_heading, fill=(255, 255, 255, 255))

    # ── Key sentence text box (CENTER, 30-75% vertical) ──────────────────────
    key = key_insight or (extract_key_sentence(narration) if narration else heading)
    if not key:
        frame = overlay_rgba(frame, overlay)
        return np.array(frame)

    # Wrap to max 2 lines — key_insight should be ≤8 words so usually 1 line
    box_max_chars = max(25, int(width * 0.040))
    key_lines = wrap_words(key, max_chars=box_max_chars)[:2]

    line_h = font_text_size + 12
    box_inner_h = len(key_lines) * line_h
    box_h = box_inner_h + pad_v * 2
    box_w = width - pad_h * 4

    # Vertical position: centered between 30% and 75% of frame
    zone_top = int(height * 0.30)
    zone_bot = int(height * 0.75)
    zone_center = (zone_top + zone_bot) // 2
    box_top = zone_center - box_h // 2
    box_bot = box_top + box_h
    box_left = pad_h * 2
    box_right = box_left + box_w

    # Rounded rectangle background
    corner_r = 18
    d.rounded_rectangle(
        [box_left, box_top, box_right, box_bot],
        radius=corner_r,
        fill=(0, 0, 0, 170),
    )

    # Text lines centered within box
    y = box_top + pad_v
    for line in key_lines:
        try:
            bb = d.textbbox((0, 0), line, font=font_text)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(line) * (font_text_size // 2)
        x = box_left + (box_w - tw) // 2
        d.text((x + 2, y + 2), line, font=font_text, fill=(0, 0, 0, 140))
        d.text((x, y), line, font=font_text, fill=(255, 255, 255, 255))
        y += line_h

    frame = overlay_rgba(frame, overlay)
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
    fact_n: int = None,
    visuals_dir: str = None,
    key_insight: str = None,
):
    """Build a MoviePy clip with key sentence display and Ken Burns effect."""
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment(segment_id, visuals_dir=visuals_dir)

    # Load base image
    if images:
        base_img = Image.open(images[0]).convert("RGB")
    elif is_hook_outro:
        base_img = make_gradient_bg(width, height)
    else:
        # Try to grab any available image
        base_vdir = visuals_dir or VISUALS_DIR
        all_imgs = glob.glob(os.path.join(base_vdir, "*/*.jpg"))
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

        return render_frame(frame_img, heading, narration, width, height,
                            is_hook_outro, fact_n=fact_n, key_insight=key_insight)

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

def render_with_moviepy(segments, output_path, width, height, bgm_path, visuals_dir=None):
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
            fact_n=seg.get("fact_n"), visuals_dir=visuals_dir,
            key_insight=seg.get("key_insight"),
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

def render_with_ffmpeg(segments, output_path, width, height, bgm_path, visuals_dir=None):
    """Pure ffmpeg fallback: pre-renders frames with Pillow, then muxes."""
    log.info("Using ffmpeg fallback renderer")
    tmpdir = tempfile.mkdtemp()
    segment_videos = []
    base_vdir = visuals_dir or VISUALS_DIR

    for i, seg in enumerate(segments):
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            continue

        duration = get_audio_duration(audio_path)
        images = get_images_for_segment(seg["id"], visuals_dir=visuals_dir)
        heading = seg.get("heading", "")
        narration = seg.get("narration", "")
        is_ho = seg.get("is_hook_outro", False)
        fact_n = seg.get("fact_n")
        key_insight = seg.get("key_insight")

        if images:
            base_img = Image.open(images[0]).convert("RGB")
        elif is_ho:
            base_img = make_gradient_bg(width, height)
        else:
            all_imgs = glob.glob(os.path.join(base_vdir, "*/*.jpg"))
            base_img = Image.open(all_imgs[0]).convert("RGB") if all_imgs else make_gradient_bg(width, height)

        # Render a static frame
        if PILLOW_AVAILABLE:
            frame_arr = render_frame(crop_fill(base_img, width, height), heading, narration,
                                     width, height, is_ho, fact_n=fact_n, key_insight=key_insight)
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
    parser.add_argument("--run-dir", type=str, default=None,
                        help="Run output directory. Read audio/visuals from run-dir, write video to {run-dir}/video.mp4")
    args = parser.parse_args()

    log.info("=== 05_render_video.py START ===")

    # Resolve dirs
    audio_dir = os.path.join(args.run_dir, "audio") if args.run_dir else _DEFAULT_AUDIO_DIR
    visuals_dir = os.path.join(args.run_dir, "visuals") if args.run_dir else _DEFAULT_VISUALS_DIR

    # Resolve script path
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

    hook_audio = os.path.join(audio_dir, "hook.mp3")
    if os.path.exists(hook_audio):
        segments.append({
            "id": "hook",
            "audio": hook_audio,
            "heading": "BRAINBODA",
            "narration": script.get("hook", ""),
            "is_hook_outro": True,
            "fact_n": None,
        })

    for fact in facts:
        n = fact["n"]
        audio = os.path.join(audio_dir, f"fact_{n:02d}.mp3")
        if os.path.exists(audio):
            segments.append({
                "id": fact["id"],
                "audio": audio,
                "heading": fact.get("heading", ""),
                "narration": fact.get("narration", ""),
                "key_insight": fact.get("key_insight"),
                "is_hook_outro": False,
                "fact_n": n,
            })

    outro_audio = os.path.join(audio_dir, "outro.mp3")
    if os.path.exists(outro_audio):
        segments.append({
            "id": "outro",
            "audio": outro_audio,
            "heading": "Subscribe to Brainboda",
            "narration": script.get("outro", ""),
            "is_hook_outro": True,
            "fact_n": None,
        })

    if not segments:
        log.error("No audio segments found — run 03_tts.py first")
        sys.exit(1)

    log.info("Segments: %d", len(segments))

    if args.run_dir:
        output_path = os.path.join(args.run_dir, "video.mp4")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(OUTPUT_DIR, f"video_{video_type}_{timestamp}.mp4")

    # Skip if non-test video already exists
    if not args.test and os.path.exists(output_path):
        log.info("Video already exists: %s — delete it to re-render", output_path)
        print(f"\nVideo already exists: {output_path}")
        return output_path

    bgm_path = os.path.join(OUTPUT_DIR, "bgm.mp3")
    if not os.path.exists(bgm_path):
        bgm_path = None

    success = False
    if MOVIEPY_AVAILABLE and PILLOW_AVAILABLE:
        try:
            success = render_with_moviepy(segments, output_path, width, height, bgm_path,
                                          visuals_dir=visuals_dir)
        except Exception as exc:
            log.warning("MoviePy failed: %s — falling back to ffmpeg", exc)

    if not success:
        success = render_with_ffmpeg(segments, output_path, width, height, bgm_path,
                                     visuals_dir=visuals_dir)

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
