"""
Brainboda channel configuration.
"""

import os
from pathlib import Path

# Load .env from project root if present
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

CHANNEL_NAME = "Brainboda"
CHANNEL_LANGUAGE = "en"
CHANNEL_DESCRIPTION = "Psychology · Human Behavior · Success Mindset"

# TTS settings
TTS_VOICE_MALE = "en-US-GuyNeural"
TTS_VOICE_FEMALE = "en-US-JennyNeural"
TTS_VOICE_DEFAULT = TTS_VOICE_MALE

# Content settings
FACTS_PER_VIDEO = 10
FACTS_PER_SHORT = 3
VIDEO_CATEGORY_ID = "27"  # Education

# Wikipedia categories to scrape (English)
WIKIPEDIA_CATEGORIES = [
    "Cognitive_biases",
    "Social_psychology",
    "Psychological_manipulation",
    "Behavioural_sciences",
    "Personality_psychology",
    "Positive_psychology",
    "Neuropsychology",
    "Decision_making",
    "Persuasion",
    "Habit",
]

WIKIPEDIA_SEED_PAGES = [
    "Cognitive bias",
    "Social influence",
    "Anchoring (cognitive bias)",
    "Confirmation bias",
    "Dunning–Kruger effect",
    "Impostor syndrome",
    "Cognitive dissonance",
    "Loss aversion",
    "Priming (psychology)",
    "Placebo effect",
    "Hawthorne effect",
    "Bystander effect",
    "Fundamental attribution error",
    "Halo effect",
    "Availability heuristic",
    "Framing effect (psychology)",
    "Self-fulfilling prophecy",
    "Psychological manipulation",
    "Body language",
    "Habit",
    "Growth mindset",
    "Emotional intelligence",
    "Reciprocity (social psychology)",
    "Scarcity (social psychology)",
    "Social proof",
    "Authority (psychology)",
    "Liking (social psychology)",
    "Commitment and consistency",
    "Sunk cost",
    "Peak–end rule",
]

# API keys — set in .env (never hardcode here)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# Video settings
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
SHORT_WIDTH = 1080
SHORT_HEIGHT = 1920
FPS = 30
SECONDS_PER_FACT = 35  # average seconds per fact

# Thumbnail settings
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

# YouTube playlist
YOUTUBE_PLAYLIST_ID = "PLAs3NOlOTcp0"  # "How Your Mind Works"

# Upload schedule
UPLOAD_DAYS = ["Monday", "Wednesday", "Friday"]
UPLOAD_TIME = "18:00"  # UTC

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

FACTS_RAW_CSV = os.path.join(DATA_DIR, "facts_raw.csv")
FACTS_APPROVED_CSV = os.path.join(DATA_DIR, "facts_approved.csv")
USED_FACTS_JSON = os.path.join(DATA_DIR, "used_facts.json")
