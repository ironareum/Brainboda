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


def get_images_for_segment(segment_id: str, visuals_dir: str = None,
                           narration_only: bool = False):
    """Return sorted image paths for a segment.

    segment_id == 'hook'  → uses _hook/ folder (generic psychology images)
    narration_only=True   → skips img_01 (reserved for title card)
    """
    base = visuals_dir or VISUALS_DIR
    # Hook uses its own dedicated image pool
    folder = "_hook" if segment_id == "hook" else segment_id
    seg_dir = os.path.join(base, folder)
    if not os.path.isdir(seg_dir):
        return []
    imgs = sorted(
        glob.glob(os.path.join(seg_dir, "*.jpg")) +
        glob.glob(os.path.join(seg_dir, "*.png"))
    )
    if narration_only:
        # img_01 is reserved for the title card — skip it for narration slides
        imgs = [p for p in imgs if not os.path.basename(p).startswith("img_01.")]
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

_LETTERBOX_RATIO = 0.05  # 5% black bar top and bottom

def _apply_letterbox(arr: "np.ndarray") -> "np.ndarray":
    """Add cinematic black bars — top/bottom 5%."""
    h = arr.shape[0]
    bar = int(h * _LETTERBOX_RATIO)
    result = arr.copy()
    result[:bar] = 0
    result[h - bar:] = 0
    return result


def _apply_ken_burns(base_cropped: "Image.Image", t: float, duration: float,
                     width: int, height: int) -> "Image.Image":
    scale = 1.0 + 0.08 * (t / max(duration, 1))
    iw, ih = base_cropped.size
    nw, nh = int(iw * scale), int(ih * scale)
    zoomed = base_cropped.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - width) // 2, (nh - height) // 2
    return zoomed.crop((left, top, left + width, top + height))


def _is_emphasis_word(word: str) -> bool:
    """Highlight numbers, percentages, and short ALL-CAPS words."""
    clean = word.strip(".,!?\"'()")
    if _re.match(r"^\d+([.,]\d+)?%?$", clean):
        return True
    if len(clean) >= 2 and clean.isupper():
        return True
    return False


