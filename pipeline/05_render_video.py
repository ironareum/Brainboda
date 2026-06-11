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


def render_typewriter_frame(
    base_img: "Image.Image",
    text_so_far: str,
    full_text: str,
    width: int,
    height: int,
    font_size: int,
    font,
    left_margin: int,
    line_h: int,
    text_start_y: int,
) -> "np.ndarray":
    """Hook typewriter: dark image + text typed from left, cursor at end."""
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle([0, 0, width, height], fill=(0, 0, 0, 145))

    if not text_so_far:
        return np.array(overlay_rgba(frame, overlay))

    # Wrap revealed text at same width as full text (so layout is stable)
    max_line_w = width - left_margin * 2
    chars_per_line = max(10, int(max_line_w / max(1, font_size * 0.6)))
    lines = wrap_words(text_so_far, max_chars=chars_per_line)

    y = text_start_y
    for i, line in enumerate(lines):
        is_last = (i == len(lines) - 1)
        display = line + ("▋" if is_last else "")
        d.text((left_margin + 3, y + 3), display, font=font, fill=(0, 0, 0, 160))
        d.text((left_margin, y), display, font=font, fill=(255, 255, 255, 255))
        y += line_h

    return np.array(overlay_rgba(frame, overlay))


def render_hook_frame(
    base_img: "Image.Image",
    first_sentence: str,
    width: int,
    height: int,
) -> "np.ndarray":
    """Static hook frame (used when text display is complete — image only)."""
    frame = crop_fill(base_img.copy(), width, height)
    # Slight dim only, no text
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 60))
    frame = overlay_rgba(frame, overlay)
    return np.array(frame)


def render_fact_title_frame(
    base_img: "Image.Image",
    fact_n: int,
    heading: str,
    width: int,
    height: int,
) -> "np.ndarray":
    """
    Fact title frame: 'Fact N: Heading.' centered on image.
    Shown while the title sentence is being narrated, then disappears.
    """
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # Moderate dark overlay for text readability
    d.rectangle([0, 0, width, height], fill=(0, 0, 0, 130))

    display_text = f"Fact {fact_n}: {heading}." if fact_n else heading

    max_w = int(width * 0.80)
    font_size = max(52, height // 13)
    font = find_font(BOLD_FONTS, font_size)

    for _ in range(10):
        chars_per_line = max(10, int(max_w / max(1, font_size * 0.60)))
        lines = wrap_words(display_text, max_chars=chars_per_line)[:3]
        max_line_w = 0
        for ln in lines:
            try:
                bb = d.textbbox((0, 0), ln, font=font)
                max_line_w = max(max_line_w, bb[2] - bb[0])
            except Exception:
                max_line_w = len(ln) * int(font_size * 0.60)
        if max_line_w <= max_w or font_size <= 36:
            break
        font_size = int(font_size * 0.88)
        font = find_font(BOLD_FONTS, font_size)

    line_h = int(font_size * 1.3)
    total_h = len(lines) * line_h
    y = (height - total_h) // 2

    for line in lines:
        try:
            bb = d.textbbox((0, 0), line, font=font)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(line) * int(font_size * 0.60)
        x = (width - tw) // 2
        d.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0, 180))
        d.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    frame = overlay_rgba(frame, overlay)
    return np.array(frame)


