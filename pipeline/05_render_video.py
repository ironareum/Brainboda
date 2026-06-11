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


# ── frame renderers ───────────────────────────────────────────────────────────

def _apply_ken_burns(base_cropped: "Image.Image", t: float, duration: float,
                     width: int, height: int) -> "Image.Image":
    scale = 1.0 + 0.05 * (t / max(duration, 1))
    iw, ih = base_cropped.size
    nw, nh = int(iw * scale), int(ih * scale)
    zoomed = base_cropped.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - width) // 2, (nh - height) // 2
    return zoomed.crop((left, top, left + width, top + height))


def render_hook_frame(
    base_img: "Image.Image",
    first_sentence: str,
    width: int,
    height: int,
) -> "np.ndarray":
    """Aperture-style: dark image + large bold centered text for hook."""
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # Full dark dim overlay (60% opacity) for readability
    d.rectangle([0, 0, width, height], fill=(0, 0, 0, 150))

    # Auto-size font to fit text within 80% of frame width, max 3 lines
    max_w = int(width * 0.82)
    font_size = max(60, height // 9)
    font = find_font(BOLD_FONTS, font_size)

    # Auto-reduce font size until text fits
    for _ in range(10):
        chars_per_line = max(10, int(max_w / (font_size * 0.6)))
        lines = wrap_words(first_sentence, max_chars=chars_per_line)[:3]
        # Check actual width
        max_line_w = 0
        for ln in lines:
            try:
                bb = d.textbbox((0, 0), ln, font=font)
                max_line_w = max(max_line_w, bb[2] - bb[0])
            except Exception:
                max_line_w = len(ln) * (font_size * 0.6)
        if max_line_w <= max_w or font_size <= 40:
            break
        font_size = int(font_size * 0.88)
        font = find_font(BOLD_FONTS, font_size)

    line_h = int(font_size * 1.25)
    total_h = len(lines) * line_h
    y = (height - total_h) // 2

    for line in lines:
        try:
            bb = d.textbbox((0, 0), line, font=font)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(line) * int(font_size * 0.6)
        x = (width - tw) // 2
        # Drop shadow
        d.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0, 180))
        d.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    frame = overlay_rgba(frame, overlay)
    return np.array(frame)


def render_fact_frame(
    base_img: "Image.Image",
    fact_n: int,
    first_sentence: str,
    width: int,
    height: int,
) -> "np.ndarray":
    """
    Fact frame: image background with:
    - FACT 0N badge top-left (semi-transparent pill)
    - First sentence text centered (semi-transparent, stays full duration per B2)
    """
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    badge_font_size = max(26, height // 28)
    badge_font = find_font(BOLD_FONTS, badge_font_size)

    # ── FACT badge top-left ──────────────────────────────────────────────────
    badge_text = f"FACT {fact_n:02d}" if fact_n else ""
    if badge_text:
        pad_bx, pad_by = 14, 8
        try:
            bb = d.textbbox((0, 0), badge_text, font=badge_font)
            btw, bth = bb[2] - bb[0], bb[3] - bb[1]
        except Exception:
            btw, bth = len(badge_text) * badge_font_size // 2, badge_font_size
        bx1, by1 = 24, 24
        bx2, by2 = bx1 + btw + pad_bx * 2, by1 + bth + pad_by * 2
        d.rounded_rectangle([bx1, by1, bx2, by2], radius=8, fill=(0, 0, 0, 160))
        d.text((bx1 + pad_bx, by1 + pad_by), badge_text, font=badge_font,
               fill=(255, 255, 255, 220))

    # ── First sentence centered (semi-transparent) ────────────────────────────
    max_w = int(width * 0.78)
    font_size = max(42, height // 16)
    font = find_font(BOLD_FONTS, font_size)

    # Auto-size to fit
    for _ in range(10):
        chars_per_line = max(10, int(max_w / (font_size * 0.58)))
        lines = wrap_words(first_sentence, max_chars=chars_per_line)[:3]
        max_line_w = 0
        for ln in lines:
            try:
                bb = d.textbbox((0, 0), ln, font=font)
                max_line_w = max(max_line_w, bb[2] - bb[0])
            except Exception:
                max_line_w = len(ln) * int(font_size * 0.58)
        if max_line_w <= max_w or font_size <= 32:
            break
        font_size = int(font_size * 0.88)
        font = find_font(BOLD_FONTS, font_size)

    pad_tx, pad_ty = 24, 16
    line_h = int(font_size * 1.3)
    total_text_h = len(lines) * line_h
    box_h = total_text_h + pad_ty * 2
    box_w = max_w + pad_tx * 2
    box_left = (width - box_w) // 2
    box_top = int(height * 0.60)  # lower third
    box_right = box_left + box_w
    box_bot = box_top + box_h

    # Semi-transparent dark background strip
    d.rounded_rectangle([box_left, box_top, box_right, box_bot],
                        radius=12, fill=(0, 0, 0, 140))

    y = box_top + pad_ty
    for line in lines:
        try:
            bb = d.textbbox((0, 0), line, font=font)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(line) * int(font_size * 0.58)
        x = box_left + (box_w - tw) // 2
        d.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 120))
        d.text((x, y), line, font=font, fill=(255, 255, 255, 210))
        y += line_h

    frame = overlay_rgba(frame, overlay)
    return np.array(frame)