def render_hook_word_reveal_frame(
    base_img: "Image.Image",
    words_to_show: int,
    all_words: list,
    width: int,
    height: int,
    font_size: int,
    font,
    font_em,
    left_margin: int,
    line_h: int,
    text_start_y: int,
) -> "np.ndarray":
    """Hook word-by-word reveal: each word fades in sequentially.
    Emphasis words (numbers, %) are yellow and slightly larger.
    """
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle([0, 0, width, height], fill=(0, 0, 0, 150))

    if not words_to_show or not all_words:
        return _apply_letterbox(np.array(overlay_rgba(frame, overlay)))

    visible = all_words[:words_to_show]
    text_so_far = " ".join(visible)
    max_line_w = width - left_margin * 2
    chars_per_line = max(10, int(max_line_w / max(1, font_size * 0.60)))
    lines = wrap_words(text_so_far, max_chars=chars_per_line)

    y = text_start_y
    for line in lines:
        x = left_margin
        for word in line.split():
            is_em = _is_emphasis_word(word)
            color = (255, 220, 50, 255) if is_em else (255, 255, 255, 255)
            f = font_em if is_em else font
            # shadow
            d.text((x + 2, y + 2), word + " ", font=f, fill=(0, 0, 0, 160))
            d.text((x, y), word + " ", font=f, fill=color)
            try:
                w = f.getlength(word + " ")
            except AttributeError:
                w = font_size * 0.6 * (len(word) + 1)
            x += int(w)
        y += line_h

    return _apply_letterbox(np.array(overlay_rgba(frame, overlay)))


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
        display = line  # no cursor
        d.text((left_margin + 3, y + 3), display, font=font, fill=(0, 0, 0, 160))
        d.text((left_margin, y), display, font=font, fill=(255, 255, 255, 255))
        y += line_h

    return _apply_letterbox(np.array(overlay_rgba(frame, overlay)))


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
    """Fact title frame: 'Fact N: Heading.' centered on image."""
    frame = crop_fill(base_img.copy(), width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
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
    return _apply_letterbox(np.array(frame))


def render_fact_image_frame(
    base_img: "Image.Image",
    fact_n: int,
    width: int,
    height: int,
) -> "np.ndarray":
    """Fact image-only frame — clean image, no badge overlay."""
    frame = crop_fill(base_img.copy(), width, height)
    return _apply_letterbox(np.array(frame))


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


def _vol(clip, v: float):
    """Set audio clip volume — handles MoviePy v1/v2/v2.x API differences."""
    if hasattr(clip, 'multiply_volume'):
        return clip.multiply_volume(v)
    if hasattr(clip, 'volumex'):
        return clip.volumex(v)
    # MoviePy v2 effects system
    try:
        from moviepy.audio.fx import MultiplyVolume
        return clip.with_effects([MultiplyVolume(v)])
    except Exception:
        pass
    try:
        from moviepy.audio.fx.multiply_volume import MultiplyVolume
        return clip.with_effects([MultiplyVolume(v)])
    except Exception:
        pass
    log.warning("Cannot set BGM volume — no compatible API found. Skipping BGM.")
    return None


def _load_bgm(segment: str):
    """Load a random BGM from config/bgm/{segment}/ folder.
    Falls back to config/audio/bgm_{segment}.mp3.
    segment: 'hook', 'facts', 'outro'
    """
    import random
    folder = os.path.join(_BASE_DIR, "config", "bgm", segment)
    if os.path.isdir(folder):
        files = sorted(glob.glob(os.path.join(folder, "*.mp3")) +
                       glob.glob(os.path.join(folder, "*.wav")))
        if files:
            path = random.choice(files)
            try:
                clip = AudioFileClip(path)
                log.info("BGM (%s): %s", segment, os.path.basename(path))
                return clip, path
            except Exception as exc:
                log.warning("BGM load failed (%s): %s", path, exc)
    # Fallback: single file
    path = os.path.join(_BASE_DIR, "config", "audio", f"bgm_{segment}.mp3")
    if not os.path.exists(path):
        return None, None
    try:
        return AudioFileClip(path), path
    except Exception as exc:
        log.warning("BGM load failed (%s): %s", path, exc)
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
    - Hook sentence displayed all-at-once (bold, centered) on Ken Burns image
    - After hook duration: image-only with fast transitions
    - BGM: bgm_hook.mp3 mixed in (if present)
    """
    duration = get_audio_duration(audio_path)
    images = get_images_for_segment("hook", visuals_dir=visuals_dir)
    if not images:
        base_vdir = visuals_dir or VISUALS_DIR
        images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:3]

    # Load 1 image for hook (clean, focused look)
    loaded_imgs = []
    for p in images[:1]:
        try:
            loaded_imgs.append(crop_fill(Image.open(p).convert("RGB"), width, height))
        except Exception:
            pass
    if not loaded_imgs:
        log.error("No images available for hook segment — run 04_fetch_visuals.py first")
        sys.exit(1)

    sentences = _re.split(r'(?<=[.!?])\s+', narration.strip())
    hook_sentence = sentences[0] if sentences else narration
    all_words = hook_sentence.split()
    n_words = len(all_words)

    # Hook text reveal covers first ~45% of duration
    hook_dur = min(duration * 0.45, max(3.0, n_words / 135 * 60))

    # Font metrics — bold font + slightly larger emphasis font
    left_margin = int(width * 0.08)
    max_line_w = width - left_margin * 2
    font_size = max(45, height // 14)
    font = find_font(BOLD_FONTS, font_size)
    for _ in range(10):
        chars_per_line = max(10, int(max_line_w / max(1, font_size * 0.60)))
        if len(wrap_words(hook_sentence, max_chars=chars_per_line)) <= 3:
            break
        font_size = int(font_size * 0.88)
        font = find_font(BOLD_FONTS, font_size)
    font_em = find_font(BOLD_FONTS, int(font_size * 1.10))  # emphasis: 10% bigger
    line_h = int(font_size * 1.35)
    chars_per_line = max(10, int(max_line_w / max(1, font_size * 0.60)))
    lines = wrap_words(hook_sentence, max_chars=chars_per_line)
    text_start_y = (height - len(lines) * line_h) // 2

    bg_img = loaded_imgs[0]

    # Word reveal: spread words evenly across the FULL audio duration (matches narration pace)
    word_interval = duration / max(n_words, 1)

    def make_frame(t):
        bg = _apply_ken_burns(bg_img, t, duration, width, height)
        words_visible = min(n_words, max(1, int(t / word_interval) + 1))
        return render_hook_word_reveal_frame(
            bg, words_visible, all_words, width, height,
            font_size, font, font_em, left_margin, line_h, text_start_y,
        )

    try:
        video_clip = VideoClip(make_frame, duration=duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)
        video_clip = _set_dur(video_clip, min_dur)
        audio_clip = _subclip(audio_clip, 0, min_dur)

        # Mix bgm_hook.mp3 with fade-in: audio_fadein for 2s ramp, then fixed vol 0.12
        bgm_audio, bgm_path = _load_bgm("hook")
        if bgm_audio:
            try:
                bgm = _loop_audio(_vol(bgm_audio, 0.12), min_dur)
                fade_dur = min(2.0, min_dur * 0.3)
                # Use built-in audio_fadein (works in both MoviePy v1 and v2)
                try:
                    bgm = bgm.audio_fadein(fade_dur)
                except Exception:
                    pass  # fallback: no fade, fixed volume is fine
                bgm = _subclip(bgm, 0, min_dur)
                video_clip = _attach_audio(video_clip, CompositeAudioClip([audio_clip, bgm]))
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

    # img_01 → title card only; img_02+ → narration slides
    all_images = get_images_for_segment(segment_id, visuals_dir=visuals_dir)
    narration_images = get_images_for_segment(segment_id, visuals_dir=visuals_dir,
                                              narration_only=True)
    if not all_images:
        base_vdir = visuals_dir or VISUALS_DIR
        all_images = sorted(glob.glob(os.path.join(base_vdir, "*/*.jpg")))[:3]
        narration_images = all_images

    def _load(paths):
        out = []
        for p in paths:
            try:
                out.append(crop_fill(Image.open(p).convert("RGB"), width, height))
            except Exception:
                pass
        return out

    title_loaded = _load(all_images[:1])   # img_01 for title card
    narr_loaded = _load(narration_images)   # img_02+ for narration

    if not title_loaded and not narr_loaded:
        log.error("No images available for segment %s — run 04_fetch_visuals.py first", segment_id)
        sys.exit(1)

    # Fall back gracefully if one pool is empty
    if not title_loaded:
        title_loaded = narr_loaded[:1]
    if not narr_loaded:
        narr_loaded = title_loaded

    # Title text to display during narration of "Fact N: Heading."
    title_text = f"Fact {fact_n}: {heading}." if fact_n and heading else heading

    # Estimate title duration
    title_words = len(title_text.split())
    title_dur = max(2.0, title_words / 135 * 60)
    title_dur = min(title_dur, duration * 0.45)
    image_dur = duration - title_dur

    # Split narration into sentences and estimate per-sentence durations
    # (excluding the title sentence which is already counted in title_dur)
    narr_text = narration.strip()
    sentences = _re.split(r'(?<=[.!?])\s+', narr_text)
    # Skip title sentence (first sentence matches heading)
    body_sentences = sentences[1:] if len(sentences) > 1 else sentences
    if not body_sentences:
        body_sentences = [""]

    # Build sentence → image assignment (1 image per sentence, cycling through narr_loaded)
    n_imgs = len(narr_loaded) if narr_loaded else 1
    sent_word_counts = [max(1, len(s.split())) for s in body_sentences]
    total_words = sum(sent_word_counts)
    # Cumulative time offsets within image_dur
    sent_boundaries = [0.0]
    for wc in sent_word_counts:
        sent_boundaries.append(sent_boundaries[-1] + (wc / max(total_words, 1)) * image_dur)

    def _img_idx_at(local_t):
        for i, boundary in enumerate(sent_boundaries[1:]):
            if local_t < boundary:
                return i % n_imgs
        return (len(body_sentences) - 1) % n_imgs

    def make_frame(t):
        if t < title_dur:
            bc = title_loaded[0]
            img = _apply_ken_burns(bc, t, title_dur, width, height)
            return render_fact_title_frame(img, fact_n, heading, width, height)
        else:
            local_t = t - title_dur
            idx = _img_idx_at(local_t)
            bc = narr_loaded[idx]
            # Ken Burns resets per sentence for smooth zoom each image
            sent_start = sent_boundaries[idx] if idx < len(sent_boundaries) else 0
            sent_end = sent_boundaries[idx + 1] if idx + 1 < len(sent_boundaries) else image_dur
            seg_dur = max(sent_end - sent_start, 0.5)
            seg_t = local_t - sent_start
            img = _apply_ken_burns(bc, seg_t, seg_dur, width, height)
            return render_fact_image_frame(img, fact_n, width, height)

    try:
        video_clip = _set_dur(VideoClip(make_frame, duration=duration), duration)
        audio_clip = AudioFileClip(audio_path)
        min_dur = min(duration, audio_clip.duration)
        video_clip = _set_dur(video_clip, min_dur)
        audio_clip = _subclip(audio_clip, 0, min_dur)
        # BGM is NOT mixed here — applied once across the full facts section in render_with_moviepy
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

    if not images:
        log.error("No images available for outro — run 04_fetch_visuals.py first")
        sys.exit(1)
    base_img = Image.open(images[0]).convert("RGB")
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

    OUTRO_PAUSE = 1.0  # 1s silent pause before outro narration starts
    total_dur = duration + OUTRO_PAUSE

    def make_frame_outro(t):
        ct = max(0.0, t - OUTRO_PAUSE)
        img = _apply_ken_burns(base_cropped, ct, total_dur, width, height)
        arr = render_outro_frame(img, width, height)
        fade_start = max(0.0, total_dur - 1.5)
        if t >= fade_start:
            fade_frac = (t - fade_start) / 1.5
            arr = (np.array(arr, dtype=np.float32) * (1 - fade_frac)).clip(0, 255).astype(np.uint8)
        return arr

    try:
        video_clip = VideoClip(make_frame_outro, duration=total_dur)
        narr_clip = AudioFileClip(audio_path)
        narr_clip = _subclip(narr_clip, 0, min(duration, narr_clip.duration))

        # Prepend 1s silence then narration
        try:
            from moviepy import AudioClip as _AClip
            silence = _AClip(lambda t: [0, 0], duration=OUTRO_PAUSE, nchannels=2)
        except Exception:
            try:
                from moviepy.audio.AudioClip import AudioClip as _AClip
                silence = _AClip(lambda t: [0, 0], duration=OUTRO_PAUSE, nchannels=2)
            except Exception:
                silence = None

        bgm_audio, _ = _load_bgm("outro")
        if bgm_audio is None:
            bgm_audio, _ = _load_bgm("facts")

        audio_parts = []
        if silence:
            audio_parts.append(silence)
        audio_parts.append(narr_clip)

        try:
            from moviepy import concatenate_audioclips
        except ImportError:
            from moviepy.editor import concatenate_audioclips

        final_narr = concatenate_audioclips(audio_parts) if silence else narr_clip

        if bgm_audio:
            bgm = _vol(bgm_audio, 0.10)
            if bgm is not None:
                try:
                    if bgm.duration < total_dur:
                        loops = int(total_dur / bgm.duration) + 1
                        bgm = concatenate_audioclips([_vol(bgm_audio, 0.10)] * loops)
                    bgm = _subclip(bgm, 0, total_dur)
                    mixed = CompositeAudioClip([final_narr, bgm])
                    return _attach_audio(_set_dur(video_clip, total_dur), mixed)
                except Exception as exc:
                    log.warning("Outro BGM mix failed: %s", exc)

        return _attach_audio(_set_dur(video_clip, total_dur), final_narr)
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

def _make_black_transition(width: int, height: int, duration: float = 0.3):
    """Short black frame clip used between fact segments."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    return ImageClip(arr).with_duration(duration)


def _loop_audio(clip, duration: float):
    """Loop an audio clip to fill the given duration."""
    try:
        from moviepy import concatenate_audioclips
    except ImportError:
        from moviepy.editor import concatenate_audioclips
    if clip.duration >= duration:
        return _subclip(clip, 0, duration)
    loops = int(duration / clip.duration) + 2
    return _subclip(concatenate_audioclips([clip] * loops), 0, duration)


def _mix_bgm_onto_clip(video_clip, bgm_audio, volume: float, bgm_start: float = 0.0):
    """Overlay bgm_audio (starting at bgm_start offset) onto video_clip's audio."""
    dur = video_clip.duration
    try:
        bgm = _vol(bgm_audio, volume)
        if bgm is None:
            return video_clip
        # Start from bgm_start offset so continuous BGM doesn't restart
        bgm_seg = _subclip(bgm_audio, bgm_start, bgm_audio.duration)
        bgm_seg = _vol(bgm_seg, volume)
        bgm_seg = _loop_audio(bgm_seg, dur)
        bgm_seg = _subclip(bgm_seg, 0, dur)
        mixed = CompositeAudioClip([video_clip.audio, bgm_seg])
        return _attach_audio(video_clip, mixed)
    except Exception as exc:
        log.warning("BGM overlay failed: %s", exc)
        return video_clip


def render_with_moviepy(segments, output_path, width, height, bgm_path, visuals_dir=None):
    log.info("Using MoviePy renderer")

    hook_clips = []
    fact_clips = []
    outro_clips = []

    # Load facts BGM once — will be applied continuously across all facts
    facts_bgm, facts_bgm_path = _load_bgm("facts")
    if facts_bgm_path:
        log.info("Facts BGM: %s (applied continuously across all facts)", facts_bgm_path)

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
            if clip:
                hook_clips.append(clip)
        elif seg_id == "outro":
            clip = build_outro_clip(audio_path, width, height, visuals_dir)
            if clip:
                outro_clips.append(clip)
        else:
            clip = build_fact_clip(
                audio_path, seg_id, seg.get("narration", ""),
                width, height, fact_n=seg.get("fact_n"),
                heading=seg.get("heading", ""), visuals_dir=visuals_dir,
            )
            if clip:
                fact_clips.append(clip)

    if not hook_clips and not fact_clips and not outro_clips:
        log.error("No clips built")
        return False

    try:
        # Apply cross-fade transitions between fact clips
        XFADE = 0.4  # seconds overlap for cross-fade
        if len(fact_clips) > 1:
            try:
                xfaded = [fact_clips[0]]
                for c in fact_clips[1:]:
                    try:
                        faded = c.crossfadein(XFADE)
                    except AttributeError:
                        try:
                            from moviepy.video.fx.CrossFadeIn import CrossFadeIn
                            faded = CrossFadeIn(XFADE).apply(c)
                        except Exception:
                            faded = c
                    xfaded.append(faded)
                fact_clips = xfaded
            except Exception as exc:
                log.warning("Cross-fade setup failed, using plain concat: %s", exc)

        # Concatenate facts section, then overlay single continuous BGM
        if fact_clips and facts_bgm:
            facts_section = concatenate_videoclips(fact_clips, method="compose",
                                                   padding=-XFADE if len(fact_clips) > 1 else 0)
            facts_section = _mix_bgm_onto_clip(facts_section, facts_bgm, volume=0.09)
            all_clips = hook_clips + [facts_section] + outro_clips
        else:
            all_clips = hook_clips + fact_clips + outro_clips

        final = concatenate_videoclips(all_clips, method="compose")

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

        # 0.3s black transition
        save_still_seg(np.zeros((height, width, 3), dtype=np.uint8), None, 0.3)

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

    if not MOVIEPY_AVAILABLE:
        log.error("MoviePy not available. Run: pip install moviepy")
        sys.exit(1)
    if not PILLOW_AVAILABLE:
        log.error("Pillow not available. Run: pip install pillow numpy")
        sys.exit(1)

    success = render_with_moviepy(segments, output_path, width, height, bgm_path,
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
