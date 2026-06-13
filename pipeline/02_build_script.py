"""
Step 2: Build video script from facts.

Mode A (default): Wikipedia-based — reads facts_raw.csv, selects N facts.
Mode B (--ai):    AI-generated — gives a theme to Claude, gets full script back.

Usage:
    python pipeline/02_build_script.py --type main
    python pipeline/02_build_script.py --type main --ai --theme "dark psychology"
    python pipeline/02_build_script.py --type short --ai --theme "cognitive biases"
    python pipeline/02_build_script.py --dry-run
"""

import argparse
import csv
import json
import logging
import os
import random
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.channel import (
    ANTHROPIC_API_KEY,
    FACTS_APPROVED_CSV,
    FACTS_RAW_CSV,
    FACTS_PER_SHORT,
    FACTS_PER_VIDEO,
    LOGS_DIR,
    OUTPUT_DIR,
    USED_FACTS_JSON,
)

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"02_build_script_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── title templates ───────────────────────────────────────────────────────────

MAIN_TITLE_TEMPLATES = [
    "{n} Psychological Facts That Will Change How You See People",
    "{n} Psychology Tricks Your Brain Plays On You Every Day",
    "{n} Mind-Blowing Facts About Human Behavior (Backed by Science)",
    "{n} Psychological Facts Most People Don't Know About Themselves",
    "{n} Disturbing Psychology Facts That Explain Human Behavior",
    "{n} Dark Psychology Facts That Will Make You Think Twice",
    "{n} Incredible Psychology Facts About the Human Mind",
    "{n} Psychological Secrets Rich and Successful People Know",
    "{n} Shocking Psychology Facts Science Has Proven",
    "{n} Hidden Psychology Facts That Explain Why You Do What You Do",
]

SHORT_TITLE_TEMPLATES = [
    "This Psychology Fact Will Shock You 🧠 #psychology #mindset",
    "Your Brain Is Lying To You Right Now #cognitivebias #psychology",
    "The {fact_title} Explained In 60 Seconds #psychology #facts",
    "Science Proved This About Your Brain #neuroscience #psychology",
    "Why Your Brain Sabotages You (Psychology Explained) #mindset",
]

HOOK_TEMPLATES = [
    "Did you know that {hook_fact}? Stay until the end — because fact #{hook_n} will completely change how you see people.",
    "Scientists have discovered something shocking about the human mind. {hook_fact} And that's just the beginning.",
    "Your brain is lying to you right now. {hook_fact} In this video, we reveal {n} psychology facts that will change everything.",
    "What if everything you believed about yourself was shaped by hidden mental forces? {hook_fact} Let's dive in.",
    "The human brain is the most complex object in the known universe — and it's full of secrets. {hook_fact} Here are {n} facts you need to know.",
]

OUTRO_TEMPLATES = [
    "Which fact surprised you the most? Let me know in the comments below. And if you found this fascinating, subscribe — we post new psychology facts every week.",
    "So which of these {n} facts hit the hardest? Drop it in the comments. Subscribe to Brainboda for more mind-expanding psychology content every week.",
    "Now you know {n} psychology secrets that most people never discover. Share this with someone who needs to hear it — and subscribe for more every week.",
    "The human mind is endlessly fascinating. Which fact are you going to think about today? Comment below, and hit subscribe so you never miss an episode.",
]

TRANSITION_PHRASES = [
    "This means that",
    "In practice, this means",
    "What this tells us is",
    "For you, this means",
    "In real life, this translates to",
    "The practical takeaway here is",
    "What's remarkable about this is",
]

# ── helpers ───────────────────────────────────────────────────────────────────

def load_used_ids() -> set[str]:
    if not os.path.exists(USED_FACTS_JSON):
        return set()
    try:
        with open(USED_FACTS_JSON) as f:
            data = json.load(f)
        return set(data.get("used_ids", []))
    except Exception:
        return set()


def save_used_ids(ids: set[str]) -> None:
    existing = load_used_ids()
    merged = existing | ids
    with open(USED_FACTS_JSON, "w") as f:
        json.dump({"used_ids": sorted(merged)}, f, indent=2)


PSYCHOLOGY_KEYWORDS = [
    "psychology", "psychological", "psycholog",
    "behavior", "behaviour", "cognitive", "cognition",
    "brain", "neuroscience", "neural", "mental health",
    "bias", "heuristic", "emotion",
    "memory", "perception", "personality", "motivation",
    "anxiety", "depression", "stress", "trauma",
    "self-esteem", "consciousness",
    "therapy", "therapist", "psychiatry", "psychoanalysis",
    "mindset", "prophecy", "attitude",
]