def render_fact_image_frame(
    base_img: "Image.Image",
    fact_n: int,
    width: int,
    height: int,
) -> "np.ndarray":
    """Fact image-only frame with FACT 0N badge top-left. No body text."""
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    badge_font_size = max(26, height // 28)
    badge_font = find_font(BOLD_FONTS, badge_font_size)
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
        d.rounded_rectangle([bx1, by1, bx2, by2], radius=8, fill=(0, 0, 0, 155))
        d.text((bx1 + pad_bx, by1 + pad_by), badge_text, font=badge_font,
               fill=(255, 255, 255, 220))

    frame = overlay_rgba(frame, overlay)
    return np.array(frame)


# legacy — kept for ffmpeg fallback reference
def render_fact_frame(base_img, fact_n, first_sentence, width, height):
    return render_fact_title_frame(base_img, fact_n, first_sentence, width, height)



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


def _load_bgm(name: str):
    """Load a BGM file from config/audio/ or return None."""
    path = os.path.join(_BASE_DIR, "config", "audio", name)
    if not os.path.exists(path):
        return None, None
    try:
        clip = AudioFileClip(path)
        return clip, path
    except Exception as exc:
        log.warning("BGM load failed (%s): %s", name, exc)
        return None, None


def build_hook_clip(
    audio_path: str,
    narration: str,
    width: int,
    height: int,
    visuals_dir: str = None,
):
    """
    Hook clip:
    - First sentence: typewriter effect (chars reveal left-to-right, synced with narration)
    - After first sentence: image-only with transitions
    - BGM: bgm_hook.mp3 mixed in (if present), slight volume swell at end
    """
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment("hook", visuals_dir=visuals_dir)
    if not images:
        base_vdir = visuals_dir or VISUALS_DIR
        images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:3]
    if not images:
        images = []

    # Load images
    loaded_imgs = []
    for p in images[:3]:
        try:
            loaded_imgs.append(crop_fill(Image.open(p).convert("RGB"), width, height))
        except Exception:
            pass
    if not loaded_imgs:
        loaded_imgs = [make_gradient_bg(width, height)]

    # Parse sentences
    sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
    first_sentence = sentences[0] if sentences else narration

    # Estimate first sentence duration (WPM ~135)
    wpm = 135
    first_dur = max(3.0, len(first_sentence.split()) / wpm * 60)
    first_dur = min(first_dur, duration * 0.50)

    # Pre-compute typewriter font metrics (stable across all frames)
    left_margin = int(width * 0.08)
    max_line_w = width - left_margin * 2
    font_size = max(56, height // 11)
    font = find_font(BOLD_FONTS, font_size)
    # Auto-size to ensure full sentence fits in ≤3 lines
    for _ in range(10):
        chars_per_line = max(10, int(max_line_w / max(1, font_size * 0.60)))
        test_lines = wrap_words(first_sentence, max_chars=chars_per_line)
        if len(test_lines) <= 3:
            break
        font_size = int(font_size * 0.88)
        font = find_font(BOLD_FONTS, font_size)
    line_h = int(font_size * 1.25)
    # Vertical start: center of frame for expected max lines
    n_lines_est = len(wrap_words(first_sentence, max_chars=max(10, int(max_line_w / max(1, font_size * 0.60)))))
    text_start_y = (height - n_lines_est * line_h) // 2

    total_chars = len(first_sentence)
    n_imgs = len(loaded_imgs)
    img_dur = (duration - first_dur) / max(n_imgs, 1) if duration > first_dur else 0

    def make_frame(t):
        # Pick background image (cycle through for image section)
        if t < first_dur:
            bg = _apply_ken_burns(loaded_imgs[0], t, first_dur, width, height)
        else:
            idx = int((t - first_dur) / max(img_dur, 0.01)) % n_imgs
            bc = loaded_imgs[idx % n_imgs]
            local_t = (t - first_dur) % max(img_dur, 0.01)
            bg = _apply_ken_burns(bc, local_t, img_dur, width, height)

        if t < first_dur:
            # Typewriter: reveal characters proportionally
            progress = t / first_dur
            n_show = int(progress * total_chars)
            text_so_far = first_sentence[:n_show]
            return render_typewriter_frame(
                bg, text_so_far, first_sentence, width, height,
                font_size, font, left_margin, line_h, text_start_y,
            )
        else:
            # After first sentence: image only (slight dim)
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 55))
            return np.array(overlay_rgba(bg, overlay))

    try:
        video_clip = VideoClip(make_frame, duration=duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)
        video_clip = _set_dur(video_clip, min_dur)
        audio_clip = _subclip(audio_clip, 0, min_dur)

        # Mix bgm_hook.mp3
        bgm_audio, bgm_path = _load_bgm("bgm_hook.mp3")
        if bgm_audio:
            try:
                # Loop BGM to cover full duration
                bgm = bgm_audio.volumex(0.10)
                if bgm.duration < min_dur:
                    # Simple loop via concatenation
                    loops = int(min_dur / bgm.duration) + 1
                    from moviepy import concatenate_audioclips
                    bgm = concatenate_audioclips([bgm_audio.volumex(0.10)] * loops)
                bgm = _subclip(bgm, 0, min_dur)
                # Slight swell in last 2s
                mixed = CompositeAudioClip([audio_clip, bgm])
                video_clip = _attach_audio(video_clip, mixed)
            except Exception as exc:
                log.warning("Hook BGM mix failed: %s", exc)
                video_clip = _attach_audio(video_clip, audio_clip)
        else:
            video_clip = _attach_audio(video_clip, audio_clip)

        return video_clip
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
    heading: str = "",
    visuals_dir: str = None,
):
    """
    Fact clip:
    - Part A (title duration): 'Fact N: Heading.' centered on image, synced with narration
    - Part B (rest): image rotation (Ken Burns) + FACT badge only, no text
    BGM: bgm_facts.mp3 mixed in (if present)
    """
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment(segment_id, visuals_dir=visuals_dir)
    if not images:
        base_vdir = visuals_dir or VISUALS_DIR
        images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:3]

    # Load images
    loaded = []
    for p in images:
        try:
            loaded.append(crop_fill(Image.open(p).convert("RGB"), width, height))
        except Exception:
            pass
    if not loaded:
        loaded = [make_gradient_bg(width, height)]

    # Title text to display during narration of "Fact N: Heading."
    title_text = f"Fact {fact_n}: {heading}." if fact_n and heading else heading

    # Estimate how long the title sentence takes to narrate
    title_words = len(title_text.split())
    title_dur = max(2.0, title_words / 135 * 60)
    title_dur = min(title_dur, duration * 0.45)
    image_dur = duration - title_dur

    n_imgs = len(loaded)
    img_dur_each = image_dur / n_imgs if n_imgs else image_dur

    def make_frame(t):
        # Image rotation
        if t < title_dur:
            bc = loaded[0]
            img = _apply_ken_burns(bc, t, title_dur, width, height)
            return render_fact_title_frame(img, fact_n, heading, width, height)
        else:
            local_t = t - title_dur
            idx = int(local_t / max(img_dur_each, 0.01)) % n_imgs
            bc = loaded[idx]
            seg_local_t = local_t % max(img_dur_each, 0.01)
            img = _apply_ken_burns(bc, seg_local_t, img_dur_each, width, height)
            return render_fact_image_frame(img, fact_n, width, height)

    try:
        video_clip = _set_dur(VideoClip(make_frame, duration=duration), duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)
        video_clip = _set_dur(video_clip, min_dur)
        audio_clip = _subclip(audio_clip, 0, min_dur)

        # Mix bgm_facts.mp3
        bgm_audio, _ = _load_bgm("bgm_facts.mp3")
        if bgm_audio:
            try:
                bgm = bgm_audio.volumex(0.09)
                if bgm.duration < min_dur:
                    from moviepy import concatenate_audioclips
                    loops = int(min_dur / bgm.duration) + 1
                    bgm = concatenate_audioclips([bgm_audio.volumex(0.09)] * loops)
                bgm = _subclip(bgm, 0, min_dur)
                mixed = CompositeAudioClip([audio_clip, bgm])
                return _attach_audio(video_clip, mixed)
            except Exception as exc:
                log.warning("Facts BGM mix failed: %s", exc)

        return _attach_audio(video_clip, audio_clip)
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
                           fact_n=fact_n, heading=heading, visuals_dir=visuals_dir)

