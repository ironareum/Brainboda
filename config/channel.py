"""
Brainboda channel configuration.
"""

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

# Pixabay API (set your key in environment or here)
PIXABAY_API_KEY = "YOUR_PIXABAY_API_KEY"

# Pexels API (set your key in environment or here)
PEXELS_API_KEY = "YOUR_PEXELS_API_KEY"

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

# Upload schedule
UPLOAD_DAYS = ["Monday", "Wednesday", "Friday"]
UPLOAD_TIME = "18:00"  # UTC

# Paths
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

FACTS_RAW_CSV = os.path.join(DATA_DIR, "facts_raw.csv")
FACTS_APPROVED_CSV = os.path.join(DATA_DIR, "facts_approved.csv")
USED_FACTS_JSON = os.path.join(DATA_DIR, "used_facts.json")