def render_outro_frame(
    base_img: "Image.Image",
    width: int,
    height: int,
) -> "np.ndarray":
    """Outro: image with dark vignette, no text (narration handles it)."""
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # Soft vignette edges
    for y in range(int(height * 0.25)):
        alpha = int(120 * (1 - y / (height * 0.25)))
        d.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    for y in range(int(height * 0.25)):
        yy = height - 1 - y
        alpha = int(140 * (1 - y / (height * 0.25)))
        d.line([(0, yy), (width, yy)], fill=(0, 0, 0, alpha))
    frame = overlay_rgba(frame, overlay)
    return np.array(frame)


# keep for legacy ffmpeg fallback only
def render_hook_outro_frame(base_img, heading, width, height):
    return Image.fromarray(render_hook_frame(base_img, heading, width, height))


def render_image_frame(base_img, width, height, zoom_scale=1.0):
    cropped = crop_fill(base_img, width, height)
    if zoom_scale != 1.0:
        iw, ih = cropped.size
        nw, nh = int(iw * zoom_scale), int(ih * zoom_scale)
        zoomed = cropped.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - width) // 2, (nh - height) // 2
        cropped = zoomed.crop((left, top, left + width, top + height))
    return np.array(cropped)


def render_frame(base_img, heading, narration, width, height,
                 is_hook_outro=False, fact_n=None, key_insight=None):
    if is_hook_outro:
        return render_hook_frame(base_img, heading, width, height)
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