# ── MoviePy renderer ──────────────────────────────────────────────────────────

def render_with_moviepy(segments, output_path, width, height, bgm_path, visuals_dir=None):
    log.info("Using MoviePy renderer")
    clips = []

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
            # 0.7s black transition before each fact
            clips.append(_make_black_transition(width, height, 0.7))
            clip = build_fact_clip(
                audio_path, seg_id, seg.get("narration", ""),
                width, height, fact_n=seg.get("fact_n"),
                heading=seg.get("heading", ""), visuals_dir=visuals_dir,
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

    # No intro — hook starts immediately

    for seg in segments:
        audio_path = seg.get("audio")
        if not audio_path or not os.path.exists(audio_path):
            continue

        full_duration = get_audio_duration(audio_path)
        seg_id = seg.get("id", "")
        images = get_images_for_segment(seg_id, visuals_dir=visuals_dir)
        narration = seg.get("narration", "")
        fact_n = seg.get("fact_n")
        heading = seg.get("heading", "")

        if seg_id == "hook":
            if not images:
                images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:1]
            base_img = Image.open(images[0]).convert("RGB") if images else make_gradient_bg(width, height)
            sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
            first_s = sentences[0] if sentences else narration
            # ffmpeg: static frame with first sentence (no typewriter in fallback)
            frame_arr = render_fact_title_frame(
                crop_fill(base_img, width, height), None, first_s, width, height)
            save_still_seg(frame_arr, audio_path, full_duration)
            continue

        if seg_id == "outro":
            if not images:
                images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:1]
            base_img = Image.open(images[0]).convert("RGB") if images else make_gradient_bg(width, height)
            frame_arr = render_outro_frame(crop_fill(base_img, width, height), width, height)
            save_still_seg(frame_arr, audio_path, full_duration)
            continue

        # ── Fact segment: black transition + title frame + image rotation ──────
        if not images:
            images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:3]

        title_words = len(f"Fact {fact_n}: {heading}.".split()) if fact_n else len(heading.split())
        title_dur = max(2.0, title_words / 135 * 60)
        title_dur = min(title_dur, full_duration * 0.45)
        image_dur = full_duration - title_dur

        # 0.7s black transition
        save_still_seg(np.zeros((height, width, 3), dtype=np.uint8), None, 0.7)

        # Part A: title frame with title-duration audio
        if images:
            base_img = Image.open(images[0]).convert("RGB")
        else:
            base_img = make_gradient_bg(width, height)
        title_frame = render_fact_title_frame(crop_fill(base_img, width, height),
                                              fact_n, heading, width, height)
        audio_a = os.path.join(tmpdir, f"atitle_{seg_counter[0]:03d}.m4a")
        subprocess.run([FFMPEG_BIN, "-y", "-i", audio_path, "-t", str(title_dur),
                        "-c:a", "aac", audio_a], capture_output=True)
        save_still_seg(title_frame, audio_a if os.path.exists(audio_a) else None, title_dur)

        # Part B: image rotation with badge overlay
        n_imgs = max(1, len(images))
        dur_each = image_dur / n_imgs
        for idx, img_path in enumerate(images):
            try:
                base_img = Image.open(img_path).convert("RGB")
            except Exception:
                base_img = make_gradient_bg(width, height)
            frame_arr = render_fact_image_frame(crop_fill(base_img, width, height),
                                                fact_n, width, height)
            audio_slice = os.path.join(tmpdir, f"aslice_{seg_counter[0]:03d}_{idx}.m4a")
            ss = title_dur + idx * dur_each
            subprocess.run([FFMPEG_BIN, "-y", "-i", audio_path,
                            "-ss", str(ss), "-t", str(dur_each),
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
