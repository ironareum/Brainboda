"""
Step 3: Text-to-Speech narration using edge-tts.

Reads script JSON, generates MP3 files for each segment:
  output/audio/hook.mp3
  output/audio/fact_01.mp3 ... fact_10.mp3
  output/audio/outro.mp3
  output/audio/full_narration.mp3 (concatenated)

Skips segments that already exist (size > 0).
Falls back to silent audio if edge-tts is unavailable.

Usage:
    python pipeline/03_tts.py --script output/script_main_xxx.json
    python pipeline/03_tts.py --script output/script_main_xxx.json --voice en-US-JennyNeural
"""

import argparse
import asyncio
import glob
import json
import logging
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.channel import LOGS_DIR, OUTPUT_DIR, TTS_VOICE_DEFAULT

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"03_tts_{datetime.now():%Y%m%d_%H%M%S}.log")
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
    return "ffmpeg"  # fallback — will fail gracefully

FFMPEG_BIN = _find_ffmpeg()
log.info("ffmpeg binary: %s", FFMPEG_BIN)

# ── TTS helpers ───────────────────────────────────────────────────────────────

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    log.warning("edge-tts not installed. Will use silent audio fallback.")

try:
    from pydub import AudioSegment
    AudioSegment.converter = FFMPEG_BIN
    AudioSegment.ffmpeg = FFMPEG_BIN
    AudioSegment.ffprobe = FFMPEG_BIN.replace("ffmpeg", "ffprobe")
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    log.warning("pydub not installed. Concatenation will use ffmpeg subprocess.")