def _make_black_transition(width: int, height: int, duration: float = 0.7):
    """Short silent black clip used between facts."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    return _set_dur(ImageClip(arr), duration)


def build_intro_clip(width: int, height: int):
    """BRAINBODA cinematic intro — uses intro_sfx.mp3 if present, else silent 2s."""
    sfx_path = os.path.join(_BASE_DIR, "config", "audio", "intro_sfx.mp3")
    if os.path.exists(sfx_path):
        duration = get_audio_duration(sfx_path)
    else:
        duration = 2.0

    img = Image.new("RGB", (width, height), (0, 0, 0))
    d = ImageDraw.Draw(img)
    font_size = max(80, height // 8)
    font = find_font(BOLD_FONTS, font_size)
    text = "BRAINBODA"
    try:
        bb = d.textbbox((0, 0), text, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
    except Exception:
        tw, th = len(text) * font_size // 2, font_size
    x, y = (width - tw) // 2, (height - th) // 2
    d.text((x + 4, y + 4), text, font=font, fill=(80, 60, 0))
    d.text((x, y), text, font=font, fill=(255, 215, 0))

    clip = _set_dur(ImageClip(np.array(img)), duration)
    if os.path.exists(sfx_path):
        try:
            audio = AudioFileClip(sfx_path)
            clip = _attach_audio(clip, _subclip(audio, 0, duration))
        except Exception as exc:
            log.warning("intro_sfx load failed: %s", exc)
    return clip


def build_hook_clip(
    audio_path: str,
    narration: str,
    width: int,
    height: int,
    visuals_dir: str = None,
):
    """Hook: dark image + first hook sentence as large bold centered text (Aperture style)."""
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment("hook", visuals_dir=visuals_dir)
    if not images:
        # Use any available fact image as atmospheric background
        base_vdir = visuals_dir or VISUALS_DIR
        images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:1]

    if images:
        base_img = Image.open(images[0]).convert("RGB")
    else:
        base_img = make_gradient_bg(width, height)
    base_cropped = crop_fill(base_img, width, height)

    # First sentence of hook (strip leading "Did you know" type openers if very long)
    sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
    first_sentence = sentences[0] if sentences else narration

    def make_frame(t):
        img = _apply_ken_burns(base_cropped, t, duration, width, height)
        return render_hook_frame(img, first_sentence, width, height)

    try:
        video_clip = VideoClip(make_frame, duration=duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)
        return _attach_audio(_set_dur(video_clip, min_dur), _subclip(audio_clip, 0, min_dur))
    except Exception as exc:
        log.error("build_hook_clip failed: %s", exc)
        return None


def build_fact_clip(
    audio_path: str,
    segment_id: str,
    narration: str,
    width: int,
    height: int,
    fact_n: int = None,
    visuals_dir: str = None,
):
    """
    Fact clip: rotating images (Ken Burns) with FACT badge + first sentence overlay.
    Text stays for entire duration (B2). 3 images rotate evenly.
    """
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment(segment_id, visuals_dir=visuals_dir)
    if not images:
        base_vdir = visuals_dir or VISUALS_DIR
        images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:3]

    # Extract display sentence (strip "Fact N: Title." opener)
    sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
    raw_first = sentences[0] if sentences else narration
    display_sentence = _re.sub(r'^Fact\s+\d+[:\.]?\s*', '', raw_first).strip()
    # If it's still just a heading (short), use the next sentence
    if len(display_sentence.split()) <= 3 and len(sentences) > 1:
        display_sentence = sentences[1]

    if not images:
        # Solid gradient fallback
        def make_frame_bg(t):
            bg = make_gradient_bg(width, height)
            return render_fact_frame(bg, fact_n, display_sentence, width, height)
        try:
            video_clip = VideoClip(make_frame_bg, duration=duration)
            audio_clip = AudioFileClip(audio_path)
            min_dur = min(duration, audio_clip.duration)
            return _attach_audio(_set_dur(video_clip, min_dur), _subclip(audio_clip, 0, min_dur))
        except Exception as exc:
            log.error("build_fact_clip fallback failed for %s: %s", segment_id, exc)
            return None

    n_imgs = len(images)
    dur_each = duration / n_imgs
    loaded = []
    for p in images:
        try:
            img = Image.open(p).convert("RGB")
            loaded.append(crop_fill(img, width, height))
        except Exception:
            pass
    if not loaded:
        loaded = [make_gradient_bg(width, height)]
        n_imgs = 1
        dur_each = duration

    img_clips = []
    for idx, base_cropped in enumerate(loaded):
        seg_dur = dur_each

        def make_frame(t, bc=base_cropped, sd=seg_dur):
            img = _apply_ken_burns(bc, t, sd, width, height)
            return render_fact_frame(img, fact_n, display_sentence, width, height)

        img_clips.append(_set_dur(VideoClip(make_frame, duration=seg_dur), seg_dur))

    try:
        combined = concatenate_videoclips(img_clips, method="compose")
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)
        return _attach_audio(_set_dur(combined, min_dur), _subclip(audio_clip, 0, min_dur))
    except Exception as exc:
        log.error("build_fact_clip failed for %s: %s", segment_id, exc)
        return None


def build_outro_clip(
    audio_path: str,
    width: int,
    height: int,
    visuals_dir: str = None,
):
    """Outro: image with vignette, no text overlay, fade to black at end."""
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment("outro", visuals_dir=visuals_dir)
    if not images:
        base_vdir = visuals_dir or VISUALS_DIR
        images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:1]

    if images:
        base_img = Image.open(images[0]).convert("RGB")
    else:
        base_img = make_gradient_bg(width, height)
    base_cropped = crop_fill(base_img, width, height)

    def make_frame(t):
        img = _apply_ken_burns(base_cropped, t, duration, width, height)
        arr = render_outro_frame(img, width, height)
        # Fade to black in last 1.5s
        fade_start = max(0.0, duration - 1.5)
        if t >= fade_start:
            fade_frac = (t - fade_start) / 1.5
            fade_overlay = (np.zeros_like(arr, dtype=np.float32) +
                            np.array(arr, dtype=np.float32) * (1 - fade_frac))
            return fade_overlay.clip(0, 255).astype(np.uint8)
        return arr

    try:
        video_clip = VideoClip(make_frame, duration=duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)
        return _attach_audio(_set_dur(video_clip, min_dur), _subclip(audio_clip, 0, min_dur))
    except Exception as exc:
        log.error("build_outro_clip failed: %s", exc)
        return None


# legacy alias for ffmpeg path
def build_hook_outro_clip(audio_path, segment_id, heading, width, height, visuals_dir=None):
    if segment_id == "outro":
        return build_outro_clip(audio_path, width, height, visuals_dir)
    return build_hook_clip(audio_path, heading, width, height, visuals_dir)


def build_clip(audio_path, segment_id, heading, narration, width, height,
               is_hook_outro=False, fact_n=None, visuals_dir=None, key_insight=None):
    if segment_id == "hook":
        return build_hook_clip(audio_path, narration, width, height, visuals_dir)
    if segment_id == "outro":
        return build_outro_clip(audio_path, width, height, visuals_dir)
    return build_fact_clip(audio_path, segment_id, narration, width, height,
                           fact_n=fact_n, visuals_dir=visuals_dir)

# ── MoviePy renderer ──────────────────────────────────────────────────────────

def render_with_moviepy(segments, output_path, width, height, bgm_path, visuals_dir=None):
    log.info("Using MoviePy renderer")
    clips = []

    # BRAINBODA intro
    intro = build_intro_clip(width, height)
    if intro:
        clips.append(intro)
        log.info("  Added BRAINBODA intro")

    for seg in segments:
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            log.warning("Skipping %s — no audio", seg.get("id"))
            continue
        seg_id = seg.get("id", "")
        log.info("  Building clip: %s", seg.get("heading", seg_id))

        if seg_id == "hook":
            clip = build_hook_clip(audio_path, seg.get("narration", ""),
                                   width, height, visuals_dir)
        elif seg_id == "outro":
            clip = build_outro_clip(audio_path, width, height, visuals_dir)
        else:
            # Prepend 0.7s black transition before each fact
            clips.append(_make_black_transition(width, height, 0.7))
            clip = build_fact_clip(
                audio_path, seg_id, seg.get("narration", ""),
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
        frame_path = os.path.join(tmpdir, f"frame_{i:03d}.png")
        frame_img.save(frame_path, "PNG")
        seg_out = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
        if audio_path and os.path.exists(audio_path):
            r = _ffmpeg_still_to_video(FFMPEG_BIN, frame_path, audio_path, seg_out, duration, width, height, FPS)
        else:
            r = _ffmpeg_silent_video(FFMPEG_BIN, frame_path, seg_out, duration, width, height, FPS)
        if r.returncode == 0 and os.path.exists(seg_out):
            segment_videos.append(seg_out)
        else:
            log.warning("  Segment render failed (returncode=%s)", r.returncode if hasattr(r, 'returncode') else '?')

    # BRAINBODA intro
    sfx_path = os.path.join(_BASE_DIR, "config", "audio", "intro_sfx.mp3")
    intro_dur = get_audio_duration(sfx_path) if os.path.exists(sfx_path) else 2.0
    img = Image.new("RGB", (width, height), (0, 0, 0))
    d_intro = ImageDraw.Draw(img)
    fs = max(80, height // 8)
    fnt = find_font(BOLD_FONTS, fs)
    text = "BRAINBODA"
    try:
        bb = d_intro.textbbox((0, 0), text, font=fnt)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
    except Exception:
        tw, th = len(text) * fs // 2, fs
    d_intro.text(((width - tw) // 2 + 4, (height - th) // 2 + 4), text, font=fnt, fill=(80, 60, 0))
    d_intro.text(((width - tw) // 2, (height - th) // 2), text, font=fnt, fill=(255, 215, 0))
    save_still_seg(np.array(img), sfx_path if os.path.exists(sfx_path) else None, intro_dur)

    for seg in segments:
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            continue

        full_duration = get_audio_duration(audio_path)
        seg_id = seg.get("id", "")
        images = get_images_for_segment(seg_id, visuals_dir=visuals_dir)
        narration = seg.get("narration", "")
        fact_n = seg.get("fact_n")

        if seg_id == "hook":
            if not images:
                all_imgs = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))
                images = all_imgs[:1]
            base_img = Image.open(images[0]).convert("RGB") if images else make_gradient_bg(width, height)
            sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
            first_s = sentences[0] if sentences else narration
            frame_arr = render_hook_frame(crop_fill(base_img, width, height), first_s, width, height)
            save_still_seg(frame_arr, audio_path, full_duration)
            continue

        if seg_id == "outro":
            if not images:
                all_imgs = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))
                images = all_imgs[:1]
            base_img = Image.open(images[0]).convert("RGB") if images else make_gradient_bg(width, height)
            frame_arr = render_outro_frame(crop_fill(base_img, width, height), width, height)
            save_still_seg(frame_arr, audio_path, full_duration)
            continue

        # ── Fact segment: black transition + image rotation with overlay ───────
        if not images:
            images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:3]

        sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
        raw_first = sentences[0] if sentences else narration
        display_sentence = _re.sub(r'^Fact\s+\d+[:\.]?\s*', '', raw_first).strip()
        if len(display_sentence.split()) <= 3 and len(sentences) > 1:
            display_sentence = sentences[1]

        # 0.7s black transition before fact
        save_still_seg(np.zeros((height, width, 3), dtype=np.uint8), None, 0.7)

        # Rotate through images with overlay
        n_imgs = max(1, len(images))
        dur_each = full_duration / n_imgs
        for idx, img_path in enumerate(images):
            try:
                base_img = Image.open(img_path).convert("RGB")
            except Exception:
                base_img = make_gradient_bg(width, height)
            frame_arr = render_fact_frame(crop_fill(base_img, width, height),
                                          fact_n, display_sentence, width, height)
            # Audio slice for this image segment
            audio_slice = os.path.join(tmpdir, f"aslice_{seg_counter[0]:03d}_{idx}.m4a")
            subprocess.run([FFMPEG_BIN, "-y", "-i", audio_path,
                            "-ss", str(idx * dur_each), "-t", str(dur_each),
                            "-c:a", "aac", audio_slice], capture_output=True)
            save_still_seg(frame_arr,
                           audio_slice if os.path.exists(audio_slice) else None,
                           dur_each)

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
