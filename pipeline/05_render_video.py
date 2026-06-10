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

def render_image_frame(
    base_img: "Image.Image",
    width: int,
    height: int,
    zoom_scale: float = 1.0,
) -> "np.ndarray":
    """Render a clean image-only frame (no text overlay) with optional zoom."""
    cropped = crop_fill(base_img, width, height)
    if zoom_scale != 1.0:
        iw, ih = cropped.size
        new_w, new_h = int(iw * zoom_scale), int(ih * zoom_scale)
        zoomed = cropped.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - width) // 2
        top = (new_h - height) // 2
        cropped = zoomed.crop((left, top, left + width, top + height))
    return np.array(cropped)


def render_text_card(
    text: str,
    width: int,
    height: int,
    sub_text: str = None,
    text_color: tuple = (255, 255, 255),
    bg_color: tuple = (0, 0, 0),
) -> "np.ndarray":
    """Render a text-only card on dark background (for fact sentences / outro)."""
    img = Image.new("RGB", (width, height), bg_color)
    d = ImageDraw.Draw(img)

    font_main_size = max(56, height // 12)
    font_sub_size = max(36, height // 22)
    font_main = find_font(BOLD_FONTS, font_main_size)
    font_sub = find_font(REGULAR_FONTS, font_sub_size)

    # Wrap text to ~40 chars per line
    lines = wrap_words(text, max_chars=max(28, int(width * 0.038)))[:3]
    line_h = font_main_size + 16
    total_h = len(lines) * line_h
    if sub_text:
        total_h += font_sub_size + 24

    y = (height - total_h) // 2
    for line in lines:
        try:
            bb = d.textbbox((0, 0), line, font=font_main)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(line) * (font_main_size // 2)
        x = (width - tw) // 2
        # Drop shadow
        d.text((x + 3, y + 3), line, font=font_main, fill=(0, 0, 0, 120))
        d.text((x, y), line, font=font_main, fill=text_color)
        y += line_h

    if sub_text and font_sub:
        y += 16
        try:
            bb = d.textbbox((0, 0), sub_text, font=font_sub)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(sub_text) * (font_sub_size // 2)
        x = (width - tw) // 2
        d.text((x, y), sub_text, font=font_sub, fill=(160, 160, 160))

    return np.array(img)


def render_hook_outro_frame(
    base_img: "Image.Image",
    heading: str,
    width: int,
    height: int,
) -> "np.ndarray":
    """Hook/outro frame: full-bleed image with channel name overlay at top."""
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # Dark vignette at top
    for y in range(int(height * 0.35)):
        alpha = int(180 * (1 - y / (height * 0.35)))
        d.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    font_size = max(64, height // 10)
    font = find_font(BOLD_FONTS, font_size)

    try:
        bb = d.textbbox((0, 0), heading, font=font)
        tw = bb[2] - bb[0]
    except Exception:
        tw = len(heading) * (font_size // 2)
    bx = (width - tw) // 2
    by = int(height * 0.10)
    d.text((bx + 3, by + 3), heading, font=font, fill=(0, 0, 0, 160))
    d.text((bx, by), heading, font=font, fill=(255, 255, 255, 255))

    frame = overlay_rgba(frame, overlay)
    return np.array(frame)


# keep for legacy fallback only
def render_frame(base_img, heading, narration, width, height,
                 is_hook_outro=False, fact_n=None, key_insight=None):
    if is_hook_outro:
        return render_hook_outro_frame(base_img, heading, width, height)
    return render_image_frame(base_img, width, height)

# ── MoviePy helpers ───────────────────────────────────────────────────────────

def _attach_audio(video_clip, audio_clip):
    try:
        return video_clip.with_audio(audio_clip)
    except AttributeError:
        return video_clip.set_audio(audio_clip)


def _set_dur(clip, dur):
    try:
        return clip.with_duration(dur)
    except AttributeError:
        return clip.set_duration(dur)


def _subclip(clip, start, end):
    try:
        return clip.subclipped(start, end)
    except AttributeError:
        return clip.subclip(start, end)


def build_intro_clip(width: int, height: int, duration: float = 3.0):
    """Black card with BRAINBODA text — cinematic intro."""
    arr = render_text_card("BRAINBODA", width, height,
                           text_color=(255, 215, 0), bg_color=(0, 0, 0))
    clip = ImageClip(arr)
    return _set_dur(clip, duration)


def build_hook_outro_clip(
    audio_path: str,
    segment_id: str,
    heading: str,
    width: int,
    height: int,
    visuals_dir: str = None,
):
    """Hook or outro: full-bleed image with heading overlay."""
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment(segment_id, visuals_dir=visuals_dir)
    if images:
        base_img = Image.open(images[0]).convert("RGB")
    else:
        base_img = make_gradient_bg(width, height)
    base_cropped = crop_fill(base_img, width, height)

    def make_frame(t):
        scale = 1.0 + 0.04 * (t / max(duration, 1))
        iw, ih = base_cropped.size
        nw, nh = int(iw * scale), int(ih * scale)
        zoomed = base_cropped.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - width) // 2, (nh - height) // 2
        img = zoomed.crop((left, top, left + width, top + height))
        return render_hook_outro_frame(img, heading, width, height)

    try:
        video_clip = VideoClip(make_frame, duration=duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)
        return _attach_audio(_set_dur(video_clip, min_dur), _subclip(audio_clip, 0, min_dur))
    except Exception as exc:
        log.error("build_hook_outro_clip failed for %s: %s", segment_id, exc)
        return None


def build_fact_clip(
    audio_path: str,
    segment_id: str,
    heading: str,
    narration: str,
    width: int,
    height: int,
    fact_n: int = None,
    visuals_dir: str = None,
):
    """
    Fact clip in two parts:
    Part A: Black card showing heading + first narration sentence (estimated duration).
    Part B: Image-only rotation with Ken Burns, no text.
    """
    full_duration = get_audio_duration(audio_path)
    images = get_images_for_segment(segment_id, visuals_dir=visuals_dir)

    # Fallback images if none for this fact
    if not images:
        base_vdir = visuals_dir or VISUALS_DIR
        images = glob.glob(os.path.join(base_vdir, "*/*.jpg"))[:3]
    if not images:
        images = []

    # Estimate first-sentence duration (WPM ~140)
    sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
    first_sentence = sentences[0] if sentences else narration
    # Remove "Fact N:" prefix from display
    display_sentence = _re.sub(r'^Fact\s+\d+:\s*', '', first_sentence).strip()

    wpm = 140
    first_dur = max(2.5, len(display_sentence.split()) / wpm * 60)
    first_dur = min(first_dur, full_duration * 0.40)  # cap at 40% of total
    image_dur = full_duration - first_dur

    # ── Part A: text card ─────────────────────────────────────────────────────
    label = f"Fact {fact_n}" if fact_n else heading
    arr_text = render_text_card(
        display_sentence, width, height,
        sub_text=label,
        text_color=(255, 255, 255), bg_color=(5, 5, 10),
    )
    part_a = _set_dur(ImageClip(arr_text), first_dur)

    # ── Part B: image rotation (Ken Burns per image) ──────────────────────────
    if images and image_dur > 0.5:
        n_imgs = len(images)
        dur_each = image_dur / n_imgs
        img_clips = []
        for idx, img_path in enumerate(images):
            try:
                base_img = Image.open(img_path).convert("RGB")
            except Exception:
                continue
            base_cropped = crop_fill(base_img, width, height)
            seg_dur = dur_each

            def make_img_frame(t, bc=base_cropped, sd=seg_dur):
                scale = 1.0 + 0.05 * (t / max(sd, 1))
                iw, ih = bc.size
                nw, nh = int(iw * scale), int(ih * scale)
                zoomed = bc.resize((nw, nh), Image.LANCZOS)
                left, top = (nw - width) // 2, (nh - height) // 2
                return np.array(zoomed.crop((left, top, left + width, top + height)))

            img_clip = _set_dur(VideoClip(make_img_frame, duration=seg_dur), seg_dur)
            img_clips.append(img_clip)

        if img_clips:
            part_b = concatenate_videoclips(img_clips, method="compose")
        else:
            arr_bg = np.array(make_gradient_bg(width, height))
            part_b = _set_dur(ImageClip(arr_bg), image_dur)
    else:
        arr_bg = np.array(make_gradient_bg(width, height))
        part_b = _set_dur(ImageClip(arr_bg), max(image_dur, 0.5))

    try:
        combined = concatenate_videoclips([part_a, part_b], method="compose")
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(full_duration, audio_clip.duration)
        return _attach_audio(_set_dur(combined, min_dur), _subclip(audio_clip, 0, min_dur))
    except Exception as exc:
        log.error("build_fact_clip failed for %s: %s", segment_id, exc)
        return None


# legacy kept for ffmpeg fallback path
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
    if is_hook_outro:
        return build_hook_outro_clip(audio_path, segment_id, heading, width, height, visuals_dir)
    return build_fact_clip(audio_path, segment_id, heading, narration, width, height,
                           fact_n=fact_n, visuals_dir=visuals_dir)

# ── MoviePy renderer ──────────────────────────────────────────────────────────

def render_with_moviepy(segments, output_path, width, height, bgm_path, visuals_dir=None):
    log.info("Using MoviePy renderer")
    clips = []

    # Brainboda cinematic intro (3 sec, no audio)
    intro = build_intro_clip(width, height, duration=3.0)
    if intro:
        clips.append(intro)
        log.info("  Added BRAINBODA intro card")

    for seg in segments:
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            log.warning("Skipping %s — no audio", seg.get("id"))
            continue
        log.info("  Building clip: %s", seg.get("heading", seg.get("id")))
        if seg.get("is_hook_outro"):
            clip = build_hook_outro_clip(
                audio_path, seg["id"], seg["heading"], width, height, visuals_dir
            )
        else:
            clip = build_fact_clip(
                audio_path, seg["id"], seg["heading"], seg["narration"],
                width, height, fact_n=seg.get("fact_n"), visuals_dir=visuals_dir,
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

def _ffmpeg_still_to_video(ffmpeg_bin, frame_path, audio_path, out_path, duration, width, height, fps):
    cmd = [
        ffmpeg_bin, "-y",
        "-loop", "1", "-i", frame_path,
        "-i", audio_path,
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        "-vf", f"scale={width}:{height}",
        "-r", str(fps), out_path,
    ]
    return subprocess.run(cmd, capture_output=True, timeout=300)


def _ffmpeg_silent_video(ffmpeg_bin, frame_path, out_path, duration, width, height, fps):
    """Render a still frame as a video with silent audio."""
    cmd = [
        ffmpeg_bin, "-y",
        "-loop", "1", "-i", frame_path,
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        "-vf", f"scale={width}:{height}",
        "-r", str(fps), "-shortest", out_path,
    ]
    return subprocess.run(cmd, capture_output=True, timeout=60)


def render_with_ffmpeg(segments, output_path, width, height, bgm_path, visuals_dir=None):
    """Pure ffmpeg fallback: pre-renders frames with Pillow, then muxes."""
    log.info("Using ffmpeg fallback renderer")
    tmpdir = tempfile.mkdtemp()
    segment_videos = []
    base_vdir = visuals_dir or VISUALS_DIR
    seg_counter = [0]

    def save_still_seg(frame_arr, audio_path, duration):
        i = seg_counter[0]
        seg_counter[0] += 1
        frame_img = Image.fromarray(frame_arr)
        frame_path = os.path.join(tmpdir, f"frame_{i:03d}.jpg")
        frame_img.save(frame_path, "JPEG", quality=90)
        seg_out = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
        if audio_path:
            r = _ffmpeg_still_to_video(FFMPEG_BIN, frame_path, audio_path, seg_out, duration, width, height, FPS)
        else:
            r = _ffmpeg_silent_video(FFMPEG_BIN, frame_path, seg_out, duration, width, height, FPS)
        if r.returncode == 0 and os.path.exists(seg_out):
            segment_videos.append(seg_out)

    # Brainboda intro (3 sec, silent)
    intro_arr = render_text_card("BRAINBODA", width, height,
                                 text_color=(255, 215, 0), bg_color=(0, 0, 0))
    save_still_seg(intro_arr, None, 3.0)

    for seg in segments:
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            continue

        full_duration = get_audio_duration(audio_path)
        images = get_images_for_segment(seg["id"], visuals_dir=visuals_dir)
        heading = seg.get("heading", "")
        narration = seg.get("narration", "")
        is_ho = seg.get("is_hook_outro", False)
        fact_n = seg.get("fact_n")

        if is_ho:
            if images:
                base_img = Image.open(images[0]).convert("RGB")
            else:
                base_img = make_gradient_bg(width, height)
            frame_arr = render_hook_outro_frame(
                crop_fill(base_img, width, height), heading, width, height
            )
            save_still_seg(frame_arr, audio_path, full_duration)
            continue

        # Fact segment: Part A (text card) + Part B (image rotation)
        if not images:
            all_imgs = glob.glob(os.path.join(base_vdir, "*/*.jpg"))
            images = all_imgs[:3]

        sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
        first_sentence = sentences[0] if sentences else narration
        display_sentence = _re.sub(r'^Fact\s+\d+:\s*', '', first_sentence).strip()
        first_dur = max(2.5, len(display_sentence.split()) / 140 * 60)
        first_dur = min(first_dur, full_duration * 0.40)
        image_dur = full_duration - first_dur

        label = f"Fact {fact_n}" if fact_n else heading
        text_arr = render_text_card(display_sentence, width, height,
                                    sub_text=label, text_color=(255, 255, 255), bg_color=(5, 5, 10))

        # Part A: text card with proportional audio
        i_a = seg_counter[0]
        seg_counter[0] += 1
        frame_path_a = os.path.join(tmpdir, f"frame_{i_a:03d}.jpg")
        Image.fromarray(text_arr).save(frame_path_a, "JPEG", quality=90)
        seg_out_a = os.path.join(tmpdir, f"seg_{i_a:03d}.mp4")
        # Trim audio to first_dur for Part A
        audio_a = os.path.join(tmpdir, f"audio_{i_a:03d}_a.m4a")
        subprocess.run([FFMPEG_BIN, "-y", "-i", audio_path, "-t", str(first_dur),
                        "-c:a", "aac", audio_a], capture_output=True)
        if os.path.exists(audio_a):
            r = _ffmpeg_still_to_video(FFMPEG_BIN, frame_path_a, audio_a, seg_out_a,
                                       first_dur, width, height, FPS)
            if r.returncode == 0:
                segment_videos.append(seg_out_a)

        # Part B: image rotation with remaining audio
        audio_b = os.path.join(tmpdir, f"audio_{i_a:03d}_b.m4a")
        subprocess.run([FFMPEG_BIN, "-y", "-i", audio_path,
                        "-ss", str(first_dur), "-c:a", "aac", audio_b], capture_output=True)
        if images and os.path.exists(audio_b) and image_dur > 0.5:
            n_imgs = len(images)
            dur_each = image_dur / n_imgs
            for idx, img_path in enumerate(images):
                try:
                    base_img = Image.open(img_path).convert("RGB")
                    frame_arr = render_image_frame(base_img, width, height)
                except Exception:
                    continue
                # Audio slice for this image
                audio_slice = os.path.join(tmpdir, f"audio_{i_a:03d}_b{idx}.m4a")
                subprocess.run([FFMPEG_BIN, "-y", "-i", audio_b,
                                "-ss", str(idx * dur_each), "-t", str(dur_each),
                                "-c:a", "aac", audio_slice], capture_output=True)
                if os.path.exists(audio_slice):
                    save_still_seg(frame_arr, audio_slice, dur_each)
                else:
                    save_still_seg(frame_arr, None, dur_each)
        elif os.path.exists(audio_b):
            bg_arr = np.array(make_gradient_bg(width, height))
            save_still_seg(bg_arr, audio_b, image_dur)

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