REJECT_IDS = {
    # Non-psychology fields / organizations / journals
    "4or", "19_to_zero", "animal_studies", "anthropology",
    "black_american_anthropology",
    "association_for_behavior_analysis_international",
    "association_for_contextual_behavioral_science",
    "cog_s_ladder", "ghost_job", "phantom_job",
    "behavioral_science___policy",
    "black_manosphere", "attention_inequality", "honey_trapping",
    "amity_enmity_complex", "blame", "blame_in_organizations",
    "sunk_cost", "aesthetic_usability_effect",
    # Duplicates
    "anchoring__cognitive_bias_", "anchoring_effect",
    "priming__psychology_", "framing_effect__psychology_",
    "habit", "reciprocity__social_psychology_", "scarcity__social_psychology_",
    # Too broad / not a fact
    "list_of_cognitive_biases", "social_psychology",
    # Non-psychology topics
    "behavior_imaging", "behavior_informatics",
    "behavioral_urbanism", "barriers_to_pro_environmental_behaviour",
    "intimidation",
}

REJECT_BODY_PHRASES = [
    "recently recognised field",
    "field within anthropology",
    "operations research",
    "hosted at the university of calgary",
    "nonprofit professional membership organization",
    "nonprofit organization dedicated to promoting",
]

def is_psychology_relevant(fact: dict) -> bool:
    fact_id = fact.get("id", "").lower()
    title = fact.get("title", "").lower()
    body = fact.get("body", "").lower()

    if fact_id in REJECT_IDS:
        return False
    if any(phrase in body for phrase in REJECT_BODY_PHRASES):
        return False

    text = title + " " + body
    return any(kw in text for kw in PSYCHOLOGY_KEYWORDS)