def file_exists_nonempty(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


def _write_silent_wav_as_mp3_stub(output_path: str, duration_ms: int) -> bool:
    """
    Write a silent WAV file using only stdlib struct/wave.
    Saves as .wav but renamed to .mp3 — ffmpeg-based players handle it;
    for pipeline testing this is sufficient.
    """
    import struct
    import wave
    import io

    sample_rate = 22050
    n_channels = 1
    sampwidth = 2  # 16-bit
    n_frames = int(sample_rate * duration_ms / 1000)
    wav_path = output_path + ".wav"
    try:
        with wave.open(wav_path, "w") as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00" * n_frames * n_channels * sampwidth)

        # Try converting WAV→MP3 via ffmpeg
        result = subprocess.run(
            [FFMPEG_BIN, "-y", "-i", wav_path, "-acodec", "libmp3lame",
             "-b:a", "64k", output_path],
            capture_output=True, timeout=30
        )
        os.unlink(wav_path)
        if result.returncode == 0 and file_exists_nonempty(output_path):
            log.info("  [wav→mp3] Silent audio: %s (%dms)", output_path, duration_ms)
            return True
        # If ffmpeg conversion failed, just use the WAV as-is (renamed)
        import shutil
        shutil.move(wav_path, output_path)
        log.info("  [wav fallback] Silent WAV saved as: %s (%dms)", output_path, duration_ms)
        return file_exists_nonempty(output_path)
    except Exception as exc:
        log.error("Silent WAV fallback failed: %s", exc)
        return False


async def synthesize_edge_tts(text: str, output_path: str, voice: str) -> bool:
    """Synthesize text to MP3 using edge-tts. Returns True on success."""
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        if file_exists_nonempty(output_path):
            log.info("  [edge-tts] Saved: %s (%.1f KB)", output_path, os.path.getsize(output_path) / 1024)
            return True
        return False
    except Exception as exc:
        log.warning("  [edge-tts] Failed: %s — %s", output_path, exc)
        return False


def generate_silent_mp3(output_path: str, duration_ms: int = 3000) -> bool:
    """Generate a silent MP3 of given duration as fallback."""
    if not PYDUB_AVAILABLE:
        # Use ffmpeg directly
        import subprocess
        duration_sec = duration_ms / 1000
        cmd = [
            FFMPEG_BIN, "-y", "-f", "lavfi", "-i",
            "anullsrc=r=44100:cl=mono", "-t", str(duration_sec),
            "-acodec", "libmp3lame", "-b:a", "64k", output_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            return result.returncode == 0 and file_exists_nonempty(output_path)
        except Exception as exc:
            log.error("ffmpeg silent fallback failed: %s", exc)
            return False
    else:
        try:
            # Try pydub export via the resolved ffmpeg
            silent = AudioSegment.silent(duration=duration_ms)
            silent.export(output_path, format="mp3")
            log.info("  [fallback] Silent audio: %s (%dms)", output_path, duration_ms)
            return True
        except Exception as exc:
            log.warning("pydub silent fallback failed: %s — trying raw WAV", exc)
            # Last resort: write a minimal silent WAV file (no external tools needed)
            return _write_silent_wav_as_mp3_stub(output_path, duration_ms)


async def synthesize_segment(text: str, output_path: str, voice: str, duration_est: int) -> bool:
    """Try edge-tts first, fall back to silent audio."""
    if file_exists_nonempty(output_path):
        log.info("  [skip] Already exists: %s", os.path.basename(output_path))
        return True

    if EDGE_TTS_AVAILABLE:
        success = await synthesize_edge_tts(text, output_path, voice)
        if success:
            return True
        log.warning("  edge-tts failed, using silent fallback")

    # Fallback: silent audio for estimated duration
    duration_ms = max(duration_est * 1000, 2000)
    return generate_silent_mp3(output_path, duration_ms)


def concatenate_audio(input_paths: list, output_path: str) -> bool:
    """Concatenate MP3 files using pydub or ffmpeg."""
    if file_exists_nonempty(output_path):
        log.info("  [skip] full_narration.mp3 already exists")
        return True

    existing = [p for p in input_paths if file_exists_nonempty(p)]
    if not existing:
        log.warning("No audio segments to concatenate")
        return False

    if PYDUB_AVAILABLE:
        try:
            combined = AudioSegment.empty()
            for path in existing:
                seg = AudioSegment.from_mp3(path)
                combined += seg
            combined.export(output_path, format="mp3")
            log.info("Concatenated %d segments → %s (%.1f MB)",
                     len(existing), output_path, os.path.getsize(output_path) / (1024 * 1024))
            return True
        except Exception as exc:
            log.warning("pydub concat failed: %s — trying ffmpeg", exc)

    # ffmpeg fallback
    import subprocess
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            list_file = f.name
            for p in existing:
                f.write(f"file '{os.path.abspath(p)}'\n")
        cmd = [FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
               "-acodec", "libmp3lame", "-b:a", "128k", output_path]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        os.unlink(list_file)
        if result.returncode == 0 and file_exists_nonempty(output_path):
            log.info("ffmpeg concat succeeded → %s", output_path)
            return True
        log.error("ffmpeg concat failed: %s", result.stderr.decode())
        return False
    except Exception as exc:
        log.error("ffmpeg concat exception: %s", exc)
        return False


# ── main logic ────────────────────────────────────────────────────────────────

async def run_tts(script_path: str, voice: str) -> dict:
    """Generate all audio segments. Returns dict of {segment_name: file_path}."""
    log.info("Loading script: %s", script_path)
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    results = {}

    # Hook
    hook_path = os.path.join(AUDIO_DIR, "hook.mp3")
    ok = await synthesize_segment(script["hook"], hook_path, voice, script.get("hook_duration_est", 20))
    if ok:
        results["hook"] = hook_path

    # Facts
    for fact in script["facts"]:
        n = fact["n"]
        fact_path = os.path.join(AUDIO_DIR, f"fact_{n:02d}.mp3")
        ok = await synthesize_segment(fact["narration"], fact_path, voice, fact.get("duration_est", 30))
        if ok:
            results[f"fact_{n:02d}"] = fact_path

    # Outro
    outro_path = os.path.join(AUDIO_DIR, "outro.mp3")
    ok = await synthesize_segment(script["outro"], outro_path, voice, script.get("outro_duration_est", 20))
    if ok:
        results["outro"] = outro_path

    # Concatenate full narration
    ordered = []
    if "hook" in results:
        ordered.append(results["hook"])
    for i in range(1, len(script["facts"]) + 1):
        key = f"fact_{i:02d}"
        if key in results:
            ordered.append(results[key])
    if "outro" in results:
        ordered.append(results["outro"])

    full_path = os.path.join(AUDIO_DIR, "full_narration.mp3")
    concatenate_audio(ordered, full_path)
    if file_exists_nonempty(full_path):
        results["full_narration"] = full_path

    return results


def find_latest_script(output_dir: str, video_type: str = None) -> str | None:
    """Find the most recently modified script JSON in output/."""
    pattern = os.path.join(output_dir, "script_*.json")
    if video_type:
        pattern = os.path.join(output_dir, f"script_{video_type}_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def main():
    parser = argparse.ArgumentParser(description="TTS: Generate MP3 narration from script JSON")
    parser.add_argument("--script", type=str, default=None,
                        help="Path to script JSON. If omitted, uses latest in output/")
    parser.add_argument("--voice", type=str, default=TTS_VOICE_DEFAULT,
                        help="edge-tts voice name")
    args = parser.parse_args()

    log.info("=== 03_tts.py START ===")

    # Resolve script path
    script_path = args.script
    if not script_path:
        script_path = find_latest_script(OUTPUT_DIR)
        if not script_path:
            log.error("No script JSON found in %s — run 02_build_script.py first", OUTPUT_DIR)
            sys.exit(1)
        log.info("Auto-detected latest script: %s", script_path)

    if not os.path.exists(script_path):
        log.error("Script not found: %s", script_path)
        sys.exit(1)

    log.info("Voice: %s", args.voice)
    log.info("Audio output dir: %s", AUDIO_DIR)

    results = asyncio.run(run_tts(script_path, args.voice))

    log.info("=== 03_tts.py DONE ===")

    print(f"\n{'='*60}")
    print(f"  TTS complete — {len(results)} audio segments")
    print(f"  Output dir: {AUDIO_DIR}")
    print(f"{'='*60}")
    for name, path in sorted(results.items()):
        size_kb = os.path.getsize(path) / 1024 if os.path.exists(path) else 0
        print(f"  {name:<20} {path} ({size_kb:.0f} KB)")

    return results


if __name__ == "__main__":
    main()