def load_available_facts(topic: str | None = None) -> list[dict]:
    """Load facts from approved CSV (preferred) or raw CSV, filtered by used IDs."""
    used_ids = load_used_ids()

    # Prefer approved facts if file exists and has data
    source = FACTS_RAW_CSV
    if os.path.exists(FACTS_APPROVED_CSV) and os.path.getsize(FACTS_APPROVED_CSV) > 10:
        source = FACTS_APPROVED_CSV
        log.info("Using approved facts: %s", source)
    else:
        log.info("Using raw facts: %s", source)

    facts: list[dict] = []
    try:
        with open(source, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["id"] in used_ids:
                    continue
                if topic and topic.lower() not in (row["title"] + row["body"]).lower():
                    continue
                if not is_psychology_relevant(row):
                    log.debug("Quality filter rejected: %s", row.get("title", ""))
                    continue
                facts.append(row)
    except FileNotFoundError:
        log.error("Facts CSV not found: %s — run 01_fetch_facts.py first", source)

    log.info("Available (unused) facts: %d", len(facts))
    return facts


def pick_facts(facts: list[dict], n: int, topic: str | None) -> list[dict]:
    """Pick N facts, shuffled. If topic-filtered pool is too small, fill from all."""
    if len(facts) < n:
        log.warning("Only %d facts available, need %d", len(facts), n)
        n = len(facts)
    shuffled = facts.copy()
    random.shuffle(shuffled)
    return shuffled[:n]


def derive_application(body: str) -> str:
    """Extract or synthesize a 'real-life application' closing sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", body.strip())
    # Look for a sentence that already contains application language
    app_keywords = ["means", "explains", "shows", "tells", "proves", "suggests", "practical"]
    for s in reversed(sentences):
        if any(kw in s.lower() for kw in app_keywords) and len(s) > 40:
            return s
    # Fallback: rephrase the last sentence
    last = sentences[-1] if sentences else body
    transition = random.choice(TRANSITION_PHRASES)
    # Strip leading connector if already present
    last_clean = re.sub(r"^(This means|This shows|This tells us)[^,]*,?\s*", "", last, flags=re.IGNORECASE)
    return f"{transition} {last_clean[0].lower()}{last_clean[1:]}"


def build_narration(fact: dict, n: int) -> str:
    """Build the full spoken narration for one fact."""
    heading = fact["title"]
    body = fact["body"].strip()

    # Remove trailing application sentence from body if we'll derive one separately
    sentences = re.split(r"(?<=[.!?])\s+", body)
    core = " ".join(sentences[:-1]) if len(sentences) > 1 else body
    application = derive_application(body)

    narration = f"Fact {n}: {heading}. {core} {application}"
    return narration.strip()


def estimate_duration(text: str, wpm: int = 150) -> int:
    """Estimate spoken duration in seconds at given words-per-minute."""
    words = len(text.split())
    return max(20, round(words / wpm * 60))


def build_hook(facts: list[dict], n_total: int) -> str:
    """Pick the most striking fact for the hook teaser."""
    # Use fact at index 2 (fact #3) for the hook reference as per spec
    hook_fact_idx = min(2, len(facts) - 1)
    hook_fact = facts[hook_fact_idx]

    # Extract a punchy first sentence from the hook fact
    first_sentence = re.split(r"(?<=[.!?])\s+", hook_fact["body"])[0]

    template = random.choice(HOOK_TEMPLATES)
    hook = template.format(
        hook_fact=first_sentence,
        hook_n=hook_fact_idx + 1,
        n=n_total,
    )
    return hook


def build_script(
    facts: list[dict],
    video_type: str = "main",
) -> dict:
    """Assemble the full script dictionary."""
    n = len(facts)

    # Title
    if video_type == "short":
        title_tpl = random.choice(SHORT_TITLE_TEMPLATES)
        title = title_tpl.format(fact_title=facts[0]["title"], n=n)
    else:
        title_tpl = random.choice(MAIN_TITLE_TEMPLATES)
        title = title_tpl.format(n=n)

    # Hook
    hook = build_hook(facts, n)

    # Fact narrations
    fact_blocks = []
    for i, fact in enumerate(facts, 1):
        narration = build_narration(fact, i)
        fact_blocks.append({
            "n": i,
            "id": fact["id"],
            "heading": fact["title"],
            "source_url": fact.get("source_url", ""),
            "narration": narration,
            "key_insight": build_key_insight(fact["title"], fact["body"]),
            "duration_est": estimate_duration(narration),
            "search_keywords": _visual_keywords(fact),
        })

    # Outro
    outro_tpl = random.choice(OUTRO_TEMPLATES)
    outro = outro_tpl.format(n=n)

    # Total duration estimate
    hook_dur = estimate_duration(hook)
    outro_dur = estimate_duration(outro)
    total_dur = hook_dur + sum(b["duration_est"] for b in fact_blocks) + outro_dur

    # Description
    description = _build_description(title, fact_blocks, hook_dur=hook_dur)

    # Tags
    tags = _build_tags(facts)

    thumbnail_hook = _build_thumbnail_hook(title, hook, facts)

    return {
        "type": video_type,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "thumbnail_hook": thumbnail_hook,
        "hook": hook,
        "hook_duration_est": hook_dur,
        "facts": fact_blocks,
        "outro": outro,
        "outro_duration_est": outro_dur,
        "total_duration_est": total_dur,
        "description": description,
        "tags": tags,
    }


def build_key_insight(title: str, body: str) -> str:
    """Generate a 5-8 word punchy key insight for on-screen display."""
    import re as _re

    # Prefer sentences with numbers/percentages — most impactful
    sentences = _re.split(r'(?<=[.!?])\s+', body.strip())
    number_pattern = _re.compile(r'\b\d+[\d.,]*\s*(%|x|times|percent|fold|people|out of|seconds?|minutes?|hours?|days?|years?)\b', _re.IGNORECASE)

    best = None
    for s in sentences:
        if number_pattern.search(s) and 30 <= len(s) <= 200:
            best = s
            break

    if not best:
        # Fall back to the second sentence (usually the core claim)
        for s in sentences[1:]:
            if len(s) > 30:
                best = s
                break
    if not best:
        best = sentences[0] if sentences else title

    # Extract a short clause: split on comma/dash/colon and pick the punchiest part
    parts = _re.split(r'[,;—–]', best)
    parts = [p.strip() for p in parts if len(p.strip()) > 15]

    # Score parts: prefer ones with numbers or strong psychology words
    power_words = ["effect", "bias", "paradox", "fact", "people", "times", "more", "less", "never", "always", "actually", "proven", "shows", "found"]
    def score(p):
        p_low = p.lower()
        return sum(1 for w in power_words if w in p_low) + (3 if number_pattern.search(p) else 0)

    parts_sorted = sorted(parts, key=score, reverse=True)
    chosen = parts_sorted[0] if parts_sorted else best

    # Trim to 5-8 words
    words = chosen.split()
    if len(words) > 8:
        # Try to find a natural cut point within 5-8 words
        short = " ".join(words[:7])
        # Remove trailing preposition/conjunction
        short = _re.sub(r'\s+(a|an|the|and|or|but|in|on|of|to|is|are|was|were|that|which)\s*$', '', short, flags=_re.IGNORECASE)
        chosen = short.strip()
    elif len(words) < 4:
        # Pad with title if too short
        chosen = title

    # Capitalize first letter
    if chosen:
        chosen = chosen[0].upper() + chosen[1:]

    return chosen


def _build_thumbnail_hook(title: str, hook: str, facts: list) -> str:
    """Generate a short 5-7 word punchy hook line for the thumbnail."""
    import re as _re

    # Patterns: "Your Brain...", "You Actually...", "Science Proved...", "Most People..."
    STARTERS = [
        "Your Brain Does This Daily",
        "You Do This Without Knowing",
        "Science Proved This About You",
        "Most People Never Know This",
        "Your Mind Lies To You Daily",
    ]

    # Extract a strong keyword from the title
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "of", "to",
                  "that", "this", "is", "are", "was", "were", "be", "been",
                  "facts", "fact", "psychological", "psychology", "hidden", "dark",
                  "incredible", "shocking", "mind-blowing", "disturbing"}
    title_words = [w.strip(".,!?\"'") for w in title.split() if w.lower().strip(".,!?\"'") not in stop_words and len(w) > 3]

    # Try to build a hook around the best topic word
    power_phrases = [
        ("bias", "Your Brain Has a Hidden Bias"),
        ("manipul", "People Are Being Manipulated"),
        ("fear", "Fear Controls Your Decisions"),
        ("memory", "Your Memories Are Fabricated"),
        ("success", "Success Rewires Your Brain"),
        ("decision", "You Make Decisions Unconsciously"),
        ("social", "Social Pressure Shapes Your Mind"),
        ("emotion", "Emotions Override Your Logic"),
        ("habit", "Habits Control Your Every Move"),
        ("trust", "Your Brain Decides Who To Trust"),
        ("stress", "Stress Changes Your Brain Daily"),
        ("sleep", "Sleep Deprivation Warps Reality"),
        ("conform", "You Conform Without Realizing It"),
        ("reward", "Your Brain Craves Instant Rewards"),
        ("dark", "The Dark Side of Human Psychology"),
        ("lie", "Your Brain Lies To You Constantly"),
    ]

    title_lower = title.lower()
    hook_lower = hook.lower()
    combined = title_lower + " " + hook_lower

    for keyword, phrase in power_phrases:
        if keyword in combined:
            return phrase

    # Fallback: use first fact title to build a hook
    if facts:
        fact_title = facts[0].get("title", "")
        words = [w for w in fact_title.split() if len(w) > 3][:3]
        if words:
            return f"The Hidden Truth About {' '.join(words[:2])}"

    # Last resort: use a random starter
    import random
    return random.choice(STARTERS)


def _visual_keywords(fact: dict) -> list[str]:
    """Keywords for image search (Pixabay/Pexels) for this fact."""
    base = ["brain", "psychology", "mind", "human behavior"]
    title_words = [w.lower() for w in fact["title"].split() if len(w) > 4]
    return (title_words + base)[:5]


def _fmt_ts(seconds: float) -> str:
    """Format seconds as M:SS timestamp."""
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _build_description(title: str, facts: list[dict], hook_dur: float = 20.0) -> str:
    # Build timestamps
    ts_lines = ["⏱️ TIMESTAMPS", f"0:00 - Introduction"]
    cursor = hook_dur
    for i, b in enumerate(facts, 1):
        ts_lines.append(f"{_fmt_ts(cursor)} - Fact {i}: {b['heading']}")
        cursor += b.get("duration_est", 30.0)
    ts_lines.append(f"{_fmt_ts(cursor)} - Outro")

    lines = [
        title,
        "",
        "In this video, we explore fascinating psychology facts backed by science that reveal how the human mind really works.",
        "",
        "\n".join(ts_lines),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🧠 Subscribe to Brainboda for weekly psychology insights.",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🎵 Music: Pixabay Music (https://pixabay.com/music/)",
        "License: Pixabay Content License — Free for commercial use, no attribution required.",
        "",
        "#psychology #humanbehavior #mindset #cognitivebias #brainboda #selfimprovement #mentalhealth #neuroscience",
    ]
    return "\n".join(lines)


def _build_tags(facts: list[dict]) -> list[str]:
    base = [
        "psychology", "human behavior", "mind", "brain", "cognitive bias",
        "self improvement", "neuroscience", "mindset", "mental health",
        "psychology facts", "brainboda",
    ]
    fact_tags = [f["title"].lower() for f in facts]
    all_tags = fact_tags + base
    seen: set[str] = set()
    return [t for t in all_tags if not (t in seen or seen.add(t))][:30]  # type: ignore[func-returns-value]


# ── AI script generation (Method B) ──────────────────────────────────────────

_USED_CONCEPTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "used_concepts.json"
)

_USED_SHORTS_FACTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "used_shorts_facts.json"
)


def _load_used_shorts_facts() -> list:
    try:
        with open(_USED_SHORTS_FACTS_PATH, encoding="utf-8") as f:
            return json.load(f).get("headings", [])
    except Exception:
        return []


def _save_used_shorts_facts(headings: list):
    os.makedirs(os.path.dirname(_USED_SHORTS_FACTS_PATH), exist_ok=True)
    with open(_USED_SHORTS_FACTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"headings": headings}, f, indent=2, ensure_ascii=False)

_DEFAULT_THEMES = [
    "dark psychology", "cognitive biases", "social influence",
    "manipulation tactics", "memory and learning", "personality psychology",
    "decision making", "habit formation", "emotional intelligence",
    "unconscious behavior", "relationship psychology", "fear and anxiety",
]

_AI_SYSTEM_PROMPT = """\
You are a YouTube script writer for "Brainboda" — a science-based educational channel.

RULES:
- Conversational English, not academic. Write like talking to a curious friend.
- Every fact must be a REAL, named concept (e.g. "Dunning-Kruger Effect", "Dark Triad").
- Cite the actual researcher or origin where known (e.g. "coined by psychologist Robert Cialdini in 1984").
- NEVER fabricate statistics, percentages, or study results.
- If uncertain about specifics, describe the concept generally — no fake citations.
- Each fact narration: 80-120 words. Must start with "Fact N: [Concept Name].".
- End each fact with one sentence on why it matters in the viewer's real life.
- Hook: 40-60 words. MUST follow this structure:
    1. Open with a shocking statistic OR a bold counterintuitive claim (makes viewer stop scrolling).
    2. One sentence that deepens the mystery or raises the stakes.
    3. End with a direct question that pulls the viewer in (e.g. "So why does your brain do this?").
  The hook must NOT mention any concept by name — tease the theme only.
- Make facts feel surprising, counterintuitive, or unsettling in a thought-provoking way.
- Facts should flow with a loose narrative arc: start relatable, build intensity, end impactful.

OUTPUT: Return valid JSON only. No explanation, no markdown fences, no text outside the JSON.\
"""

_AI_USER_PROMPT = """\
Create a YouTube script for a {video_type} video about: "{theme}"

Number of facts: {n_facts}

Previously used concepts for this theme — DO NOT repeat these:
{used_concepts}

Return this exact JSON structure:
{{
  "title": "catchy YouTube title including the number of facts",
  "thumbnail_hook": "5-6 word punchy phrase for thumbnail",
  "hook": "...",
  "facts": [
    {{
      "n": 1,
      "heading": "Real Concept Name",
      "narration": "Fact 1: Real Concept Name. ...",
      "search_keywords": ["keyword1", "keyword2", "keyword3"]
    }}
  ],
  "outro": "engagement CTA — ask viewers to comment which fact hit hardest, subscribe",
  "tags": ["tag1", "tag2", "...up to 20 tags"]
}}\
"""


def _load_used_concepts() -> dict:
    try:
        with open(_USED_CONCEPTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_used_concepts(data: dict):
    os.makedirs(os.path.dirname(_USED_CONCEPTS_PATH), exist_ok=True)
    with open(_USED_CONCEPTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _pick_theme(requested: str | None, used_concepts: dict) -> str:
    if requested:
        return requested.lower().strip()
    # Auto-pick: prefer themes with fewest used concepts
    scored = sorted(_DEFAULT_THEMES, key=lambda t: len(used_concepts.get(t, [])))
    return scored[0]


def build_script_ai(theme: str, video_type: str, n_facts: int,
                    dry_run: bool = False) -> dict | None:
    """Call Claude Haiku to generate a full script for the given theme."""
    try:
        import anthropic
    except ImportError:
        log.error("anthropic package not installed. Run: pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
    if not api_key or api_key == "YOUR_ANTHROPIC_API_KEY":
        log.error("ANTHROPIC_API_KEY not set. Export it or add to environment.")
        sys.exit(1)

    used_concepts = _load_used_concepts()
    theme_key = theme.lower().strip()
    used_for_theme = used_concepts.get(theme_key, [])
    used_str = ", ".join(used_for_theme) if used_for_theme else "none yet"

    user_prompt = _AI_USER_PROMPT.format(
        video_type=video_type,
        theme=theme,
        n_facts=n_facts,
        used_concepts=used_str,
    )

    log.info("Calling Claude Haiku | theme: %s | n_facts: %d", theme, n_facts)
    log.info("Previously used concepts for this theme: %s", used_str)

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4096,
            system=_AI_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        log.debug("AI raw response (first 300 chars): %s", raw[:300])
    except Exception as exc:
        log.error("Claude API call failed: %s", exc)
        return None

    # Parse JSON
    try:
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        script_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse AI response as JSON: %s", exc)
        log.error("Raw response: %s", raw[:500])
        return None

    # Inject standard fields
    script_data["type"] = video_type
    script_data["created_at"] = datetime.now().isoformat(timespec="seconds")
    script_data["ai_generated"] = True
    script_data["theme"] = theme

    # Estimate durations
    hook_dur = estimate_duration(script_data.get("hook", ""))
    outro_dur = estimate_duration(script_data.get("outro", ""))
    for fact in script_data.get("facts", []):
        fact["duration_est"] = estimate_duration(fact.get("narration", ""))
        fact["id"] = re.sub(r"[^a-z0-9]+", "_", fact["heading"].lower()).strip("_")
        fact["source_url"] = ""
        fact["key_insight"] = ""
    script_data["hook_duration_est"] = hook_dur
    script_data["outro_duration_est"] = outro_dur
    script_data["total_duration_est"] = (
        hook_dur + sum(f["duration_est"] for f in script_data["facts"]) + outro_dur
    )

    # Build description
    script_data["description"] = _build_description(
        script_data["title"], script_data["facts"],
        hook_dur=script_data.get("hook_duration_est", 20.0)
    )

    # Track used concepts
    if not dry_run:
        new_concepts = [f["heading"] for f in script_data["facts"]]
        used_concepts.setdefault(theme_key, [])
        for c in new_concepts:
            if c not in used_concepts[theme_key]:
                used_concepts[theme_key].append(c)
        _save_used_concepts(used_concepts)
        log.info("Saved %d concepts to used_concepts.json (theme: %s)",
                 len(new_concepts), theme_key)

    return script_data


def _pick_best_fact(facts: list) -> dict:
    """Pick most impactful fact heuristically — longest narration tends to be most developed."""
    return max(facts, key=lambda f: len(f.get("narration", "")))


_SHORTS_TEASER_PROMPT = """\
You are writing a YouTube Shorts script for "Brainboda" — a psychology education channel.

The goal: tease ONE psychology fact to make viewers curious enough to watch the full video.

CONCEPT: {concept}
CONCEPT SUMMARY: {summary}

Write a script with exactly 3 parts:

1. HOOK (10-15 seconds / ~30-40 words):
   - Open with a surprising or counterintuitive question or claim related to the concept.
   - Do NOT name the concept yet. Just tease the idea.
   - Example style: "Did you know your brain actively rewrites your memories every time you recall them?"

2. TEASER (25-35 seconds / ~65-90 words):
   - Partially reveal the concept — give just enough to be fascinating.
   - Name the concept (e.g. "This is called the {concept}.").
   - Explain what it is in 1-2 sentences, but leave out the full detail / real-world impact.
   - End with an open question that makes them NEED to know more.
   - Example ending: "But here's where it gets really dark — what does this mean for every decision you make?"

3. CTA (5-8 seconds / ~15-20 words):
   - Direct call to action to watch the full Brainboda video.
   - Example: "Watch the full breakdown on Brainboda — link in bio. You won't look at yourself the same way."

RULES:
- Conversational English, like talking to a curious friend.
- Total script: 45-65 seconds when read aloud (~110-150 words).
- NEVER fabricate statistics or studies.
- Return ONLY valid JSON, no markdown, no extra text.

Return this exact JSON:
{{
  "hook": "...",
  "teaser": "...",
  "cta": "..."
}}\
"""


def _generate_short_teaser_ai(concept: str, summary: str) -> dict | None:
    """Call Claude Haiku to generate hook/teaser/cta for a Shorts video."""
    try:
        import anthropic
    except ImportError:
        log.error("anthropic package not installed.")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
    if not api_key or api_key == "YOUR_ANTHROPIC_API_KEY":
        log.error("ANTHROPIC_API_KEY not set.")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _SHORTS_TEASER_PROMPT.format(concept=concept, summary=summary)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")
        return json.loads(raw)
    except Exception as exc:
        log.error("Claude API call failed for Shorts teaser: %s", exc)
        return None


def _build_short_description(concept: str, main_script_path: str) -> str:
    tags = "#psychology #shorts #brainboda #humanbehavior #mindset #neuroscience #psychologyfacts"
    return "\n".join([
        f"{concept} — Psychology Short | Brainboda",
        "",
        f"Watch the full video for the complete breakdown of {concept} and more mind-bending psychology facts.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🧠 Subscribe to Brainboda for weekly psychology insights.",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        tags,
    ])


def build_script_short_from_main(main_script_path: str, run_dir: str,
                                  dry_run: bool = False) -> dict | None:
    """Build a Shorts teaser script from one fact in the main script, using AI."""
    with open(main_script_path, encoding="utf-8") as f:
        main_script = json.load(f)

    main_facts = main_script.get("facts", [])
    if not main_facts:
        log.error("Main script has no facts.")
        return None

    used_headings = _load_used_shorts_facts()
    available_facts = [f for f in main_facts if f["heading"] not in used_headings]
    if not available_facts:
        log.warning("All facts from this main already used as Shorts — resetting pool.")
        available_facts = main_facts

    chosen = _pick_best_fact(available_facts)
    concept = chosen["heading"]
    summary = chosen.get("narration", chosen.get("key_insight", ""))
    log.info("Short chosen fact: %s", concept)

    # Use AI to write a teaser script
    teaser = _generate_short_teaser_ai(concept, summary)
    if not teaser:
        log.warning("AI teaser generation failed — falling back to raw narration snippet.")
        snippet = summary[:200].rsplit(".", 1)[0] + "."
        teaser = {
            "hook": f"Did you know about {concept}?",
            "teaser": snippet,
            "cta": "Watch the full video on Brainboda for more. Link in bio!",
        }

    hook_text = teaser["hook"]
    teaser_text = teaser["teaser"]
    cta_text = teaser["cta"]

    # Single "fact" entry for the render pipeline (teaser body)
    hook_dur = estimate_duration(hook_text)
    teaser_dur = estimate_duration(teaser_text)
    cta_dur = estimate_duration(cta_text)

    fact_entry = {
        "n": 1,
        "heading": concept,
        "narration": teaser_text,
        "search_keywords": chosen.get("search_keywords", ["psychology", "mind", "brain"]),
        "duration_est": teaser_dur,
        "id": re.sub(r"[^a-z0-9]+", "_", concept.lower()).strip("_"),
        "source_url": chosen.get("source_url", ""),
        "key_insight": chosen.get("key_insight", ""),
    }

    title = f"{concept} — Did You Know? #Shorts | Brainboda"
    tags = main_script.get("tags", [])
    if "shorts" not in [t.lower() for t in tags]:
        tags = ["shorts", "psychology shorts"] + tags

    script_data = {
        "type": "short",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "ai_generated": True,
        "from_main": os.path.abspath(main_script_path),
        "chosen_fact": concept,
        "title": title,
        "thumbnail_hook": concept,
        "hook": hook_text,
        "facts": [fact_entry],
        "outro": cta_text,
        "tags": tags,
        "hook_duration_est": hook_dur,
        "outro_duration_est": cta_dur,
        "total_duration_est": hook_dur + teaser_dur + cta_dur,
        "description": _build_short_description(concept, main_script_path),
    }

    if not dry_run:
        used_headings.append(concept)
        _save_used_shorts_facts(used_headings)
        log.info("Marked '%s' as used for Shorts", concept)

    return script_data


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build video script from psychology facts")
    parser.add_argument("--type", choices=["main", "short"], default="main")
    parser.add_argument("--topic", type=str, default=None,
                        help="(Wikipedia mode) Filter facts by topic keyword")
    parser.add_argument("--ai", action="store_true",
                        help="Use Claude AI to generate script instead of Wikipedia facts")
    parser.add_argument("--theme", type=str, default=None,
                        help="(AI mode) Theme for the video e.g. 'dark psychology'")
    parser.add_argument("--from-main", type=str, default=None,
                        help="(Shorts mode) Path to main script JSON — extracts best fact for Short")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, write no files")
    parser.add_argument("--run-dir", type=str, default=None,
                        help="Run output directory. If provided, save script as {run-dir}/script.json")
    args = parser.parse_args()

    log.info("=== 02_build_script.py START ===")
    log.info("Type: %s | AI: %s | Theme: %s | FromMain: %s | Dry-run: %s",
             args.type, args.ai, args.theme or "auto", args.from_main or "no", args.dry_run)

    n_needed = FACTS_PER_SHORT if args.type == "short" else FACTS_PER_VIDEO

    # ── Shorts from main mode ─────────────────────────────────────────────────
    if args.from_main:
        if not os.path.exists(args.from_main):
            log.error("Main script not found: %s", args.from_main)
            sys.exit(1)
        run_dir = args.run_dir or os.path.join(OUTPUT_DIR,
            datetime.now().strftime("%Y%m%d_%H%M%S") + "_short")
        os.makedirs(run_dir, exist_ok=True)
        log.info("Generating Short from main script: %s", args.from_main)
        script = build_script_short_from_main(args.from_main, run_dir, dry_run=args.dry_run)
        if not script:
            log.error("Short-from-main generation failed.")
            sys.exit(1)

    # ── AI mode ───────────────────────────────────────────────────────────────
    elif args.ai:
        used_concepts = _load_used_concepts()
        theme = _pick_theme(args.theme, used_concepts)
        log.info("AI mode | theme: %s", theme)
        script = build_script_ai(theme, args.type, n_needed, dry_run=args.dry_run)
        if not script:
            log.error("AI script generation failed.")
            sys.exit(1)
    # ── Wikipedia mode (default) ──────────────────────────────────────────────
    else:
        available = load_available_facts(topic=args.topic)
        if not available:
            log.error("No available facts. Run 01_fetch_facts.py first.")
            sys.exit(1)

        selected = pick_facts(available, n_needed, args.topic)
        if not selected:
            log.error("Could not select enough facts.")
            sys.exit(1)

        log.info("Selected %d facts for %s video", len(selected), args.type)
        script = build_script(selected, video_type=args.type)

    # ── output ────────────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.run_dir:
        os.makedirs(args.run_dir, exist_ok=True)
        script_path = os.path.join(args.run_dir, "script.json")
    else:
        script_path = os.path.join(OUTPUT_DIR, f"script_{args.type}_{timestamp}.json")

    if not args.dry_run:
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2, ensure_ascii=False)
        log.info("Script saved → %s", script_path)

        if not args.ai and not args.from_main:
            # Mark Wikipedia facts as used (AI mode tracks concepts separately)
            used_ids = {f["id"] for f in selected}
            save_used_ids(used_ids)
            log.info("Marked %d fact IDs as used in %s", len(used_ids), USED_FACTS_JSON)
    else:
        log.info("[DRY RUN] Script NOT saved. No IDs marked as used.")
        script_path = "(dry-run, not saved)"

    log.info("=== 02_build_script.py DONE ===")

    # ── preview ───────────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  VIDEO TYPE : {script['type'].upper()}")
    print(f"  TITLE      : {script['title']}")
    print(f"  DURATION   : ~{script['total_duration_est']}s ({script['total_duration_est']//60}m{script['total_duration_est']%60}s)")
    print(f"  FACTS      : {len(script['facts'])}")
    print(f"  OUTPUT     : {script_path}")
    print(f"{'='*65}")
    print(f"\n[HOOK]\n  {script['hook']}\n")
    for b in script["facts"]:
        print(f"[FACT {b['n']}] {b['heading']} (~{b['duration_est']}s)")
        print(f"  {b['narration'][:120]}...")
        print()
    print(f"[OUTRO]\n  {script['outro']}\n")
    print(f"[TAGS] {', '.join(script['tags'][:8])} ...")

    return script_path


if __name__ == "__main__":
    main()
